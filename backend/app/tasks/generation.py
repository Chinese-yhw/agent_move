"""生成类 Celery 任务：标准照 / 镜头视频 / 配音 / 合成导出。

设计要点（对应 ¥500/100集 成本控制）：
- worker_prefetch_multiplier=1 + 单 GPU worker：任务串行排队，机器利用率拉满、不空转
- 每个任务完成后按「实际 GPU 占用秒数 × 时租」写回 tasks.cost_yuan，费用可审计
- 失败自动重试 1 次（网络抖动/显存不足场景）
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import (
    Asset, Dialogue, ImageCandidate, Project, StoryboardShot, Task,
    TaskStatus, TaskType, VideoCandidate, ShotStatus, CandidateStatus,
)
from app.providers.comfyui import ComfyUIProvider
from app.providers.llm import translate_motion_prompt
from app.providers.tts import CosyVoiceProvider
from app.services.compose import export_episode
from app.tasks.celery_app import celery_app

settings = get_settings()

# Celery 内用同步引擎（异步 ORM 只给 API 层用）
if "sqlite" in settings.database_url:
    _sync_url = "sqlite:///./data/drama_gen.db"
else:
    _sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
Engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSession = sessionmaker(Engine, class_=Session, expire_on_commit=False)


def _media_url(local: Path) -> str:
    """本地文件 → 平台可访问 URL。"""
    rel = Path(local).resolve().relative_to(Path(settings.media_root).resolve())
    return f"{settings.media_base_url}/{rel.as_posix()}"


def _gpu_cost(seconds: float) -> float:
    return round(seconds / 3600 * settings.gpu_hourly_cost, 4)


def _mark(task_id: int, status: TaskStatus, result: dict | None = None,
          error: str | None = None, cost: float = 0.0):
    with SyncSession() as db:
        t = db.get(Task, task_id)
        if t:
            t.status = status
            t.result = result
            t.error = error
            t.cost_yuan = cost
            t.progress = 100 if status == TaskStatus.success else t.progress
            t.finished_at = datetime.now(timezone.utc)
            db.commit()


def _on_failure(task_self, exc, task_id, args, kwargs, einfo):
    """Celery 失败回调（含重试耗尽）：把 tasks 表状态置为 failed。

    否则任务函数里 raise self.retry 最终放弃后，DB 行会永远停在 pending，
    前端进度条会一直转圈（表现为“点击生成没反应”）。
    所有生成任务的第一个位置参数都是 DB tasks.id。
    """
    db_task_id = args[0] if args else kwargs.get("task_id")
    if db_task_id is not None:
        _mark(db_task_id, TaskStatus.failed, error=f"{type(exc).__name__}: {exc}")


class _Heartbeat:
    """任务运行期心跳：按预估耗时把 progress 从 5% 平滑推到 95%。

    GPU 生成是整体阻塞的（拿不到 ComfyUI 单步进度），用时间估算兜底，
    前端轮询 tasks.progress 即可看到进度条持续走动。
    """

    def __init__(self, task_id: int, eta_seconds: float):
        self.task_id = task_id
        self.eta = max(eta_seconds, 1.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        with SyncSession() as db:
            t = db.get(Task, self.task_id)
            if t:
                t.status = TaskStatus.running
                t.progress = 5
                db.commit()
        self._start_ts = time.time()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(3):
            ratio = (time.time() - self._start_ts) / self.eta
            pct = min(int(5 + ratio * 90), 95)
            with SyncSession() as db:
                t = db.get(Task, self.task_id)
                if t and t.status == TaskStatus.running:
                    t.progress = max(t.progress, pct)
                    db.commit()

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return False


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30, on_failure=_on_failure)
def generate_standard_images(self, task_id: int, asset_id: int, n: int, width: int, height: int):
    """素材标准照抽卡：生成 N 张候选图。"""
    with SyncSession() as db:
        asset = db.get(Asset, asset_id)
        if not asset:
            _mark(task_id, TaskStatus.failed, error=f"素材 id={asset_id} 不存在")
            return
        project = db.get(Project, asset.project_id)
        style = project.style if project else "中性"
        prompt = f"{style}风格，{asset.description}"
        negative = "low quality, blurry, deformed, extra limbs, watermark, text"

    start = time.time()
    try:
        provider = ComfyUIProvider()
        with _Heartbeat(task_id, eta_seconds=n * 25):  # 4090 上约 20~30s/张
            images = provider.generate_images(prompt, negative, n, width, height)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)

    cost = _gpu_cost(time.time() - start)
    with SyncSession() as db:
        urls = []
        for img in images:
            c = ImageCandidate(
                asset_id=asset_id, image_url=_media_url(img), prompt=prompt,
                seed=int(time.time()) % 2**31, model="comfyui-z-image",
            )
            db.add(c)
            urls.append(c.image_url)
        a = db.get(Asset, asset_id)
        if a and a.status != "已锁定":
            from app.models import AssetStatus
            a.status = AssetStatus.generated
        db.commit()
        _mark(task_id, TaskStatus.success, {"candidates": urls}, cost=cost)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60, on_failure=_on_failure)
def generate_shot_videos(self, task_id: int, shot_id: int, n: int):
    """镜头视频抽卡：首帧=关联角色/场景标准照，提示词=动作描述（必要时 LLM 翻译）。"""
    with SyncSession() as db:
        shot = db.get(StoryboardShot, shot_id)
        first_frame_local = _pick_first_frame(db, shot)
        motion = shot.motion_prompt or translate_motion_prompt(shot.description, shot.camera_movement)
        if not shot.motion_prompt:
            shot.motion_prompt = motion
        shot.status = ShotStatus.running
        duration = shot.duration
        db.commit()

    if first_frame_local is None or not first_frame_local.exists():
        _mark(task_id, TaskStatus.failed, error="缺少首帧：请先为该镜头关联的角色/场景生成并锁定标准照")
        return

    negative = ("low quality, blurry, distorted face, deformed hands, watermark, text, "
                "static image, no motion, flickering, changing face, different person")
    start = time.time()
    try:
        provider = ComfyUIProvider()
        videos = []
        with _Heartbeat(task_id, eta_seconds=n * (duration * 12 + 60)):  # 480p i2v 经验值
            for _ in range(max(1, n)):  # 多候选=多次提交（每次自动换种子）
                videos.append(provider.generate_video(first_frame_local, motion, negative, duration))
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)

    cost = _gpu_cost(time.time() - start)
    with SyncSession() as db:
        urls = []
        for v in videos:
            c = VideoCandidate(
                shot_id=shot_id, video_url=_media_url(v), duration=duration,
                prompt=motion, model="wan2.1-i2v-480p",
            )
            db.add(c)
            urls.append(c.video_url)
        db.get(StoryboardShot, shot_id).status = ShotStatus.review
        db.commit()
        _mark(task_id, TaskStatus.success, {"candidates": urls}, cost=cost)


@celery_app.task(bind=True, max_retries=1, on_failure=_on_failure)
def generate_dialogue_audios(self, task_id: int, dialogue_ids: list[int]):
    """批量配音：台词 → CosyVoice。"""
    provider = CosyVoiceProvider()
    results, errors = {}, []
    start = time.time()
    with SyncSession() as db:
        rows = db.execute(select(Dialogue).where(Dialogue.id.in_(dialogue_ids))).scalars().all()
        char_names = {a.id: a.name for a in db.scalars(select(Asset)).unique()}
        for d in rows:
            voice = d.voice_id or (char_names.get(d.character_id, "default"))
            try:
                audio = provider.tts(d.text, voice_id=voice, emotion=d.emotion)
                d.audio_url = _media_url(audio)
                results[d.id] = d.audio_url
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(f"台词{d.id}: {exc}")
    cost = _gpu_cost(time.time() - start) * 0.1  # TTS 占用极小，按 10% 折算
    if errors and not results:
        _mark(task_id, TaskStatus.failed, error="; ".join(errors), cost=cost)
    else:
        _mark(task_id, TaskStatus.success, {"audios": results, "errors": errors}, cost=cost)


@celery_app.task(bind=True, max_retries=1, on_failure=_on_failure)
def compose_episode(self, task_id: int, script_id: int, bgm_path: str | None, burn_subtitle: bool):
    """合成整集：通过镜头按镜号拼接 + 配音对齐 + 字幕烧录。"""
    with SyncSession() as db:
        shots = db.execute(
            select(StoryboardShot)
            .where(StoryboardShot.script_id == script_id,
                   StoryboardShot.status == ShotStatus.approved)
            .order_by(StoryboardShot.shot_no)
        ).scalars().all()
        items = []
        for s in shots:
            winner = db.execute(
                select(VideoCandidate).where(
                    VideoCandidate.shot_id == s.id,
                    VideoCandidate.status == CandidateStatus.approved,
                ).limit(1)
            ).scalar_one_or_none()
            if not winner:
                continue
            # 显式查询台词，避免 ORM 关系懒加载（异步 Session 下会 MissingGreenlet）
            dialogues = db.execute(
                select(Dialogue).where(Dialogue.shot_id == s.id)
            ).scalars().all()
            audios = [d.audio_url for d in dialogues if d.audio_url]
            subs = [(d.text, d.character_id) for d in dialogues]
            items.append({
                "video": _url_to_path(winner.video_url),
                "audios": [_url_to_path(u) for u in audios],
                "subtitles": subs,
                "duration": s.duration,
            })
        if not items:
            _mark(task_id, TaskStatus.failed, error="没有已通过的镜头，请先审核通过至少一个镜头")
            return
        out = export_episode(items, bgm_path, burn_subtitle)
        url = _media_url(out)
        _mark(task_id, TaskStatus.success, {"video_url": url})


def _pick_first_frame(db: Session, shot: StoryboardShot) -> Path | None:
    """统一首帧选取：手动指定 > 第一个有标准照的关联角色 > 场景标准照。"""
    candidate_ids: list = []
    if shot.first_frame_asset_id:
        candidate_ids.append(shot.first_frame_asset_id)
    candidate_ids.extend(shot.character_ids or [])
    if shot.scene_id:
        candidate_ids.append(shot.scene_id)
    for cid in candidate_ids:
        a = db.get(Asset, cid)
        if a and a.standard_image:
            return _url_to_path(a.standard_image)
    return None


def _url_to_path(url: str) -> Path:
    rel = url.removeprefix(settings.media_base_url + "/")
    return Path(settings.media_root) / rel
