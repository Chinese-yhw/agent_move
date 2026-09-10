"""REST API 路由：项目/剧本/分镜 → 检测/提取 → 标准照抽卡 → 镜头视频抽卡 → 配音 → 合成。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    Asset, AssetStatus, CandidateStatus, Dialogue, ImageCandidate, Project,
    Script, ShotStatus, StoryboardShot, Task, TaskStatus, TaskType, VideoCandidate,
)
from app.schemas import (
    ApproveVideoReq, ComposeReq, GenerateImagesReq, GenerateVideoReq,
    ProjectCreate, ProjectOut, ScriptCreate, ScriptUpdate, ScriptOut,
    SetFirstFrameReq,
    ShotIn, ShotsImport, ShotOut, ShotRefOut, DialogueBrief,
    TtsGenerateReq, AssetOut, AssetUpdate, SelectCandidateReq, TaskOut,
)
from app.tasks.generation import (
    compose_episode, generate_dialogue_audios, generate_shot_videos, generate_shot_images,
    generate_standard_images,
)

router = APIRouter(prefix="/api")


# ---------- 项目 / 剧本 ----------
@router.post("/projects", response_model=ProjectOut)
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_db)):
    p = Project(name=req.name, style=req.style)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Project).order_by(Project.id.desc()))).scalars().all()


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """删除项目及其全部数据：剧本→分镜→视频候选/台词，素材→图片候选，任务记录。"""
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    script_ids = (await db.execute(
        select(Script.id).where(Script.project_id == project_id)
    )).scalars().all()
    asset_ids = (await db.execute(
        select(Asset.id).where(Asset.project_id == project_id)
    )).scalars().all()
    shot_ids: list = []
    if script_ids:
        shot_ids = (await db.execute(
            select(StoryboardShot.id).where(StoryboardShot.script_id.in_(script_ids))
        )).scalars().all()
    if shot_ids:
        await db.execute(delete(VideoCandidate).where(VideoCandidate.shot_id.in_(shot_ids)))
        await db.execute(delete(Dialogue).where(Dialogue.shot_id.in_(shot_ids)))
        await db.execute(delete(StoryboardShot).where(StoryboardShot.id.in_(shot_ids)))
    if asset_ids:
        await db.execute(delete(ImageCandidate).where(ImageCandidate.asset_id.in_(asset_ids)))
        await db.execute(delete(Asset).where(Asset.id.in_(asset_ids)))
    if script_ids:
        await db.execute(delete(Script).where(Script.id.in_(script_ids)))
    # 任务记录按关联对象清理（detect/extract/tts/compose→剧本，video→镜头，image→素材）
    ref_ids = list(script_ids) + list(shot_ids) + list(asset_ids)
    if ref_ids:
        await db.execute(delete(Task).where(Task.ref_id.in_(ref_ids)))
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/scripts", response_model=dict)
async def create_script(project_id: int, req: ScriptCreate, db: AsyncSession = Depends(get_db)):
    s = Script(project_id=project_id, chapter=req.chapter, title=req.title, content=req.content)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return {"id": s.id}


@router.get("/projects/{project_id}/scripts", response_model=list[ScriptOut])
async def list_scripts(project_id: int, db: AsyncSession = Depends(get_db)):
    """项目下所有剧本（含分镜数量），供历史查看/选择。"""
    rows = await db.execute(
        select(Script).where(Script.project_id == project_id).order_by(Script.chapter, Script.id)
    )
    out = []
    for s in rows.scalars().all():
        cnt = (await db.execute(
            select(func.count(StoryboardShot.id)).where(StoryboardShot.script_id == s.id)
        )).scalar_one()
        out.append(ScriptOut(id=s.id, project_id=s.project_id, chapter=s.chapter,
                             title=s.title, content=s.content, shot_count=cnt))
    return out


@router.get("/scripts/{script_id}", response_model=ScriptOut)
async def get_script(script_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "剧本不存在")
    cnt = (await db.execute(
        select(func.count(StoryboardShot.id)).where(StoryboardShot.script_id == script_id)
    )).scalar_one()
    return ScriptOut(id=s.id, project_id=s.project_id, chapter=s.chapter,
                     title=s.title, content=s.content, shot_count=cnt)


@router.put("/scripts/{script_id}", response_model=ScriptOut)
async def update_script(script_id: int, req: ScriptUpdate, db: AsyncSession = Depends(get_db)):
    s = await db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "剧本不存在")
    if req.title is not None:
        s.title = req.title
    if req.content is not None:
        s.content = req.content
    if req.chapter is not None:
        s.chapter = req.chapter
    await db.commit()
    await db.refresh(s)
    shot_count = (await db.execute(
        select(func.count(StoryboardShot.id)).where(StoryboardShot.script_id == script_id)
    )).scalar_one()
    return ScriptOut(id=s.id, project_id=s.project_id, chapter=s.chapter, title=s.title, content=s.content, shot_count=shot_count)

@router.delete("/scripts/{script_id}")
async def delete_script(script_id: int, db: AsyncSession = Depends(get_db)):
    """删除剧本及其分镜/候选/台词（异步 Session 需显式查询，不能依赖关系懒加载）。"""
    s = await db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "剧本不存在")
    shot_ids = (await db.execute(
        select(StoryboardShot.id).where(StoryboardShot.script_id == script_id)
    )).scalars().all()
    if shot_ids:
        await db.execute(delete(VideoCandidate).where(VideoCandidate.shot_id.in_(shot_ids)))
        await db.execute(delete(Dialogue).where(Dialogue.shot_id.in_(shot_ids)))
        await db.execute(delete(StoryboardShot).where(StoryboardShot.id.in_(shot_ids)))
    # 同时删除该剧本产生的检测/提取任务记录
    await db.execute(delete(Task).where(
        Task.ref_id == script_id,
        Task.type.in_([TaskType.detect, TaskType.extract]),
    ))
    await db.delete(s)
    await db.commit()
    return {"ok": True}


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, db: AsyncSession = Depends(get_db)):
    """删除素材及其候选图。引用该素材的镜头 scene_id / first_frame_asset_id 自动置 NULL。"""
    a = await db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404, "素材不存在")
    await db.delete(a)
    await db.commit()
    return {"ok": True}


@router.delete("/shots/{shot_id}")
async def delete_shot(shot_id: int, db: AsyncSession = Depends(get_db)):
    """删除镜头及其全部候选视频和台词。"""
    s = await db.get(StoryboardShot, shot_id)
    if not s:
        raise HTTPException(404, "镜头不存在")
    await db.delete(s)
    await db.commit()
    return {"ok": True}


@router.delete("/shots/{shot_id}/dialogues/{dialogue_id}")
async def delete_dialogue(shot_id: int, dialogue_id: int, db: AsyncSession = Depends(get_db)):
    """删除某条台词。"""
    d = await db.get(Dialogue, dialogue_id)
    if not d or d.shot_id != shot_id:
        raise HTTPException(404, "台词不存在")
    await db.delete(d)
    await db.commit()
    return {"ok": True}


def _resolve_first_frame_id(shot: StoryboardShot, assets: dict[int, Asset]) -> int | None:
    """首帧素材 ID：手动指定 > 第一个有标准照的角色 > 场景。与 worker 逻辑保持一致。"""
    candidate_ids: list = []
    if shot.first_frame_asset_id:
        candidate_ids.append(shot.first_frame_asset_id)
    candidate_ids.extend(shot.character_ids or [])
    if shot.scene_id:
        candidate_ids.append(shot.scene_id)
    for cid in candidate_ids:
        a = assets.get(cid)
        if a and a.standard_image:
            return a.id
    return None


async def _shots_with_dialogues(script_id: int, db: AsyncSession) -> list[ShotOut]:
    """查分镜并显式附带台词 + 关联素材（角色/场景标准照、首帧标记）。"""
    rows = await db.execute(
        select(StoryboardShot).where(StoryboardShot.script_id == script_id)
        .order_by(StoryboardShot.shot_no)
    )
    shots = rows.scalars().all()

    # 项目全部素材（用于首帧/角色名/关联素材展示）
    script = await db.get(Script, script_id)
    assets: dict[int, Asset] = {}
    if script:
        asset_rows = await db.execute(
            select(Asset).where(Asset.project_id == script.project_id)
        )
        assets = {a.id: a for a in asset_rows.scalars().all()}

    dlg_rows = await db.execute(
        select(Dialogue).where(Dialogue.shot_id.in_([s.id for s in shots] or [-1]))
    )
    by_shot: dict[int, list] = {}
    for d in dlg_rows.scalars().all():
        char_asset = assets.get(d.character_id)
        by_shot.setdefault(d.shot_id, []).append(DialogueBrief(
            id=d.id, character=char_asset.name if char_asset else d.speaker_name,
            text=d.text, emotion=d.emotion,
        ))

    out: list[ShotOut] = []
    for s in shots:
        first_id = _resolve_first_frame_id(s, assets)
        ref_ids: list = []
        # 手动指定的首帧即使不在关联角色/场景中，也要展示出来
        if s.first_frame_asset_id:
            ref_ids.append(s.first_frame_asset_id)
        if s.scene_id:
            ref_ids.append(s.scene_id)
        ref_ids.extend(s.character_ids or [])
        seen: set[int] = set()
        refs = []
        for aid in ref_ids:
            if aid in seen:
                continue
            seen.add(aid)
            a = assets.get(aid)
            if not a:
                continue
            refs.append(ShotRefOut(
                id=a.id, name=a.name, type=a.type,
                standard_image=a.standard_image,
                status=a.status.value if hasattr(a.status, "value") else str(a.status or ""),
                is_first_frame=(a.id == first_id),
            ))
        data = {c.name: getattr(s, c.name) for c in s.__table__.columns}
        out.append(ShotOut.model_validate({
            **data, "refs": refs, "dialogues": by_shot.get(s.id, []),
        }))
    return out


@router.get("/scripts/{script_id}/shots", response_model=list[ShotOut])
async def list_shots(script_id: int, db: AsyncSession = Depends(get_db)):
    return await _shots_with_dialogues(script_id, db)


@router.post("/scripts/{script_id}/shots", response_model=list[ShotOut])
async def import_shots(script_id: int, req: ShotsImport, db: AsyncSession = Depends(get_db)):
    """批量导入分镜（前端表格/Excel 解析后提交）。角色名自动关联素材表 ID。"""
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404, "剧本不存在")
    assets = (await db.execute(
        select(Asset).where(Asset.project_id == script.project_id)
    )).scalars().all()
    name_to_id = {a.name: a.id for a in assets}
    scene_name_to_id = {a.name: a.id for a in assets if a.type == "scene"}

    for sh in req.shots:
        shot = StoryboardShot(
            script_id=script_id, shot_no=sh.shot_no, scene=sh.scene,
            description=sh.description,
            image_prompt=sh.image_prompt,
            negative_prompt=sh.negative_prompt,
            motion_prompt=sh.motion_prompt,
            duration=sh.duration, camera_movement=sh.camera_movement,
            shot_size=sh.shot_size,
            dramatic_analysis=sh.dramatic_analysis,
            visual_notes=sh.visual_notes,
            emotion_tone=sh.emotion_tone,
            character_ids=[name_to_id[n] for n in sh.character_names if n in name_to_id],
            scene_id=scene_name_to_id.get(sh.scene),
        )
        db.add(shot)
        await db.flush()
        for d in sh.dialogues:
            speaker = d.get("character", "")
            db.add(Dialogue(
                shot_id=shot.id, text=d.get("text", ""),
                emotion=d.get("emotion", "平静"),
                speaker_name=speaker,
                character_id=name_to_id.get(speaker),
            ))
    await db.commit()
    return await _shots_with_dialogues(script_id, db)


@router.post("/scripts/{script_id}/shots/replace", response_model=list[ShotOut])
async def replace_shots(script_id: int, req: ShotsImport, db: AsyncSession = Depends(get_db)):
    """整体替换分镜（AI 重新生成后覆盖旧表用）。"""
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404, "剧本不存在")
    old_ids = (await db.execute(
        select(StoryboardShot.id).where(StoryboardShot.script_id == script_id)
    )).scalars().all()
    if old_ids:
        await db.execute(delete(VideoCandidate).where(VideoCandidate.shot_id.in_(old_ids)))
        await db.execute(delete(Dialogue).where(Dialogue.shot_id.in_(old_ids)))
        await db.execute(delete(StoryboardShot).where(StoryboardShot.id.in_(old_ids)))
    await db.commit()
    return await import_shots(script_id, req, db)


@router.post("/scripts/{script_id}/generate_storyboard", response_model=dict)
async def ai_generate_storyboard(script_id: int, db: AsyncSession = Depends(get_db)):
    """第2步A：AI 把剧本正文拆成分镜草稿并写入表格（覆盖旧分镜），供用户检查修改。"""
    from app.providers.llm import generate_storyboard
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404, "剧本不存在")
    if not script.content.strip():
        raise HTTPException(400, "剧本正文为空，请先在剧本页填写正文并保存")
    try:
        shots_raw = generate_storyboard(script.content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AI 生成分镜失败: {exc}")

    payload = ShotsImport(shots=[_coerce_shot(x) for x in shots_raw])
    created = await replace_shots(script_id, payload, db)
    return {"created": len(created), "shots": [s.shot_no for s in created]}


def _coerce_shot(x: dict) -> ShotIn:
    """LLM 输出字段容错：补默认值、裁剪时长。"""
    return ShotIn(
        shot_no=int(x.get("shot_no", 0) or 0),
        scene=str(x.get("scene", "")),
        description=str(x.get("description", "")),
        motion_prompt=str(x.get("motion_prompt", "")),
        duration=min(max(float(x.get("duration", 5) or 5), 3.0), 8.0),
        camera_movement=str(x.get("camera_movement", "")),
        shot_size=str(x.get("shot_size", "")),
        character_names=[str(n) for n in (x.get("character_names") or [])],
        dialogues=[d for d in (x.get("dialogues") or []) if isinstance(d, dict)],
    )


@router.post("/scripts/{script_id}/shots/upload")
async def upload_storyboard_txt(script_id: int, file: UploadFile = File(...),
                                replace: bool = Form(True), db: AsyncSession = Depends(get_db)):
    """上传分镜表：自动识别格式——Tab/Markdown 表格 或 段落式 Markdown 分镜拆解。"""
    from app.services.importers import (
        parse_storyboard_table, parse_storyboard_md, looks_like_md_paragraph,
    )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="ignore")

    shots: list[dict] = []
    fmt = ""
    if looks_like_md_paragraph(text):
        shots = parse_storyboard_md(text)
        fmt = "段落式 Markdown 分镜拆解"
    else:
        shots = parse_storyboard_table(text)
        fmt = "表格"

    if not shots:
        shots = parse_storyboard_md(text)
        if shots:
            fmt = "段落式 Markdown 分镜拆解（自动回退）"

    if not shots:
        raise HTTPException(
            400,
            "未解析出任何分镜行。支持格式：\n"
            "  · 表格：Tab 分隔 / Markdown 表格 / 2+ 空格分隔，含「镜号」表头\n"
            "  · 段落 MD：**镜N｜时长 描述** + **剧作目的** / **情感基调** / **视觉风格** / **运镜理由**"
        )
    payload = ShotsImport(shots=[ShotIn(**s) for s in shots])
    if replace:
        created = await replace_shots(script_id, payload, db)
    else:
        created = await import_shots(script_id, payload, db)
    return {"created": len(created), "format": fmt}


@router.post("/scripts/{script_id}/shots/upload-csv")
async def upload_csv_prompts(script_id: int, file: UploadFile = File(...),
                             create_assets: bool = Form(True),
                             db: AsyncSession = Depends(get_db)):
    """上传 CSV 提示词表（2.csv 格式）。

    功能：
    1. 解析 CSV 中的正面/负面 prompt，覆盖到该剧本已有镜头的 image_prompt / negative_prompt
       （如果镜头还没创建，会自动按镜号新建）
    2. 可选：从 prompt 中自动提取角色/场景/道具描述，创建简化素材表（用于标准照生成）
    """
    from app.services.importers import parse_csv_shots, extract_assets_from_shots

    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404, "剧本不存在")
    project_id = script.project_id

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="ignore")

    csv_shots = parse_csv_shots(text)
    if not csv_shots:
        raise HTTPException(400, "CSV 中未解析出任何镜头。请检查列名是否为「镜号, 正面 Prompt, 负面 Prompt」")

    existing_shots = (await db.execute(
        select(StoryboardShot).where(StoryboardShot.script_id == script_id)
    )).scalars().all()
    shot_by_no = {s.shot_no: s for s in existing_shots}

    updated = 0
    created = 0
    for cs in csv_shots:
        if cs["shot_no"] in shot_by_no:
            sh = shot_by_no[cs["shot_no"]]
            sh.image_prompt = cs["image_prompt"]
            sh.negative_prompt = cs["negative_prompt"]
            if cs.get("description"):
                sh.description = cs["description"]
            updated += 1
        else:
            sh = StoryboardShot(
                script_id=script_id,
                shot_no=cs["shot_no"],
                description=cs.get("description", ""),
                image_prompt=cs["image_prompt"],
                negative_prompt=cs["negative_prompt"],
                motion_prompt="",
                duration=cs.get("duration", 5.0),
            )
            db.add(sh)
            created += 1

    asset_count = 0
    if create_assets:
        extracted = extract_assets_from_shots(csv_shots)
        existing_assets = (await db.execute(
            select(Asset).where(Asset.project_id == project_id)
        )).scalars().all()
        existing_names = {a.name: a for a in existing_assets}

        for ea in extracted:
            if ea["name"] in existing_names:
                a = existing_names[ea["name"]]
                if not a.description or len(a.description) < len(ea["description"]):
                    a.description = ea["description"]
            else:
                db.add(Asset(
                    project_id=project_id,
                    type=ea["type"],
                    name=ea["name"],
                    description=ea["description"],
                ))
                asset_count += 1

    await db.commit()

    updated_all = (await db.execute(
        select(StoryboardShot).where(StoryboardShot.script_id == script_id)
    )).scalars().all()
    name_to_asset = {}
    all_assets = (await db.execute(
        select(Asset).where(Asset.project_id == project_id)
    )).scalars().all()
    for a in all_assets:
        name_to_asset[a.name] = a

    for sh in updated_all:
        desc_blob = (sh.image_prompt or sh.description or "")
        char_ids = []
        for aname, aobj in name_to_asset.items():
            if aobj.type == "character" and aname in desc_blob:
                char_ids.append(aobj.id)
        sh.character_ids = char_ids

    await db.commit()
    return {
        "shots_parsed": len(csv_shots),
        "shots_updated": updated,
        "shots_created": created,
        "assets_created": asset_count,
    }


@router.post("/projects/{project_id}/assets/upload")
async def upload_asset_list_txt(project_id: int, file: UploadFile = File(...),
                                script_id: int | None = Form(None),
                                db: AsyncSession = Depends(get_db)):
    """上传素材清单 txt 写入 assets 表。支持两种格式：

    1. 章节式（角色/物品/场景），变体拆成独立素材；
    2. 标准照提示词式（【名字·标准照】+ 提示词），自动判断角色/场景/道具；
       若文件含【镜号N】元素清单且传了 script_id，导入后自动把素材绑定到对应镜头
       （角色名匹配 + 场景模糊匹配），镜头页即可看到首帧对应关系。
    """
    from app.services.importers import (
        link_shots_by_refs, parse_asset_list, parse_std_photo_list,
    )
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="ignore")

    std = parse_std_photo_list(text)
    created = 0
    parsed = 0
    shot_refs: dict = {}
    if std is not None:
        # —— 格式二：标准照提示词式 ——
        items = std["assets"]
        shot_refs = std["shot_refs"]
        if not items:
            raise HTTPException(400, "未解析出任何【名字·标准照】条目，请确认文件格式")
        existing_assets = (await db.execute(
            select(Asset).where(Asset.project_id == project_id)
        )).scalars().all()
        by_name = {a.name: a for a in existing_assets}
        for it in items:
            a = by_name.get(it["name"])
            if a is None:
                db.add(Asset(project_id=project_id, type=it["type"], name=it["name"],
                             description=it["description"],
                             extra={"role": it.get("role", ""), "voice": it.get("voice", "")}))
                created += 1
            elif not a.description:
                a.description = it["description"]  # 旧素材缺描述时用提示词补上
        parsed = len(items)
        await db.flush()
    else:
        # —— 格式一：章节式 ——
        items = parse_asset_list(text)
        if not items:
            raise HTTPException(
                400, "未解析出任何素材：请确认是「角色/物品/场景」章节式清单，"
                     "或包含【名字·标准照】提示词条目")
        existing = {(a.type, a.name) for a in (await db.execute(
            select(Asset).where(Asset.project_id == project_id))).scalars().all()}
        for it in items:
            entries = [(it["name"], it["description"])]
            for v in it["variants"]:
                entries.append((f"{it['name']}·{v['name']}", v["description"]))
            for name, desc in entries:
                if (it["type"], name) in existing:
                    continue
                extra = dict(it.get("extra") or {})
                extra.update({"role": it.get("role", ""), "voice": it.get("voice", ""),
                              "base_name": it["name"]})
                db.add(Asset(project_id=project_id, type=it["type"], name=name,
                             description=desc, extra=extra))
                existing.add((it["type"], name))
                created += 1
        parsed = len(items)

    # 自动关联镜头↔素材（需要镜号清单 + 指定剧本）
    linked_shots = 0
    if shot_refs and script_id:
        script = await db.get(Script, script_id)
        if script and script.project_id == project_id:
            shots = (await db.execute(
                select(StoryboardShot).where(StoryboardShot.script_id == script_id)
            )).scalars().all()
            project_assets = (await db.execute(
                select(Asset).where(Asset.project_id == project_id)
            )).scalars().all()
            linked_shots = link_shots_by_refs(shots, project_assets, shot_refs)
            # 回填台词角色：分镜导入时素材还没建，character_id 为空，现在按说话人名补上
            char_by_name = {a.name: a.id for a in project_assets if a.type == "character"}
            shot_ids = [s.id for s in shots]
            for d in (await db.execute(
                select(Dialogue).where(Dialogue.shot_id.in_(shot_ids))
            )).scalars().all():
                if d.character_id is None and d.speaker_name:
                    cid = char_by_name.get(d.speaker_name)
                    if cid is None:  # "投影·林北望" 这类写法按包含匹配
                        cid = next((nid for nm, nid in char_by_name.items() if nm in d.speaker_name), None)
                    d.character_id = cid

            # 为无关联镜头（黑屏/特效/空镜）自动创建场景素材，使其有首帧可用
            existing_names = {a.name for a in project_assets}
            for sh in shots:
                has_ref = sh.character_ids or sh.scene_id
                if has_ref:
                    continue
                # 用分镜描述作场景素材名和提示词
                desc = (sh.description or "").strip()
                if not desc:
                    continue
                name = f"镜{sh.shot_no}场景"
                if name in existing_names:
                    # 已有同名素材则直接关联
                    a = next((x for x in project_assets if x.name == name), None)
                    if a:
                        sh.scene_id = a.id
                    continue
                a = Asset(
                    project_id=project_id, type="scene", name=name,
                    description=desc,
                )
                db.add(a)
                await db.flush()
                sh.scene_id = a.id
                project_assets.append(a)
                existing_names.add(name)
                created += 1
                linked_shots += 1

    await db.commit()
    return {"created": created, "parsed": parsed, "linked_shots": linked_shots}


# ---------- 检测 / 提取 ----------
async def _run_llm_task(db: AsyncSession, task_type: TaskType, ref_id: int, fn, *args):
    t = Task(type=task_type, ref_id=ref_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    try:
        result = await fn(*args)
        from app.models import TaskStatus
        from datetime import datetime, timezone
        t.status = TaskStatus.success
        t.result = result
        t.progress = 100
        t.finished_at = datetime.now(timezone.utc)
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        from app.models import TaskStatus
        t.status = TaskStatus.failed
        t.error = str(exc)
        await db.commit()
        raise HTTPException(502, f"LLM 调用失败: {exc}")
    return t


@router.post("/scripts/{script_id}/detect", response_model=TaskOut)
async def detect_script(script_id: int, db: AsyncSession = Depends(get_db)):
    """内容检测：返回任务，result.issues 为问题清单。"""
    from app.providers.llm import detect_issues
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404)
    shots = (await db.execute(
        select(StoryboardShot).where(StoryboardShot.script_id == script_id)
        .order_by(StoryboardShot.shot_no)
    )).scalars().all()
    sb = json.dumps([{
        "shot_no": s.shot_no, "scene": s.scene, "description": s.description,
        "duration": s.duration, "camera_movement": s.camera_movement,
        "shot_size": s.shot_size,
    } for s in shots], ensure_ascii=False)
    task = await _run_llm_task(db, TaskType.detect, script_id, detect_issues, script.content, sb)
    return task


@router.post("/scripts/{script_id}/extract", response_model=TaskOut)
async def extract_assets(script_id: int, db: AsyncSession = Depends(get_db)):
    """素材提取：写入 assets 表并返回结果。"""
    from app.providers.llm import extract_assets as llm_extract
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404)
    shots = (await db.execute(
        select(StoryboardShot).where(StoryboardShot.script_id == script_id)
    )).scalars().all()
    sb = json.dumps([{"shot_no": s.shot_no, "scene": s.scene,
                      "description": s.description} for s in shots], ensure_ascii=False)

    async def _extract_and_save():
        data = await llm_extract(script.content, sb)
        saved = {"characters": 0, "scenes": 0, "props": 0}
        for key, typ in [("characters", "character"), ("scenes", "scene"), ("props", "prop")]:
            for item in data.get(key, []):
                exists = (await db.execute(select(Asset).where(
                    Asset.project_id == script.project_id,
                    Asset.type == typ, Asset.name == item.get("name", "")
                ))).scalar_one_or_none()
                if exists:
                    continue
                desc = item.get("appearance") or item.get("description") or ""
                db.add(Asset(
                    project_id=script.project_id, type=typ,
                    name=item.get("name", "未命名"), description=desc,
                    extra={k: v for k, v in item.items() if k not in ("name", "appearance", "description")},
                ))
                saved[key] += 1
        await db.commit()
        return data | {"saved": saved}

    return await _run_llm_task(db, TaskType.extract, script_id, _extract_and_save)


# ---------- 素材与标准照 ----------
@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(
    project_id: int,
    script_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Asset).where(Asset.project_id == project_id)
    if script_id is not None:
        shot_rows = await db.execute(
            select(StoryboardShot).where(StoryboardShot.script_id == script_id)
        )
        shots = shot_rows.scalars().all()
        refs: set[int] = set()
        for shot in shots:
            if shot.scene_id:
                refs.add(shot.scene_id)
            if shot.first_frame_asset_id:
                refs.add(shot.first_frame_asset_id)
            for cid in (shot.character_ids or []):
                refs.add(cid)
        if not refs:
            return []
        query = query.where(Asset.id.in_(refs))
    rows = await db.execute(query)
    return rows.scalars().all()


@router.patch("/assets/{asset_id}", response_model=AssetOut)
async def update_asset(asset_id: int, req: AssetUpdate, db: AsyncSession = Depends(get_db)):
    a = await db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    if req.description is not None:
        a.description = req.description
    if req.reference_image is not None:
        a.reference_image = req.reference_image
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/assets/{asset_id}/reference-image", response_model=AssetOut)
async def upload_reference_image(asset_id: int, file: UploadFile = File(...),
                                 db: AsyncSession = Depends(get_db)):
    """上传角色参考脸图（FaceID 用），存入 media/reference/ 目录，返回更新后的素材。"""
    import uuid as _uuid
    from app.config import get_settings as _gs
    a = await db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    if a.type != "character":
        raise HTTPException(400, "只有角色类型素材可以上传参考脸图")
    ext = (file.filename or ".png").split(".")[-1] or "png"
    settings = _gs()
    ref_dir = Path(settings.media_root) / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{_uuid.uuid4().hex[:12]}.{ext}"
    fpath = ref_dir / fname
    raw = await file.read()
    fpath.write_bytes(raw)
    a.reference_image = f"{settings.media_base_url}/reference/{fname}"
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/assets/{asset_id}/images", response_model=TaskOut)
async def gen_images(asset_id: int, req: GenerateImagesReq, db: AsyncSession = Depends(get_db)):
    a = await db.get(Asset, asset_id)
    if not a:
        raise HTTPException(404)
    t = Task(type=TaskType.image, ref_id=asset_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    r = generate_standard_images.delay(t.id, asset_id, req.n_candidates, req.width, req.height)
    t.celery_id = r.id
    await db.commit()
    return t


@router.get("/assets/{asset_id}/candidates")
async def list_image_candidates(asset_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(ImageCandidate).where(ImageCandidate.asset_id == asset_id)
        .order_by(ImageCandidate.id.desc())
    )
    return [{
        "id": c.id, "image_url": c.image_url, "prompt": c.prompt,
        "is_selected": c.is_selected, "created_at": c.created_at,
    } for c in rows.scalars().all()]


@router.post("/assets/{asset_id}/select")
async def select_standard_image(asset_id: int, req: SelectCandidateReq,
                                db: AsyncSession = Depends(get_db)):
    """抽卡定稿：候选图设为标准照并锁定。"""
    c = await db.get(ImageCandidate, req.candidate_id)
    a = await db.get(Asset, asset_id)
    if not c or not a or c.asset_id != asset_id:
        raise HTTPException(404)
    old = (await db.execute(select(ImageCandidate).where(
        ImageCandidate.asset_id == asset_id, ImageCandidate.is_selected.is_(True)
    ))).scalars().all()
    for o in old:
        o.is_selected = False
    c.is_selected = True
    a.standard_image = c.image_url
    a.status = AssetStatus.locked
    await db.commit()
    return {"ok": True, "standard_image": c.image_url}


# ---------- 镜头首帧图 + 视频 ----------
@router.post("/shots/{shot_id}/images", response_model=TaskOut)
async def gen_shot_images(shot_id: int, req: GenerateImagesReq, db: AsyncSession = Depends(get_db)):
    """镜头首帧图抽卡：用 image_prompt + negative_prompt 生成，IP-Adapter 参考角色/场景标准照。"""
    s = await db.get(StoryboardShot, shot_id)
    if not s:
        raise HTTPException(404)
    if not s.image_prompt and not s.description:
        raise HTTPException(400, "该镜头没有 image_prompt，请先上传 CSV 提示词表")
    t = Task(type=TaskType.image, ref_id=shot_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    r = generate_shot_images.delay(t.id, shot_id, req.n_candidates, req.width, req.height)
    t.celery_id = r.id
    await db.commit()
    return t


@router.get("/shots/{shot_id}/images")
async def list_shot_image_candidates(shot_id: int, db: AsyncSession = Depends(get_db)):
    """查镜头首帧图候选。"""
    rows = await db.execute(
        select(ImageCandidate).where(ImageCandidate.shot_id == shot_id)
        .order_by(ImageCandidate.id.desc())
    )
    return [{"id": c.id, "image_url": c.image_url, "prompt": c.prompt,
             "is_selected": c.is_selected} for c in rows.scalars().all()]


@router.post("/shots/{shot_id}/images/{cid}/select")
async def select_shot_image(shot_id: int, cid: int, db: AsyncSession = Depends(get_db)):
    """选定镜头首帧图（设为 first_frame_image + is_selected）。"""
    c = await db.get(ImageCandidate, cid)
    if not c or c.shot_id != shot_id:
        raise HTTPException(404, "候选图不存在")
    # 取消其他选中
    rows = await db.execute(
        select(ImageCandidate).where(
            ImageCandidate.shot_id == shot_id, ImageCandidate.is_selected.is_(True)
        )
    )
    for prev in rows.scalars().all():
        prev.is_selected = False
    c.is_selected = True
    s = await db.get(StoryboardShot, shot_id)
    if s:
        s.first_frame_image = c.image_url
    await db.commit()
    return {"ok": True, "first_frame_image": c.image_url}


@router.post("/shots/{shot_id}/videos", response_model=TaskOut)
async def gen_video(shot_id: int, req: GenerateVideoReq, db: AsyncSession = Depends(get_db)):
    s = await db.get(StoryboardShot, shot_id)
    if not s:
        raise HTTPException(404)
    # T2V 模式跳过首帧校验；有镜头专属首帧图也可跳过素材校验
    if not req.force_t2v and not s.first_frame_image:
        script = await db.get(Script, s.script_id)
        asset_rows = await db.execute(
            select(Asset).where(Asset.project_id == script.project_id)
        )
        assets = {a.id: a for a in asset_rows.scalars().all()}
        if _resolve_first_frame_id(s, assets) is None:
            raise HTTPException(
                400,
                "该镜头还没有可用首帧：请先为关联角色/场景锁定标准照，"
                "或在下方手动选择一个素材作为首帧；也可以勾选「特效模式（文生视频）」直接生成",
            )
    if req.duration:
        s.duration = min(max(req.duration, 3), 8)
    t = Task(type=TaskType.video, ref_id=shot_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    r = generate_shot_videos.delay(t.id, shot_id, req.n_candidates, force_t2v=req.force_t2v)
    t.celery_id = r.id
    await db.commit()
    return t


@router.post("/shots/{shot_id}/first-frame")
async def set_first_frame(shot_id: int, req: SetFirstFrameReq,
                          db: AsyncSession = Depends(get_db)):
    """手动指定镜头首帧素材（须已锁定标准照）；asset_id=null 恢复自动选取。"""
    s = await db.get(StoryboardShot, shot_id)
    if not s:
        raise HTTPException(404)
    if req.asset_id is not None:
        a = await db.get(Asset, req.asset_id)
        if not a or not a.standard_image:
            raise HTTPException(400, "该素材还没有锁定的标准照，不能作为首帧")
        s.first_frame_asset_id = req.asset_id
    else:
        s.first_frame_asset_id = None
    await db.commit()
    return {"ok": True, "first_frame_asset_id": s.first_frame_asset_id}


@router.get("/scripts/{script_id}/assets", response_model=list[AssetOut])
async def list_script_assets(script_id: int, db: AsyncSession = Depends(get_db)):
    """镜头页选首帧用：剧本所属项目的全部素材。"""
    script = await db.get(Script, script_id)
    if not script:
        raise HTTPException(404)
    rows = await db.execute(
        select(Asset).where(Asset.project_id == script.project_id)
        .order_by(Asset.type, Asset.id)
    )
    return rows.scalars().all()


@router.get("/shots/{shot_id}/candidates")
async def list_video_candidates(shot_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(VideoCandidate).where(VideoCandidate.shot_id == shot_id)
        .order_by(VideoCandidate.id.desc())
    )
    return [{
        "id": c.id, "video_url": c.video_url, "prompt": c.prompt,
        "status": c.status.value, "duration": c.duration,
    } for c in rows.scalars().all()]


@router.post("/shots/{shot_id}/approve")
async def approve_video(shot_id: int, req: ApproveVideoReq, db: AsyncSession = Depends(get_db)):
    """镜头审核通过：选中候选置 approved，镜头状态→通过，其余淘汰。"""
    c = await db.get(VideoCandidate, req.candidate_id)
    if not c or c.shot_id != shot_id:
        raise HTTPException(404)
    others = await db.execute(
        select(VideoCandidate).where(VideoCandidate.shot_id == shot_id,
                                     VideoCandidate.id != c.id)
    )
    for o in others.scalars():
        o.status = CandidateStatus.rejected
    c.status = CandidateStatus.approved
    s = await db.get(StoryboardShot, shot_id)
    s.status = ShotStatus.approved
    await db.commit()
    return {"ok": True}


# ---------- 配音 ----------
@router.get("/scripts/{script_id}/dialogues")
async def list_dialogues(script_id: int, db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Dialogue, StoryboardShot.shot_no)
        .join(StoryboardShot, Dialogue.shot_id == StoryboardShot.id)
        .where(StoryboardShot.script_id == script_id)
        .order_by(StoryboardShot.shot_no, Dialogue.id)
    )
    return [{
        "id": d.id, "shot_id": d.shot_id, "shot_no": shot_no, "character_id": d.character_id,
        "speaker_name": d.speaker_name or "",
        "text": d.text, "emotion": d.emotion, "voice_id": d.voice_id,
        "audio_url": d.audio_url,
    } for d, shot_no in rows.all()]


@router.post("/scripts/{script_id}/tts", response_model=TaskOut)
async def gen_tts(script_id: int, req: TtsGenerateReq, db: AsyncSession = Depends(get_db)):
    ids = req.dialogue_ids
    if not ids:
        rows = await db.execute(
            select(Dialogue.id).join(StoryboardShot).where(
                StoryboardShot.script_id == script_id)
        )
        ids = [r[0] for r in rows.all()]
    if not ids:
        raise HTTPException(400, "没有台词可配音")
    t = Task(type=TaskType.tts, ref_id=script_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    r = generate_dialogue_audios.delay(t.id, ids)
    t.celery_id = r.id
    await db.commit()
    return t


# ---------- 合成导出 ----------
@router.post("/compose/export", response_model=TaskOut)
async def export(req: ComposeReq, db: AsyncSession = Depends(get_db)):
    t = Task(type=TaskType.compose, ref_id=req.script_id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    r = compose_episode.delay(t.id, req.script_id, req.bgm_path, req.burn_subtitle)
    t.celery_id = r.id
    await db.commit()
    return t


# ---------- 任务查询 / 费用看板 ----------
@router.get("/tasks/active")
async def get_active_task(type: str, ref_id: int, db: AsyncSession = Depends(get_db)):
    """查询某对象当前未结束的任务（前端切页回来后恢复进度条）。没在跑时返回 null。"""
    rows = await db.execute(
        select(Task).where(
            Task.type == type,
            Task.ref_id == ref_id,
            Task.status.in_([TaskStatus.pending, TaskStatus.running]),
        ).order_by(Task.id.desc()).limit(1)
    )
    t = rows.scalars().first()
    return t or None


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    t = await db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    return t


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """取消正在执行的异步任务：给 Celery 发 revoke 信号 + 改 DB 状态。
    注意：已经在 ComfyUI 跑的任务无法中断，会继续跑完，但 DB 状态会被标记 cancelled。"""
    from app.tasks.celery_app import celery_app
    t = await db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t.status in (TaskStatus.success, TaskStatus.failed, TaskStatus.cancelled):
        raise HTTPException(400, f"任务已结束（{t.status.value}）")
    # 给 Celery worker 发 revoke —— 如果还没开始会跳过，正在跑的会等当前步骤结束后停止
    if t.celery_id:
        celery_app.control.revoke(t.celery_id, terminate=False, signal='SIGTERM')
    t.status = TaskStatus.cancelled
    t.error = "用户取消"
    from datetime import datetime
    t.finished_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "status": "cancelled"}


@router.delete("/candidates/images/{cid}")
async def delete_image_candidate(cid: int, db: AsyncSession = Depends(get_db)):
    """删除图片候选（+ 删磁盘文件）。"""
    c = await db.get(ImageCandidate, cid)
    if not c:
        raise HTTPException(404, "候选不存在")
    # 删磁盘文件
    url = c.image_url or ""
    local = url.replace("/media/", "")
    local_path = Path(__file__).resolve().parents[2] / "media" / local
    if local_path.exists():
        try:
            local_path.unlink()
        except Exception:
            pass
    await db.delete(c)
    await db.commit()
    return {"ok": True}


@router.delete("/candidates/videos/{cid}")
async def delete_video_candidate(cid: int, db: AsyncSession = Depends(get_db)):
    """删除视频候选（+ 删磁盘文件）。"""
    c = await db.get(VideoCandidate, cid)
    if not c:
        raise HTTPException(404, "候选不存在")
    # 删磁盘文件
    url = c.video_url or ""
    local = url.replace("/media/", "")
    local_path = Path(__file__).resolve().parents[2] / "media" / local
    if local_path.exists():
        try:
            local_path.unlink()
        except Exception:
            pass
    await db.delete(c)
    await db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/costs")
async def project_costs(project_id: int, db: AsyncSession = Depends(get_db)):
    """成本看板：按任务类型汇总 GPU 费用——¥500/100集 目标靠这里盯。"""
    rows = await db.execute(
        select(Task.type, Task.status, Task.cost_yuan)
        .join(Asset, (Asset.id == Task.ref_id) & (Task.type == TaskType.image), isouter=True)
        .where((Asset.project_id == project_id) | (Task.ref_id.in_(
            select(StoryboardShot.id).join(Script).where(Script.project_id == project_id)
        )))
    )
    by_type: dict[str, dict] = {}
    for typ, status, cost in rows.all():
        key = typ.value if hasattr(typ, "value") else str(typ)
        agg = by_type.setdefault(key, {"count": 0, "cost_yuan": 0.0})
        agg["count"] += 1
        agg["cost_yuan"] = round(agg["cost_yuan"] + (cost or 0), 4)
    total = round(sum(v["cost_yuan"] for v in by_type.values()), 4)
    return {"by_type": by_type, "total_yuan": total}
