"""导入《血月》第一集 Markdown 分镜脚本到数据库。

不调 LLM，全部规则解析：Markdown → Project + Script + Assets + StoryboardShots + Dialogues。

运行：
    cd backend
    .\.venv\Scripts\python.exe scripts\import_xueyue.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SQLITE_DB = Path(__file__).resolve().parents[1] / "data" / "drama_gen.db"
MD_PATH = Path(r"e:\agent_move\《血月》第一集 逐镜头分镜拆解＋剧作四要素全案（落地脚本）.md")


# ---------- 翻译映射（中文关键词 → 英文，给 motion_prompt 用） ----------

SHOT_SIZE_MAP = [
    ("大特写", "extreme close-up"), ("极近", "extreme close-up"),
    ("特写", "close-up"), ("脸部特写", "close-up on face"), ("特写锁焦", "static close-up"),
    ("近景", "medium close-up"), ("中近景", "medium close-up"),
    ("中景", "medium shot"), ("中景固定", "static medium shot"), ("中景双人", "medium two-shot"),
    ("全景", "full shot"), ("全景固定", "static full shot"),
    ("远景", "wide shot"), ("远景层叠", "wide establishing shot"),
    ("高空俯瞰", "high angle bird's eye view"), ("高空远景", "high angle wide shot"),
    ("地面特写", "extreme close-up on ground"), ("地面低角度", "low angle close-up on ground"),
    ("手部特写", "close-up on hands"), ("掌心特写", "close-up on palm"),
    ("胸口特写", "close-up on chest"), ("背部特写", "close-up on back"),
    ("门缝特写", "close-up on door crack"),
    ("皮肤特写", "extreme close-up on skin"),
    ("侧镜", "side profile shot"), ("侧方入画", "side entry shot"),
    ("双人镜", "two-shot"),
    ("全画面", "full frame"), ("黑屏", "pitch black screen"),
    ("画面柔光", "soft focus shot"),
]

CAMERA_MOVEMENT_MAP = [
    ("固定", "static camera"), ("静置", "static camera, no movement"),
    ("定点", "static locked-off camera"), ("定点锁焦", "static locked-off close-up"),
    ("锁定", "static locked-off camera"), ("静止", "static camera"),
    ("推近", "slow push in"), ("推特写", "push in to close-up"),
    ("极缓慢推", "extremely slow push in"), ("慢推", "slow push in"),
    ("缓慢淡入", "slow fade in"), ("淡入", "slow fade in"), ("淡出", "fade out"),
    ("跟拍", "tracking shot"), ("跟跑", "running tracking shot"), ("跟随", "following shot"),
    ("长镜头跟随", "long tracking shot"), ("长镜头跟拍奔跑", "long tracking shot following a run"),
    ("环绕", "orbiting shot"),
    ("手持", "handheld camera"), ("手持抖动", "handheld shaky camera"), ("重度手持抖动", "extremely shaky handheld"),
    ("快速跟拍", "fast tracking shot"), ("多镜头快速切换", "rapid quick cuts"), ("快切", "quick cuts"),
    ("俯拍", "high angle shot"), ("全景拉升", "pull back to wide shot"), ("拉升", "slow pull back"),
    ("全景拉升俯拍", "pull back to high angle wide shot"), ("广角全景拉伸", "wide angle pull back"),
    ("跟移", "side tracking shot"), ("小幅跟移", "subtle side tracking"),
    ("摇镜", "pan shot"), ("小幅摇镜", "subtle pan"),
    ("跟随坠落", "tracking fall shot"), ("俯冲", "diving shot"),
    ("双层叠化", "double exposure overlay"),
    ("扫描", "scanning shot"), ("慢推特写扫过", "slow pushing close-up pan across"),
    ("画面静置", "static frame, sound-driven"),
    ("轻微推近", "subtle slow push in"),
    ("轻微稳镜", "subtle stabilized camera"),
    ("轻微抖动", "slight handheld shake"),
]

VISUAL_STYLE_MAP = [
    ("国风仙侠", "Chinese xianxia fantasy aesthetic"), ("国风", "Chinese traditional aesthetic"),
    ("暗黑", "dark and moody"), ("暗黑雾", "dark inky mist"),
    ("晨雾", "morning mist"), ("柔光", "soft golden light"), ("柔光漫洒", "soft diffused light"),
    ("高通透晨雾", "luminous morning mist"),
    ("青灰", "grey-green color palette"), ("青绿", "emerald green palette"),
    ("冷调", "cool color tone"), ("暖调", "warm golden tones"),
    ("暗红", "dark crimson"), ("血色", "blood red tones"), ("血月", "blood moon"),
    ("幽蓝", "ethereal blue glow"), ("微光", "faint glow"), ("金光", "golden glow"),
    ("低饱和", "desaturated colors"), ("高对比", "high contrast"),
    ("高留白", "maximal negative space"), ("极简", "minimalist"),
    ("古篆", "ancient seal script"), ("古朴", "ancient weathered texture"),
    ("写实", "cinematic photorealistic"), ("写实电影感", "photorealistic cinematic"),
    ("画面通透", "crystal clear visuals"),
    ("暗调密闭", "dark enclosed space"), ("石室", "rough stone chamber"),
    ("烟尘", "smoke and ash"), ("浓烟", "heavy smoke"),
    ("压抑", "oppressive lighting"), ("压抑局促", "oppressive and cramped"),
    ("失重", "zero-gravity falling"), ("失重动态", "falling motion blur"),
    ("乱世", "war-torn wasteland"), ("烽烟", "battle smoke"),
    ("黄土", "yellow earth wasteland"), ("苍茫", "vast desolate landscape"),
    ("末世", "post-apocalyptic"), ("末日", "apocalyptic"),
    ("古文字", "ancient oracle bone script"), ("甲骨文", "oracle bone script"),
    ("回忆柔化", "soft focus nostalgic flashback"), ("复古暗调", "vintage dark tone"),
    ("模糊虚影", "translucent ghostly figure"), ("半透明虚影", "semi-transparent apparition"),
    ("时空错位", "anachronistic double exposure"),
    ("巨物压迫", "colossal oppressive presence"), ("巨力", "massive impact"),
    ("破碎", "shattering effect"), ("碎裂", "fragmenting and cracking"),
    ("星河流光", "flowing starlight and nebula"),
    ("生物搏动", "pulsing organic movement"),
    ("暗金微光", "dark gold subtle glow"),
    ("局部打光", "spot lighting"), ("光影聚焦", "dramatic focused lighting"),
    ("面部明暗", "chiaroscuro face lighting"), ("明暗对比", "high contrast chiaroscuro"),
    ("微虚焦", "slight soft focus"),
    ("动态爆发力", "dynamic explosive motion"),
    ("画面压暗", "dimmed frame"),
]

EMOTION_MAP = [
    ("死寂", "deathly silence"), ("肃然", "solemn"), ("肃穆", "solemn and reverent"),
    ("悠远", "ethereal and distant"), ("未知", "uncanny and unknown"),
    ("安宁", "serene"), ("治愈", "healing"), ("清幽", "tranquil and secluded"),
    ("祥和", "peaceful"), ("平和", "calm"), ("清朗", "fresh and clear"),
    ("沉稳", "grounded and composed"), ("淡然", "detached and calm"), ("克制", "restrained"),
    ("轻快", "light and playful"), ("温暖", "warm"), ("纯粹", "innocent"), ("灵动", "energetic and lively"),
    ("温馨", "cozy and warm"), ("亲昵", "affectionate"), ("日常感", "everyday mundane"),
    ("微凉", "subtle chill"), ("微妙", "subtle and uncanny"), ("暗藏神秘", "mysterious undertones"),
    ("平淡", "matter-of-fact"), ("自然", "natural"), ("轻微疑惑", "gently curious"),
    ("骤然凝重", "suddenly grave"), ("隐秘不安", "secretly uneasy"), ("阴霾", "ominous haze"),
    ("紧绷", "tense"), ("警惕", "alert"), ("悬念拉满", "suspended tension"),
    ("炸裂", "explosive"), ("惊悚", "terrifying"), ("猝不及防", "jarring and sudden"), ("窒息", "suffocating"),
    ("恐慌", "panicked"), ("压迫", "oppressive"), ("绝望初显", "early despair"), ("绝望蔓延", "spreading despair"),
    ("惨烈", "tragic and brutal"), ("混乱", "chaotic"),
    ("紧迫", "urgent"), ("奔逃", "frantic escape"), ("生死一线", "life-or-death stakes"), ("窒息", "suffocating urgency"),
    ("悲凉", "heartbreaking"), ("惊悚", "gruesome"), ("不忍直视", "harrowing"),
    ("悲壮", "tragically heroic"), ("急切", "desperate urgency"), ("托付", "solemn entrustment"),
    ("悲怆", "agonizing grief"), ("无力", "powerless"), ("决绝", "resolute"),
    ("沉痛", "heavy grief"), ("漠然", "numbed"),
    ("隐忍", "restrained grief"), ("坚定", "determined"), ("负重前行", "shouldering the burden"),
    ("肃穆", "solemn"), ("悲壮", "tragic"), ("回溯", "nostalgic flashback"), ("宿命悲凉", "fateful melancholy"),
    ("隐忍", "restrained"), ("决绝", "resolute"), ("舍身", "self-sacrificial"),
    ("压抑", "oppressive"), ("窒息", "suffocating"), ("末日降临", "apocalyptic dread"),
    ("绝望", "desperate"), ("慌张", "panicked"), ("无力", "powerless"),
    ("沉稳", "composed"), ("释然", "at peace"), ("悲悯", "compassionate"), ("大爱无声", "quiet compassion"),
    ("忧虑", "anxious"), ("沉重", "heavy with burden"), ("悬而未决", "unresolved tension"),
    ("神圣", "sacred"), ("神秘", "mysterious"), ("宿命厚重", "fateful gravity"),
    ("末日", "apocalyptic"), ("碾压", "overwhelming"), ("绝望顶点", "peak despair"),
    ("幽暗", "dark"), ("局促", "cramped"), ("暂时喘息", "brief respite"), ("暗流涌动", "undercurrent of tension"),
    ("温热", "warm"), ("宿命启动", "destiny unfolding"),
    ("肃穆", "solemn"), ("神圣", "sacred"), ("安静", "quiet"), ("宿命降临", "destiny arrives"),
    ("震撼", "awe-inspiring"), ("庄严", "solemn"),
    ("悲怆", "grieving"), ("温柔", "gentle"), ("厚重", "heavy with gravity"), ("嘱托", "solemn charge"),
    ("沉重", "heavy"), ("决绝", "resolute"), ("遗憾", "lingering regret"), ("寄予厚望", "expectant hope"),
    ("空落", "hollow"), ("沉静", "quiet and still"), ("新旧交替", "transition"),
    ("震撼", "awe"), ("承重", "burdened"), ("宿命附体", "destiny embodied"),
    ("灼痛", "searing pain"), ("隐忍", "gritting through pain"), ("悲壮", "tragic"), ("极致消耗", "extreme cost"),
    ("恢弘", "epic"), ("沧桑", "weathered"), ("文明厚重", "weight of civilization"),
    ("失重", "disorienting"), ("恍惚", "dazed"), ("颠覆", "overturned"), ("未知", "unknown"),
    ("苍凉", "bleak"), ("陌生", "alien"), ("宏大", "grand"), ("未知危机", "unknown threat"),
    ("荒芜", "desolate"), ("悲凉", "melancholic"), ("乱世苍茫", "vast war-torn wasteland"), ("文明垂危", "civilization on the brink"),
    ("刺痛", "piercing pain"), ("承重", "bearing weight"), ("隐忍", "enduring"), ("坚守", "perseverance"),
    ("恍然", "sudden realization"), ("沉重", "heavy"), ("认清宿命", "accepting destiny"), ("直面乱世", "confronting chaos"),
    ("苍凉", "bleak"), ("悲壮", "tragically grand"), ("蓄势待发", "charge poised"), ("希望不灭", "hope remains"),
]

CHARACTER_NAMES = [
    "林渊", "阿瑶", "林北望", "长老", "师兄", "守门弟子", "墨雾人",
    "林渊少年", "投影·林北望", "旁白",
]

SCENE_NAME_MAP = {
    "开篇序章": "开篇",
    "演武场": "守忆宗演武场",
    "山门": "守忆宗山门",
    "后山": "守忆宗后山密道",
    "山道": "守忆宗山道",
    "主殿": "守忆宗主殿",
    "密道": "守忆宗后山密道",
    "石室": "密道石室",
    "乱世": "商周乱世黄土地",
    "血月": "血月乱世",
}


# ---------- 工具函数 ----------

def _match_first(text: str, pairs: list[tuple[str, str]]) -> str:
    for cn, en in pairs:
        if cn in text:
            return en
    return ""


def _match_all(text: str, pairs: list[tuple[str, str]], limit: int = 4) -> list[str]:
    hits = []
    for cn, en in pairs:
        if cn in text and en not in hits:
            hits.append(en)
            if len(hits) >= limit:
                break
    return hits


def extract_duration(header: str) -> float:
    m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*s", header, re.IGNORECASE)
    if m:
        return float(m.group(2)) - float(m.group(1))
    m = re.search(r"｜\s*(\d+(?:\.\d+)?)\s*s", header, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return 5.0


def extract_shot_no(header: str) -> int:
    m = re.search(r"镜(\d+)", header)
    return int(m.group(1)) if m else 0


def generate_motion_prompt(
    description: str, shot_size: str, camera_movement: str,
    visual_notes: str, emotion_tone: str,
) -> str:
    size_en = _match_first(shot_size + description, SHOT_SIZE_MAP)
    cam_en = _match_first(camera_movement + description, CAMERA_MOVEMENT_MAP)
    visual_ens = _match_all(visual_notes + description, VISUAL_STYLE_MAP, limit=5)
    emotion_ens = _match_all(emotion_tone + description, EMOTION_MAP, limit=3)

    parts = []
    if size_en:
        parts.append(size_en)
    if cam_en:
        parts.append(cam_en)
    parts.append("cinematic frame")
    if visual_ens:
        parts.extend(visual_ens)
    if emotion_ens:
        parts.append(", ".join(emotion_ens))

    subjects: list[str] = []
    char_hits = [c for c in CHARACTER_NAMES if c in description]
    if char_hits:
        cn_to_en_char = {
            "林渊": "a young xianxia cultivator in grey robe",
            "阿瑶": "an 8-year-old girl with twin hair buns",
            "林北望": "an elder xianxia master in dark robes",
            "长老": "a temple elder",
            "师兄": "a wounded senior disciple",
            "墨雾人": "shadowy figures made of inky mist",
            "林渊少年": "a young xianxia cultivator",
            "投影·林北望": "a translucent ghostly projection of an elder",
            "守门弟子": "a gate guard disciple",
        }
        for c in char_hits:
            en = cn_to_en_char.get(c, c)
            if en not in subjects:
                subjects.append(en)

    action_hits = []
    if "黑屏" in description:
        action_hits.append("pitch black screen with deep rumbling ancient bell")
    if "钟响" in description:
        action_hits.append("ancient bronze bell resounding")
    if "字幕" in description and "淡入" in description:
        action_hits.append("white minimalist Chinese calligraphy text fading in and out")
    if "晨雾" in description or "山峦" in description or "林海" in description:
        action_hits.append("layered mountain peaks, emerald forest, flowing morning mist")
    if "石匾" in description or "篆字" in description:
        action_hits.append("ancient stone plaque with seal script characters")
    if "练剑" in description or "剑势" in description:
        action_hits.append("single figure practicing sword forms gracefully")
    if "侧脸" in description or "收剑" in description or "调息" in description:
        action_hits.append("side profile of young cultivator sheathing sword with composed breath")
    if "蹦跳" in description or "铜雀" in description:
        action_hits.append("young girl bounding in holding a three-legged bronze bird")
    if "铜雀" in description and ("特写" in shot_size or "特写" in description):
        action_hits.append("close-up of three-legged bronze bird with obsidian crystal eyes")
    if "捡" in description or "地面" in description:
        action_hits.append("hand reaching down to pick something from the ground")
    if "轰" in description or "爆炸" in description or "强光炸开" in description:
        action_hits.append("sudden massive explosion, pillars of smoke, ground shaking violently")
    if "龟裂" in description or "裂纹" in description:
        action_hits.append("stone ground cracking and spider-webbing, debris flying")
    if "护住" in description or "侧身" in description:
        action_hits.append("figure instantly turning to shield a child behind him")
    if "墨雾" in description or "黑影" in description:
        action_hits.append("shadowy figures of inky mist rushing through the temple gate")
    if "奔逃" in description or "全速奔逃" in description or "逃生" in description:
        action_hits.append("figure holding a child running for life down a mountain path")
    if "瞳孔涣散" in description or "倒地" in description:
        action_hits.append("fallen disciple, pupils dilated and empty, life force drained")
    if "手抓" in description or "抓住脚踝" in description:
        action_hits.append("wounded disciple reaching out to grab ankle with last strength")
    if "合上双眼" in description:
        action_hits.append("closing the eyes of the fallen with restrained tenderness")
    if "闪回" in description or "柔化" in description:
        action_hits.append("soft-focus flashback transition")
    if "滴血" in description or "血印" in description or "封印" in description:
        action_hits.append("elder's fingertip bleeding, sealing an ancient covenant with blood")
    if "宗谱" in description:
        action_hits.append("ancient clan registry hanging in the dark temple hall")
    if "门缝" in description and "雾气" in description:
        action_hits.append("inky mist seeping through a narrow door crack")
    if "拉开衣襟" in description or "胸口" in description:
        action_hits.append("master pulling open robes to reveal a black pulsating book embedded in his chest")
    if "巨手" in description or "巨力掀飞" in description or "殿顶" in description:
        action_hits.append("colossal mist-shaped hand crashing down from the shattered temple roof")
    if "钻" in description or "密道" in description:
        action_hits.append("two figures crawling into a narrow dark tunnel")
    if "发烫" in description or "掌心" in description:
        action_hits.append("three-legged bronze bird suddenly glowing hot in a palm")
    if "石台" in description or "凹槽" in description:
        action_hits.append("stone altar in a quiet stone chamber, groove perfectly matching the bronze bird base")
    if "蓝光" in description or "光芒爆发" in description:
        action_hits.append("bronze bird dropped into groove, blue ethereal light erupting, filling the entire chamber")
    if "虚影" in description or "投影" in description:
        action_hits.append("translucent ghostly projection of an elder appearing above the stone altar")
    if "消散" in description or "光芒褪去" in description:
        action_hits.append("projection slowly fading, chamber dimming to darkness")
    if "搏动" in description or "记忆簿" in description:
        action_hits.append("close-up of a black book pulsing under skin like a new heart")
    if "脚步声" in description or "逼近" in description:
        action_hits.append("sound of footsteps and clashing blades approaching from outside")
    if "护在身后" in description or "坚定" in description:
        action_hits.append("young figure firmly shielding a child behind him, eyes cold with resolve")
    if "按在胸口" in description or "灼热" in description or "泛红" in description:
        action_hits.append("hand pressing on chest, skin glowing red hot, heat spreading through body")
    if "刀耕火种" in description or "星河" in description or "闪掠" in description:
        action_hits.append("rapid montage flash cuts of 5000 years of Chinese civilization: farming, bronze vessels, battles, poetry — memories flooding like a river of stars")
    if "坠落" in description or "塌陷" in description or "失重" in description:
        action_hits.append("stone platform collapsing, two figures falling into abyss with zero-gravity motion")
    if "空间撕裂" in description or "帛画碎裂" in description:
        action_hits.append("surrounding space tearing like silk, a vast alien landscape emerging through the crack")
    if "黄土" in description or "乱世" in description or "甲骨文" in description:
        action_hits.append("vast yellow earth wasteland, battle smoke, floating oracle bone script cracking and dissolving")
    if "瞳孔" in description or "倒影" in description or "金色纹路" in description:
        action_hits.append("pupil reflecting the wasteland scene, golden runes glowing on burning skin")
    if "低语" in description or "商周" in description:
        action_hits.append("soft whisper of realization, eyes widening in shock and recognition")
    if "血月" in description or "定格" in description or "淡出" in description:
        action_hits.append("final wide shot: two figures on yellow earth wasteland, blood moon hanging in crimson sky, fading to black")

    body = ", ".join(action_hits) if action_hits else description[:60]

    full_parts = [size_en] if size_en else []
    full_parts.append(body)
    if cam_en:
        full_parts.append(cam_en)
    full_parts.append("cinematic")
    full_parts.extend(visual_ens)
    if emotion_ens:
        full_parts.append(", ".join(emotion_ens))
    full_parts.extend(["high detail", "24fps", "film grain"])

    return ", ".join(p for p in full_parts if p).strip()[:400]


# ---------- Markdown 解析 ----------

def parse_md(text: str) -> list[dict]:
    shots: list[dict] = []
    current_scene: str = ""

    chapter_re = re.compile(r"^##\s*【(.+?)】")
    shot_header_re = re.compile(r"\*\*镜(\d+)｜([^\*\*]+?)\*\*")

    current: dict | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        ch = chapter_re.match(line.strip())
        if ch:
            chapter_name = ch.group(1)
            for k, v in SCENE_NAME_MAP.items():
                if k in chapter_name:
                    current_scene = v
                    break
            else:
                current_scene = chapter_name.replace("（", "(").replace("）", ")")
            i += 1
            continue

        sh = shot_header_re.search(line.strip())
        if sh:
            if current:
                shots.append(current)
            header = sh.group(2).strip()
            shot_no = int(sh.group(1))
            m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*s", header, re.IGNORECASE)
            duration = float(m.group(2)) - float(m.group(1)) if m else 5.0
            m2 = re.search(r"｜\s*(.+)$", header)
            description = m2.group(1).strip() if m2 else ""

            current = {
                "shot_no": shot_no,
                "duration": duration,
                "description": description,
                "scene": current_scene,
                "dramatic_analysis": "",
                "visual_notes": "",
                "emotion_tone": "",
                "运镜理由_raw": "",
                "dialogues": [],
            }
            i += 1
            continue

        if current is not None:
            stripped = line.strip()
            label_re = re.compile(r"^\*\*(剧作目的|情感基调|视觉风格|运镜理由)\*\*[：:]\s*(.+)$")
            m = label_re.match(stripped)
            if m:
                label = m.group(1)
                value = m.group(2).strip()
                if label == "剧作目的":
                    current["dramatic_analysis"] = value
                elif label == "情感基调":
                    current["emotion_tone"] = value
                elif label == "视觉风格":
                    current["visual_notes"] = value
                elif label == "运镜理由":
                    current["运镜理由_raw"] = value
                i += 1
                continue

            if stripped.startswith("**镜") or stripped.startswith("##"):
                shots.append(current)
                current = None
                continue

            if stripped and not stripped.startswith(("#", "---", ">")):
                if current.get("dialogues") or ":" in stripped or "：" in stripped:
                    speaker_match = re.match(r"^([\u4e00-\u9fa5A-Za-z·]{1,8})[：:]\s*(.+)", stripped)
                    if speaker_match:
                        spk, txt = speaker_match.group(1), speaker_match.group(2)
                        emotion = "中性"
                        em = re.search(r"[\(（]([^）\)]{1,12})[\)）]", txt)
                        if em:
                            e_text = em.group(1)
                            from app.services.importers import _normalize_emotion
                            ne = _normalize_emotion(e_text)
                            if ne:
                                emotion = ne
                        current.setdefault("dialogues", []).append(
                            {"character": spk, "text": txt, "emotion": emotion}
                        )
                    else:
                        if "description" in current and stripped not in current["description"]:
                            current["description"] += " " + stripped

        i += 1

    if current:
        shots.append(current)

    for s in shots:
        s.pop("运镜理由_raw", None)

    return shots


def post_process_shots(shots: list[dict]) -> list[dict]:
    for s in shots:
        desc = s["description"]

        shot_size = ""
        for cn, _ in SHOT_SIZE_MAP:
            if cn in desc:
                shot_size = cn
                break
        if not shot_size:
            if s["shot_no"] <= 4:
                shot_size = "远景"
            elif any(k in desc for k in ("黑屏", "字幕")):
                shot_size = "全屏"

        camera_movement = ""
        reason_text = s.get("visual_notes", "") + s.get("description", "")
        for cn, _ in CAMERA_MOVEMENT_MAP:
            if cn in reason_text or cn in s.get("description", ""):
                camera_movement = cn
                break

        chars_in_shot = [c for c in CHARACTER_NAMES if c in desc]
        s["character_names"] = chars_in_shot
        s["shot_size"] = shot_size
        s["camera_movement"] = camera_movement

        s["motion_prompt"] = generate_motion_prompt(
            description=desc, shot_size=shot_size,
            camera_movement=camera_movement,
            visual_notes=s.get("visual_notes", ""),
            emotion_tone=s.get("emotion_tone", ""),
        )

        dlg_text = s.get("description", "")
        extra_dlg = _extract_dialogues_from_desc(dlg_text)
        if extra_dlg:
            existing_spk = {d["character"] for d in s.get("dialogues", [])}
            for d in extra_dlg:
                if d["character"] not in existing_spk:
                    s["dialogues"].append(d)

    return shots


def _extract_dialogues_from_desc(text: str) -> list[dict]:
    out = []
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z·]{1,8})[说轻声低语气音][：:]\s*([^。！？!?\n]{2,80}[。！？!?])", text):
        spk, txt = m.group(1), m.group(2)
        from app.services.importers import _normalize_emotion
        em = re.search(r"[\(（]([^）\)]{1,12})[\)）]", txt)
        emo = _normalize_emotion(em.group(1)) if em else "中性"
        out.append({"character": spk, "text": txt, "emotion": emo or "中性"})
    return out


# ---------- 数据库写入 ----------

ASSET_PROFILES = {
    "林渊": {
        "type": "character",
        "description": "少年守忆宗弟子，约16岁，身型挺拔修长，束发戴冠，灰蓝色长袍配宽腰带，腰间佩剑，面容清秀沉稳，眼神坚毅，古风水墨写实风格，东方仙侠气质",
        "extra": {"role": "男主", "voice": "青年男声，沉稳内敛"},
    },
    "阿瑶": {
        "type": "character",
        "description": "8岁小女孩，扎双丫髻，穿着淡青色短打襦裙，怀里常抱一只三脚铜雀，灵动活泼，古风水墨写实风格",
        "extra": {"role": "女主/师妹", "voice": "小女孩声，清脆明亮"},
    },
    "林北望": {
        "type": "character",
        "description": "守忆宗宗主，中年道士，须发半白，面容威严慈和，穿深灰色宗主长袍，胸口嵌着墨黑色万忆簿，古风水墨写实，庄重肃穆",
        "extra": {"role": "宗主", "voice": "中年男声，沉稳厚重"},
    },
    "长老": {
        "type": "character",
        "description": "守忆宗长老，年长修士，长须白眉，穿暗棕道袍，神情焦急绝望，古风水墨写实",
        "extra": {"role": "长老", "voice": "老年男声，沙哑低沉"},
    },
    "师兄": {
        "type": "character",
        "description": "守忆宗弟子，约20岁男性，重伤倒地，面色惨白，瞳孔涣散，伸手抓向镜头，古风水墨写实",
        "extra": {"role": "师兄", "voice": "青年男声，虚弱断续"},
    },
    "墨雾人": {
        "type": "character",
        "description": "反派，没有实体人形，由漆黑墨色雾气凝聚成的诡异飘忽形状，身体不断扭曲变幻，古风水墨写实风格，恐怖诡异",
        "extra": {"role": "反派", "voice": "无具体声音，诡异嗡鸣"},
    },
    "守忆宗演武场": {
        "type": "scene",
        "description": "清晨，青石铺就的开阔演武场，晨雾未散，远处鸟鸣，周围古木环绕，青灰色调，古风水墨写实风格",
    },
    "守忆宗山门": {
        "type": "scene",
        "description": "古朴山门，巨大石匾刻着篆字「守忆宗」，石纹苍劲，雾气流淌掠过石面，周围层叠山峦苍翠林海晨雾流动，古风水墨写实",
    },
    "守忆宗主殿": {
        "type": "scene",
        "description": "肃穆暗沉的宗门主殿，古宗法谱高悬殿中，巨柱排列，光影庄重厚重，古风水墨写实，神秘压抑",
    },
    "守忆宗山道": {
        "type": "scene",
        "description": "雾气弥漫的山林间曲折山道，两侧古木参天，古风水墨写实风格，幽暗压抑",
    },
    "守忆宗后山密道": {
        "type": "scene",
        "description": "后山深处的幽暗狭窄密道，石壁粗糙，光线微弱，古风水墨写实风格，密闭压抑",
    },
    "密道石室": {
        "type": "scene",
        "description": "密道尽头空旷古朴的石室，中央有方形石桌，石台凹槽形状特殊，无尘静谧，古风水墨写实，神秘神圣",
    },
    "商周乱世黄土地": {
        "type": "scene",
        "description": "苍茫贫瘠的黄土大地，遍地烽烟，远处战鼓轰鸣，号角呜咽，暗红色天空，甲骨文在空中漂浮碎裂消散，古风水墨写实，苍凉肃杀",
    },
    "三脚铜雀": {
        "type": "prop",
        "description": "一只古朴的三脚铜雀摆件，黄铜质感，雀目是墨色晶石，雀身刻有细密纹路，古风水墨写实，神秘有力量",
    },
    "万界记忆簿": {
        "type": "prop",
        "description": "巴掌大小的墨黑色册子，表面字符流动像活物，可以嵌入活人体内，古风水墨写实，神秘厚重",
    },
    "宗谱": {
        "type": "prop",
        "description": "挂在主殿的古朴宗谱卷轴，泛黄的纸页，黑色毛笔字，古风水墨写实",
    },
    "万忆簿": {
        "type": "prop",
        "description": "同万界记忆簿，墨黑册子，字符游走流动，嵌入人体胸口，古风水墨写实",
    },
}


def asset_name_for_scene(shot_scene: str, all_asset_names: set[str]) -> str | None:
    if shot_scene in all_asset_names:
        return shot_scene
    for k in SCENE_NAME_MAP.values():
        if k in all_asset_names and k in shot_scene:
            return k
    fuzzy = {"演武场": "守忆宗演武场", "山门": "守忆宗山门", "主殿": "守忆宗主殿",
             "山道": "守忆宗山道", "密道": "守忆宗后山密道", "石室": "密道石室",
             "乱世": "商周乱世黄土地"}
    for k, v in fuzzy.items():
        if k in shot_scene and v in all_asset_names:
            return v
    return None


def run_import():
    import sqlite3
    from pathlib import Path as P

    db_path = SQLITE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
        print(f"[x] Removed old DB: {db_path}")

    print(f"[+] Creating new DB at: {db_path}")

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app import models  # noqa: F401  — 必须先导入 models，Base.metadata 才会注册所有表
    from app.db import Base

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    session = Session()

    # --- 1. Project ---
    from app.models import Project, Asset, StoryboardShot, Dialogue, AssetStatus, ShotStatus
    project = Project(name="血月", style="国风仙侠写实电影感")
    session.add(project)
    session.flush()
    print(f"[+] Project created: id={project.id}, name=血月")

    # --- 2. Script ---
    from app.models import Script
    md_text = MD_PATH.read_text(encoding="utf-8")
    script = Script(project_id=project.id, chapter=1, title="第一集：宿命开篇", content=md_text[:2000])
    session.add(script)
    session.flush()
    print(f"[+] Script created: id={script.id}, chapter=1")

    # --- 3. Assets ---
    created_assets: dict[str, Asset] = {}
    for name, cfg in ASSET_PROFILES.items():
        a = Asset(
            project_id=project.id, type=cfg["type"], name=name,
            description=cfg["description"],
            extra=cfg.get("extra", {}),
            status=AssetStatus.pending,
        )
        session.add(a)
        session.flush()
        created_assets[name] = a
        print(f"  asset id={a.id} [{cfg['type']}] {name}")

    # --- 4. Parse MD ---
    print(f"\n[+] Parsing Markdown: {MD_PATH}")
    raw_shots = parse_md(md_text)
    shots = post_process_shots(raw_shots)
    print(f"[+] Parsed {len(shots)} shots")

    # --- 5. StoryboardShots ---
    char_asset_name_to_id = {n: a.id for n, a in created_assets.items() if a.type == "character"}
    scene_asset_names = {a.name for a in created_assets.values() if a.type == "scene"}

    for s in shots:
        name_ids = []
        for cn in s.get("character_names", []):
            aid = char_asset_name_to_id.get(cn)
            if aid is not None and aid not in name_ids:
                name_ids.append(aid)

        scene_asset_name = asset_name_for_scene(s.get("scene", ""), scene_asset_names)
        scene_id = created_assets[scene_asset_name].id if scene_asset_name else None

        shot = StoryboardShot(
            script_id=script.id,
            shot_no=s["shot_no"],
            scene=s.get("scene", "") or "",
            description=s["description"],
            motion_prompt=s.get("motion_prompt", ""),
            duration=min(max(s["duration"], 3.0), 8.0),
            camera_movement=s.get("camera_movement", "") or "",
            shot_size=s.get("shot_size", "") or "",
            dramatic_analysis=s.get("dramatic_analysis", "") or "",
            visual_notes=s.get("visual_notes", "") or "",
            emotion_tone=s.get("emotion_tone", "") or "",
            status=ShotStatus.pending,
            character_ids=name_ids,
            scene_id=scene_id,
        )
        session.add(shot)
        session.flush()

        for d in s.get("dialogues", []):
            dlg_char_id = None
            speaker_name = d.get("character", "")
            if speaker_name in char_asset_name_to_id:
                dlg_char_id = char_asset_name_to_id[speaker_name]
            Dialogue(
                shot_id=shot.id,
                character_id=dlg_char_id,
                speaker_name=speaker_name,
                text=d.get("text", ""),
                emotion=d.get("emotion", "中性"),
                voice_id="default",
            )
            session.add(Dialogue(
                shot_id=shot.id,
                character_id=dlg_char_id,
                speaker_name=speaker_name,
                text=d.get("text", ""),
                emotion=d.get("emotion", "中性"),
                voice_id="default",
            ))

    session.commit()
    session.close()
    print(f"\n[✓] Done! Imported {len(shots)} shots into {db_path}")

    # --- 6. Summary ---
    chars = sum(1 for v in ASSET_PROFILES.values() if v["type"] == "character")
    scenes = sum(1 for v in ASSET_PROFILES.values() if v["type"] == "scene")
    props = sum(1 for v in ASSET_PROFILES.values() if v["type"] == "prop")

    session2 = Session()
    dlg_count = session2.query(Dialogue).count()
    shot_rows = session2.query(StoryboardShot).all()
    session2.close()

    print(f"\n=== 导入汇总 ===")
    print(f"  项目: 血月 (id=1)")
    print(f"  剧本: 第一集 (id=1)")
    print(f"  分镜: {len(shots)} 个镜头")
    print(f"  素材: {chars}角色 / {scenes}场景 / {props}道具")
    print(f"  台词: {dlg_count} 条")
    print(f"\n=== 每个镜头的 motion_prompt 预览（前3个）===")
    for s in shots[:3]:
        print(f"  镜{s['shot_no']}: {s.get('motion_prompt', '')[:120]}")

    print(f"\n=== 还缺什么（需要你后续手动生成）===")
    print(f"  1. [必] LLM_API_KEY — 后端 .env 里需要填真实的 key")
    print(f"  2. [必] ComfyUI 服务 — 启动后填 .env 的 COMFYUI_BASE_URL")
    print(f"  3. [必] 锁定标准照 — 素材表每个角色/场景/道具需要先生成标准照")
    print(f"  4. [选] Redis + Celery — 异步任务队列（可本地启动: pip install redis）")
    print(f"  5. [选] TTS 服务 — 配音生成需要 TTS_BASE_URL")
    print(f"  6. [选] 补充 motion_prompt — 可在前端分镜表手动优化英文提示词")


class DialogCounter:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


if __name__ == "__main__":
    run_import()