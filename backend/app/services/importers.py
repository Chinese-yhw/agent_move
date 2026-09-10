"""文本导入解析器：分镜表 txt / 素材清单 txt / CSV 提示词表。

支持两种分镜表格式：
1. DeepSeek/Excel 复制：Tab 分隔（或 2+ 空格），含表头
2. Markdown 表格：| 镜号 | 景别 | 时长 | … |，含 |:---| 分隔行

支持两种素材清单格式：
1. 章节式：「角色 / 物品 / 场景」大节 + 主体/变体/音色字段
2. 标准照提示词式：【名字·标准照】+ 提示词段落；
   文件前部可带【镜号N】元素清单块，用于自动关联镜头↔素材

支持 CSV 格式：
- 2.csv 格式：镜号, 正面 Prompt, 负面 Prompt （48 镜头各带精准正负 prompt）
"""
from __future__ import annotations

import csv
import io
import re


# ---------- 分镜表 ----------
def _split_table_rows(lines: list[str]) -> list[list[str]]:
    """把每行切成单元格：Markdown 表格(|) > Tab > 2+ 空格。跳过 Markdown 分隔行。"""
    rows: list[list[str]] = []
    for l in lines:
        if "|" in l:
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            # |:---|:--:| 之类的分隔行
            if cells and all(re.fullmatch(r":?-+:?", c.replace(" ", "")) for c in cells if c):
                continue
            rows.append(cells)
        elif "\t" in l:
            rows.append(l.split("\t"))
        else:
            rows.append(re.split(r"\s{2,}", l))
    return rows


def _find_col(col_map: dict[str, int], *names: str) -> int | None:
    """表头模糊匹配：先精确，再前缀匹配（如「画面描述（含角色外貌…）」匹配「画面描述」）。"""
    for n in names:
        for k, idx in col_map.items():
            kn = k.replace(" ", "").replace("　", "")
            if kn == n or kn.startswith(n):
                return idx
    return None


def _normalize_emotion(raw: str) -> str:
    """归一化情绪词到 CosyVoice 支持的有限集合。
    CosyVoice 常见 emotion 枚举：中性/平静、悲伤/伤心、高兴/开心、愤怒/生气、
    惊讶/震惊、低语/低沉、激动、恐惧/害怕、紧张。
    未识别的情绪词回落到空串（调用方据此判断非情绪）。
    """
    if not raw:
        return ""
    e = raw.strip().strip("（）()【】[]").strip()
    EMOTION_MAP = {
        # 中性/平静
        "中性": "中性", "平静": "中性", "正常": "中性", "默认": "中性", "普通": "中性", "neutral": "中性",
        # 高兴
        "高兴": "高兴", "开心": "高兴", "喜悦": "高兴", "快乐": "高兴", "欣喜": "高兴", "笑": "高兴",
        "欢笑": "高兴", "兴奋": "高兴", "happy": "高兴", "joy": "高兴",
        # 悲伤
        "悲伤": "悲伤", "伤心": "悲伤", "难过": "悲伤", "哀伤": "悲伤", "低落": "悲伤", "悲恸": "悲伤",
        "凄凉": "悲伤", "sad": "悲伤",
        # 愤怒
        "愤怒": "愤怒", "生气": "愤怒", "怒火": "愤怒", "气恼": "愤怒", "暴怒": "愤怒", "angry": "愤怒",
        # 惊讶
        "惊讶": "惊讶", "震惊": "惊讶", "意外": "惊讶", "诧异": "惊讶", "惊奇": "惊讶", "surprised": "惊讶",
        # 恐惧
        "恐惧": "恐惧", "害怕": "恐惧", "惊恐": "恐惧", "畏缩": "恐惧", "惊慌": "恐惧", "fear": "恐惧",
        # 低语
        "低语": "低语", "低沉": "低语", "低声": "低语", "轻声": "低语", "呢喃": "低语", "whisper": "低语",
        "压低声音": "低语", "低嗓": "低语", "小声": "低语",
        # 激动
        "激动": "激动", "急切": "激动", "高昂": "激动", "激昂": "激动", "excited": "激动", "焦急": "激动",
        # 紧张
        "紧张": "紧张", "焦虑": "紧张", "不安": "紧张", "nervous": "紧张",
    }
    return EMOTION_MAP.get(e, EMOTION_MAP.get(e.lower(), ""))


def _parse_dialogues(cell: str) -> list[dict]:
    """台词单元格拆成多条：支持「林渊：… 阿瑶：…」多角色，及「字幕：…」旁白。
    情绪标注格式：林渊：（紧张）师父人呢？ 或 林渊：师父人呢？（紧张）
    台词中段括号如「（压低声音）」会作为情绪提示尝试归一化，但保留原文不删除。
    未标注情绪时默认中性。
    """
    cell = (cell or "").strip()
    if not cell or cell in ("无", "—", "-") or "无台词" in cell:
        return []
    matches = list(re.finditer(r"([一-龥A-Za-z·]{2,8})：", cell))
    if not matches:
        return [{"character": "", "text": cell, "emotion": "中性"}]
    out: list[dict] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cell)
        text = cell[m.end():end].strip().strip("；; \t")
        if not text:
            continue
        emotion = "中性"
        # 开头格式：林渊：（紧张）师父人呢？
        m_open = re.match(r"^[\(（]([^）\)]{1,12})[\)）]\s*(.*)", text, re.DOTALL)
        if m_open:
            normalized = _normalize_emotion(m_open.group(1))
            if normalized:  # 识别为情绪，删除括号、设情绪
                emotion = normalized
                text = m_open.group(2).strip()
            # 否则是动作提示（如"将阿瑶推到身后"），保留原文不动
        else:
            # 结尾格式：林渊：师父人呢？（紧张）
            m_close = re.search(r"[\(（]([^）\)]{1,12})[\)）][\s！？。；]*$", text)
            if m_close:
                normalized = _normalize_emotion(m_close.group(1))
                if normalized:
                    emotion = normalized
                    text = text[:m_close.start()].strip()
        # 台词中段含「（压低声音）」「（轻声）」等表演提示：尝试归一化为情绪，但保留原文
        if emotion == "中性":
            for m_hint in re.finditer(r"[\(（]([^）\)]{1,12})[\)）]", text):
                normalized = _normalize_emotion(m_hint.group(1))
                if normalized:
                    emotion = normalized
                    break
        out.append({"character": m.group(1), "text": text, "emotion": emotion})
    return out


def parse_storyboard_table(text: str) -> list[dict]:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    rows = _split_table_rows(lines)
    if all(len(r) <= 1 for r in rows):
        # 纯单列（无分隔符）时按 2+ 空格再试一次
        rows = [re.split(r"\s{2,}", l) for l in lines]

    header_idx = next((i for i, r in enumerate(rows)
                       if any("镜" in c and "号" in c for c in r)), -1)
    col_map: dict[str, int] = {}
    if header_idx >= 0:
        for i, h in enumerate(rows[header_idx]):
            col_map[h.strip().replace(" ", "")] = i
        data_rows = rows[header_idx + 1:]
    else:
        col_map = {"镜号": 0, "景别": 1, "时长": 2, "画面描述": 3,
                   "台词/内心独白": 4, "运镜/音效提示": 5}
        data_rows = rows

    def pick(cols: list[str], *names: str) -> str:
        idx = _find_col(col_map, *names)
        if idx is not None and idx < len(cols):
            return cols[idx].strip()
        return ""

    shots: list[dict] = []
    for i, cols in enumerate(data_rows):
        first = cols[0].strip() if cols else ""
        # 行合并：不以数字开头且上一行存在 → 视为上一行的续行
        if shots and not re.match(r"^\d+", first) and len(cols) < 3:
            # 若续行是「角色：…」格式，合并到台词单元格（多角色对白）；否则合并到画面描述
            if re.match(r"^[一-龥A-Za-z·]{2,8}：", first):
                shots[-1]["dialogues"] = _parse_dialogues(
                    (shots[-1].get("dialogues_text_cache") or "") + "\n" + first
                )
                shots[-1]["dialogues_text_cache"] = (
                    (shots[-1].get("dialogues_text_cache") or "") + "\n" + first
                )
            else:
                shots[-1]["description"] += "\n" + first
            continue
        no_raw = pick(cols, "镜号") or str(i + 1)
        dur_raw = re.sub(r"[sS秒]", "", pick(cols, "时长", "时长(s)", "时长（秒）"))
        try:
            duration = float(dur_raw)
        except ValueError:
            duration = 5.0
        duration = min(max(duration, 3.0), 8.0)
        dialogue_text = pick(cols, "台词/内心独白", "台词", "内心独白", "台词/独白")
        camera = pick(cols, "运镜/音效提示", "运镜", "运镜/音效")
        cam_part = ""
        sound_part = ""
        for seg in re.split(r"[\n；;]", camera):
            if seg.startswith("运镜"):
                cam_part = seg.split("：", 1)[-1].strip()
            elif seg.startswith("音效"):
                sound_part = seg.strip()
        desc = pick(cols, "画面描述", "描述")
        if sound_part:
            desc = f"{desc}\n（{sound_part}）"
        shot = {
            "shot_no": int(re.match(r"^\d+", no_raw).group()) if re.match(r"^\d+", no_raw) else i + 1,
            "scene": pick(cols, "场景", "场景名"),
            "description": desc,
            "motion_prompt": "",
            "duration": duration,
            "camera_movement": cam_part,
            "shot_size": pick(cols, "景别"),
            "character_names": [],
            "dialogues": _parse_dialogues(dialogue_text),
            "dialogues_text_cache": dialogue_text,  # 供后续续行合并用
        }
        if shot["description"] or shot["dialogues"]:
            shots.append(shot)
    # 清理临时字段
    for s in shots:
        s.pop("dialogues_text_cache", None)
    return shots


# ---------- 素材清单（章节式） ----------
_SECTION_MAP = {"角色": "character", "物品": "prop", "道具": "prop", "场景": "scene"}
_META_KEYS = ("类型", "性别", "主体来源", "分类", "场景类型", "物品类别",
              "主体", "变体", "output_id", "音色描述")
_FIELD_RE = re.compile(r"^(类型|性别|主体来源|分类|场景类型|物品类别|主体|变体|output_id|音色描述)[：:]\s*(.*)$")


def parse_asset_list(text: str) -> list[dict]:
    """返回 [{type,name,description,variants:[{name,description}],voice,role}]"""
    assets: list[dict] = []
    section = None          # 当前大节 character/scene/prop
    current: dict | None = None
    last_variant_key = "description"   # 主体 or 某个变体，供 output_id 归属

    def flush():
        nonlocal current
        if current and current.get("name") and current.get("description"):
            assets.append(current)
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 大节标题（独占一行）
        if line in _SECTION_MAP:
            flush()
            section = _SECTION_MAP[line]
            continue
        if line.endswith("素材清单") or section is None:
            continue
        # 条目标题：短行且不含字段冒号；排除元数据行
        m = _FIELD_RE.match(line)
        is_meta = bool(m) or re.match(r"^(物品类别|场景类型)[：:]", line)
        if not m and not is_meta and len(line) <= 24 and not re.match(r"^[\d一二三四五六七八九十]+[、.]", line):
            flush()
            current = {"type": section, "name": line, "description": "",
                       "variants": [], "voice": "", "role": ""}
            last_variant_key = "description"
            continue
        if m and current is not None:
            key, val = m.group(1), m.group(2).strip()
            if key == "主体":
                current["description"] = val
                last_variant_key = "description"
            elif key == "变体":
                vname, _, vdesc = val.partition("：")
                current["variants"].append({"name": vname.strip(), "description": vdesc.strip() or val})
                last_variant_key = "variant"
            elif key in ("output_id", "主体来源"):
                pass  # 占位标记，忽略
            elif key == "音色描述":
                current["voice"] = val
            elif key in ("类型", "场景类型", "物品类别"):
                current["role"] = (current["role"] + " / " + val).strip(" /") if current["role"] else val
            elif key == "性别":
                current.setdefault("extra", {})["gender"] = val
            elif key == "分类":
                current.setdefault("extra", {})["category"] = val
        elif m and current is None:
            continue
    flush()
    return assets


# ---------- 素材清单（标准照提示词式 + 镜号对应） ----------
_STD_PHOTO_RE = re.compile(r"^【(.+?)[·・]标准照】\s*$")
_SHOT_BLOCK_RE = re.compile(r"^【镜号\s*(\d+)\s*】\s*$")


def _classify_asset_type(name: str, prompt: str) -> str:
    """按提示词特征判断素材类型：定妆照→角色；概念图/全景→场景；道具/至宝/特写→道具。"""
    if "定妆照" in prompt:
        return "character"
    if "概念图" in prompt or "全景" in prompt:
        return "scene"
    if "道具" in prompt or "至宝" in prompt or "特写" in prompt:
        return "prop"
    if re.search(r"[宗场境殿城山]", name):
        return "scene"
    return "prop"


def parse_std_photo_list(text: str) -> dict | None:
    """解析「【镜号N】元素清单 + 【名字·标准照】提示词」格式。

    返回 {"assets": [{type,name,description,variants:[],voice,role}],
          "shot_refs": {镜号: [元素描述行...]}}；
    若文件中不含任何「【名·标准照】」块则返回 None（交给旧解析器）。
    """
    if not re.search(r"【.+?[·・]标准照】", text):
        return None

    assets: list[dict] = []
    shot_refs: dict[int, list[str]] = {}
    cur_shot: int | None = None
    cur_asset: dict | None = None
    prompt_lines: list[str] = []

    def flush_asset():
        nonlocal cur_asset, prompt_lines
        if cur_asset is not None:
            prompt = "\n".join(prompt_lines).strip()
            cur_asset["description"] = prompt
            cur_asset["type"] = _classify_asset_type(cur_asset["name"], prompt)
            assets.append(cur_asset)
        cur_asset = None
        prompt_lines = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m_shot = _SHOT_BLOCK_RE.match(line)
        if m_shot:
            flush_asset()
            cur_shot = int(m_shot.group(1))
            shot_refs.setdefault(cur_shot, [])
            continue
        m_std = _STD_PHOTO_RE.match(line)
        if m_std:
            flush_asset()
            cur_shot = None  # 标准照区不再属于任何镜号块
            cur_asset = {"type": "prop", "name": m_std.group(1).strip(),
                         "description": "", "variants": [], "voice": "", "role": ""}
            continue
        # 分隔线（====、----）与章节标题（三、…）：结束当前块
        if re.fullmatch(r"[=—\-]{3,}", line) or re.match(r"^[一二三四五六七八九十]+、", line):
            flush_asset()
            cur_shot = None
            continue
        if cur_asset is not None:
            prompt_lines.append(line)
            continue
        if cur_shot is not None:
            item = line.lstrip("-·•* ").strip()
            if item:
                shot_refs[cur_shot].append(item)
    flush_asset()
    return {"assets": assets, "shot_refs": shot_refs}


# ---------- 镜头↔素材关联（供素材上传后自动绑定） ----------
def cjk_bigrams(s: str) -> set[str]:
    """提取中文连续二元组，用于场景描述与镜头元素的模糊匹配。"""
    s = re.sub(r"[^一-龥]", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ---------- 段落式分镜拆解 MD 解析（如《血月》逐镜头分镜拆解＋剧作四要素全案） ----------

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

EMOTION_EN_MAP = [
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
    ("紧迫", "urgent"), ("奔逃", "frantic escape"), ("生死一线", "life-or-death stakes"),
    ("悲凉", "heartbreaking"), ("不忍直视", "harrowing"),
    ("悲壮", "tragically heroic"), ("急切", "desperate urgency"), ("托付", "solemn entrustment"),
    ("悲怆", "agonizing grief"), ("无力", "powerless"), ("决绝", "resolute"),
    ("沉痛", "heavy grief"), ("漠然", "numbed"),
    ("隐忍", "restrained grief"), ("坚定", "determined"), ("负重前行", "shouldering the burden"),
    ("回溯", "nostalgic flashback"), ("宿命悲凉", "fateful melancholy"),
    ("舍身", "self-sacrificial"),
    ("压抑", "oppressive"), ("末日降临", "apocalyptic dread"),
    ("绝望", "desperate"), ("慌张", "panicked"),
    ("释然", "at peace"), ("悲悯", "compassionate"), ("大爱无声", "quiet compassion"),
    ("忧虑", "anxious"), ("沉重", "heavy with burden"), ("悬而未决", "unresolved tension"),
    ("神圣", "sacred"), ("神秘", "mysterious"), ("宿命厚重", "fateful gravity"),
    ("末日", "apocalyptic"), ("碾压", "overwhelming"), ("绝望顶点", "peak despair"),
    ("幽暗", "dark"), ("局促", "cramped"), ("暂时喘息", "brief respite"), ("暗流涌动", "undercurrent of tension"),
    ("温热", "warm"), ("宿命启动", "destiny unfolding"),
    ("安静", "quiet"), ("宿命降临", "destiny arrives"),
    ("震撼", "awe-inspiring"), ("庄严", "solemn"),
    ("温柔", "gentle"), ("厚重", "heavy with gravity"), ("嘱托", "solemn charge"),
    ("遗憾", "lingering regret"), ("寄予厚望", "expectant hope"),
    ("空落", "hollow"), ("沉静", "quiet and still"), ("新旧交替", "transition"),
    ("承重", "burdened"), ("宿命附体", "destiny embodied"),
    ("灼痛", "searing pain"), ("极致消耗", "extreme cost"),
    ("恢弘", "epic"), ("沧桑", "weathered"), ("文明厚重", "weight of civilization"),
    ("失重", "disorienting"), ("恍惚", "dazed"), ("颠覆", "overturned"),
    ("苍凉", "bleak"), ("陌生", "alien"), ("宏大", "grand"), ("未知危机", "unknown threat"),
    ("荒芜", "desolate"), ("乱世苍茫", "vast war-torn wasteland"), ("文明垂危", "civilization on the brink"),
    ("刺痛", "piercing pain"), ("隐忍", "enduring"), ("坚守", "perseverance"),
    ("恍然", "sudden realization"), ("认清宿命", "accepting destiny"), ("直面乱世", "confronting chaos"),
    ("悲壮", "tragically grand"), ("蓄势待发", "charge poised"), ("希望不灭", "hope remains"),
]

DEFAULT_CHARACTER_NAMES: list[str] = []

SCENE_NAME_MAP: dict[str, str] = {}


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


def generate_motion_prompt(
    description: str, shot_size: str = "", camera_movement: str = "",
    visual_notes: str = "", emotion_tone: str = "",
    character_names: list[str] | None = None,
) -> str:
    size_en = _match_first(shot_size + description, SHOT_SIZE_MAP)
    cam_en = _match_first(camera_movement + description, CAMERA_MOVEMENT_MAP)
    visual_ens = _match_all(visual_notes + description, VISUAL_STYLE_MAP, limit=5)
    emotion_ens = _match_all(emotion_tone + description, EMOTION_EN_MAP, limit=3)

    parts: list[str] = []
    if size_en:
        parts.append(size_en)
    if cam_en:
        parts.append(cam_en)
    parts.append("cinematic frame")
    if visual_ens:
        parts.extend(visual_ens)
    if emotion_ens:
        parts.append(", ".join(emotion_ens))

    char_list = character_names or DEFAULT_CHARACTER_NAMES
    for c in char_list:
        if c in description:
            parts.append(c)

    return ", ".join(p for p in parts if p).strip()[:400]


def _extract_dialogues_from_desc(text: str) -> list[dict]:
    out = []
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z·]{1,8})[说轻声低语气音][：:]\s*([^。！？!?\n]{2,80}[。！？!?])", text):
        spk, txt = m.group(1), m.group(2)
        em = re.search(r"[\(（]([^）\)]{1,12})[\)）]", txt)
        emo = _normalize_emotion(em.group(1)) if em else "中性"
        out.append({"character": spk, "text": txt, "emotion": emo or "中性"})
    return out


def parse_storyboard_md(text: str, known_characters: list[str] | None = None) -> list[dict]:
    """解析段落式 Markdown 分镜拆解，如《血月》逐镜头分镜拆解＋剧作四要素全案。

    支持的分镜头格式：
      **镜1｜0-5s 开篇：黑屏**
      镜1｜开篇：黑屏
      ## 镜1 开篇
    支持的字段：**剧作目的** / **情感基调** / **视觉风格** / **运镜理由**
    """
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

            if stripped and not stripped.startswith(("#", "---", ">")):
                if current.get("dialogues") or ":" in stripped or "：" in stripped:
                    speaker_match = re.match(r"^([\u4e00-\u9fa5A-Za-z·]{1,8})[：:]\s*(.+)", stripped)
                    if speaker_match:
                        spk, txt = speaker_match.group(1), speaker_match.group(2)
                        emotion = "中性"
                        em = re.search(r"[\(（]([^）\)]{1,12})[\)）]", txt)
                        if em:
                            ne = _normalize_emotion(em.group(1))
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

    char_names = known_characters or DEFAULT_CHARACTER_NAMES
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

        chars_in_shot = [c for c in char_names if c in desc]
        s["character_names"] = chars_in_shot
        s["shot_size"] = shot_size
        s["camera_movement"] = camera_movement
        s["motion_prompt"] = generate_motion_prompt(
            description=desc, shot_size=shot_size,
            camera_movement=camera_movement,
            visual_notes=s.get("visual_notes", ""),
            emotion_tone=s.get("emotion_tone", ""),
            character_names=char_names,
        )

        extra_dlg = _extract_dialogues_from_desc(desc)
        if extra_dlg:
            existing_spk = {d["character"] for d in s.get("dialogues", [])}
            for d in extra_dlg:
                if d["character"] not in existing_spk:
                    s.setdefault("dialogues", []).append(d)

    result: list[dict] = []
    for s in shots:
        result.append({
            "shot_no": s["shot_no"],
            "scene": s.get("scene", ""),
            "description": s["description"],
            "motion_prompt": s.get("motion_prompt", ""),
            "duration": s["duration"],
            "camera_movement": s.get("camera_movement", ""),
            "shot_size": s.get("shot_size", ""),
            "character_names": s.get("character_names", []),
            "dialogues": s.get("dialogues", []),
        })
    return result


def looks_like_md_paragraph(text: str) -> bool:
    """判断文本是否为段落式分镜拆解（区别于表格格式）。"""
    sample = text[:2000]
    if re.search(r"\*\*镜\d+｜", sample):
        return True
    if re.search(r"^##\s*【", sample, re.MULTILINE):
        return True
    if re.search(r"\*\*剧作目的\*\*", sample):
        return True
    if re.search(r"\*\*运镜理由\*\*", sample):
        return True
    return False


# ---------- 镜头↔素材关联（供素材上传后自动绑定） ----------
def cjk_bigrams(s: str) -> set[str]:
    """提取中文连续二元组，用于场景描述与镜头元素的模糊匹配。"""
    s = re.sub(r"[^一-龥]", "", s or "")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def link_shots_by_refs(shots: list, project_assets: list, shot_refs: dict[int, list[str]],
                       scene_threshold: int = 3) -> int:
    """按【镜号N】元素清单把素材绑定到镜头（原地修改 shot 对象）。

    - 角色：素材名出现在该镜元素文本中 → character_ids
    - 场景：素材名+描述与元素文本的中文二元组重叠分最高且达阈值 → scene_id
    返回成功绑定（角色或场景任一）的镜头数。
    """
    linked = 0
    for shot in shots:
        refs = shot_refs.get(shot.shot_no)
        if not refs:
            continue
        blob = "\n".join(refs)
        char_ids = [a.id for a in project_assets
                    if a.type == "character" and a.name and a.name in blob]
        best_scene, best_score = None, 0
        blob_grams = cjk_bigrams(blob)
        for a in project_assets:
            if a.type != "scene":
                continue
            score = len(cjk_bigrams(a.name + (a.description or "")) & blob_grams)
            if score > best_score:
                best_score, best_scene = score, a.id
        changed = False
        if char_ids:
            shot.character_ids = char_ids
            changed = True
        if best_scene and best_score >= scene_threshold:
            shot.scene_id = best_scene
            changed = True
        if changed:
            linked += 1
    return linked


# ---------- CSV 分镜提示词导入（2.csv / 1.csv 格式） ----------

def parse_csv_shots(text: str) -> list[dict]:
    """解析 CSV 提示词表（镜号, 正面 Prompt, 负面 Prompt / 画面目标, 文生图 Prompt）。

    兼容两种列布局：
    - 2.csv：镜号, 正面 Prompt, 负面 Prompt
    - 1.csv：镜号, 画面目标, 文生图 Prompt, 比例
    """
    shots: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return []

    for row in reader:
        raw_no = (row.get("镜号") or "").strip()
        m = re.match(r"^\d+", raw_no)
        if not m:
            continue
        shot_no = int(m.group())

        pos_prompt = (row.get("正面 Prompt") or row.get("文生图 Prompt") or "").strip()
        neg_prompt = (row.get("负面 Prompt") or "").strip()
        target = (row.get("画面目标") or "").strip()

        desc = pos_prompt or target
        shots.append({
            "shot_no": shot_no,
            "description": target or desc,
            "image_prompt": pos_prompt,
            "negative_prompt": neg_prompt,
            "motion_prompt": "",
            "duration": 5.0,
            "camera_movement": "",
            "shot_size": "",
            "scene": "",
            "character_names": [],
            "dialogues": [],
        })

    shots.sort(key=lambda s: s["shot_no"])
    return shots


def looks_like_csv_prompts(text: str) -> bool:
    """判断文本是否为 CSV 提示词表（区别于分镜表 md/txt）。"""
    sample = text[:300]
    if re.search(r"镜号[,\t].*正面.*Prompt", sample):
        return True
    if re.search(r"镜号[,\t].*负面.*Prompt", sample):
        return True
    if re.search(r"镜号[,\t].*文生图.*Prompt", sample):
        return True
    if re.search(r"^镜号[,，]\s*正面\s*Prompt", sample, re.MULTILINE):
        return True
    return False


# ---------- 从镜头 prompt 中提取角色/场景素材 ----------

_DEFAULT_CHAR_NAMES = ["林渊", "阿瑶", "林北望", "长老", "师兄", "墨雾人"]

# 场景定义：name=素材名, keywords=匹配关键词组（任一命中即归为该场景）
_DEFAULT_SCENE_DEFS = [
    {"name": "守忆宗山峦全景", "keywords": ["苍翠山峦", "层叠林海", "宗门依山而建"]},
    {"name": "守忆宗山门", "keywords": ["山门", "石匾"]},
    {"name": "守忆宗演武场", "keywords": ["演武场", "青石演武"]},
    {"name": "守忆宗主殿", "keywords": ["主殿", "宗谱高悬", "梁柱厚重"]},
    {"name": "守忆宗山道", "keywords": ["山道", "青石山路"]},
    {"name": "守忆宗后山密道", "keywords": ["密道", "石洞狭窄"]},
    {"name": "传承石室", "keywords": ["石室", "石台", "凹槽"]},
    {"name": "商周乱世黄土地", "keywords": ["黄土地", "苍茫黄土", "灰黄", "烽烟", "战旗"]},
]

_DEFAULT_PROP_NAMES = ["三脚铜雀", "万界记忆簿", "宗谱"]


def extract_assets_from_shots(
    shots: list[dict],
    char_names: list[str] | None = None,
    scene_defs: list[dict] | None = None,
    prop_names: list[str] | None = None,
) -> list[dict]:
    """从一组 shot 的 image_prompt 里提取角色/场景/道具描述摘要，简化为素材清单。

    策略：
    - 角色：取该角色首次出现时的 image_prompt 片段（含外貌/服装关键词）
    - 场景：按关键词组匹配，取首次出现镜头的 prompt 作为环境描写
    - 道具：取首次出现时最相关的描述
    """
    chars = char_names or _DEFAULT_CHAR_NAMES
    scenes = scene_defs or _DEFAULT_SCENE_DEFS
    props = prop_names or _DEFAULT_PROP_NAMES

    char_desc: dict[str, str] = {}
    scene_desc: dict[str, str] = {}
    prop_desc: dict[str, str] = {}

    for shot in shots:
        ip = shot.get("image_prompt") or ""
        desc = shot.get("description") or ip
        blob = ip or desc

        for c in chars:
            if c in blob and c not in char_desc:
                snippet = _extract_character_snippet(c, ip)
                if snippet:
                    char_desc[c] = snippet

        # --- 场景：关键词组匹配 ---
        for sdef in scenes:
            sname = sdef["name"]
            if sname in scene_desc:
                continue
            kws = sdef["keywords"]
            if any(kw in blob for kw in kws):
                snippet = _extract_scene_snippet_v2(ip, kws)
                if snippet:
                    scene_desc[sname] = snippet

        for p in props:
            if p in blob and p not in prop_desc:
                snippet = _extract_prop_snippet(p, ip)
                if snippet:
                    prop_desc[p] = snippet

    assets: list[dict] = []
    for name in chars:
        if name in char_desc:
            assets.append({"type": "character", "name": name, "description": char_desc[name]})
    for sdef in scenes:
        sname = sdef["name"]
        if sname in scene_desc:
            assets.append({"type": "scene", "name": sname, "description": scene_desc[sname]})
    for name in props:
        if name in prop_desc:
            assets.append({"type": "prop", "name": name, "description": prop_desc[name]})

    return assets


def _extract_character_snippet(char_name: str, prompt: str) -> str:
    """从含角色名的 prompt 中提取角色外貌/服装描述片段。"""
    idx = prompt.find(char_name)
    if idx < 0:
        return ""
    start = max(0, idx - 15)
    end = min(len(prompt), idx + len(char_name) + 100)
    segment = prompt[start:end]
    segment = re.sub(r"[，,]", "，", segment)
    keywords = ["岁", "岁少年", "男孩", "女孩", "少年", "中年", "老者", "老人",
                "黑发", "白发", "须发", "面容", "眉眼", "神情", "表情",
                "长袍", "道袍", "襦裙", "童装", "古装", "服装", "束发", "戴冠",
                "腰间", "佩剑", "怀里", "抱着"]
    has_keyword = any(k in segment for k in keywords)
    if has_keyword and len(segment) >= 15:
        segment = segment.strip("，,。. ")
        return segment
    return ""


def _extract_scene_snippet_v2(prompt: str, keywords: list[str]) -> str:
    """场景描述提取 v2：取镜头 prompt 的环境描写部分。

    策略：找到关键词位置，从关键词前 30 字到后 80 字截取环境描写。
    如果该镜头是纯环境镜头（无角色名），取全文。
    """
    # 纯环境镜头（无角色名）→ 取全文
    has_person = any(name in prompt for name in _DEFAULT_CHAR_NAMES)
    if not has_person:
        return prompt.strip("，,。. ")

    # 有角色的镜头：从关键词位置截取环境片段
    for kw in keywords:
        idx = prompt.find(kw)
        if idx >= 0:
            start = max(0, idx - 30)
            end = min(len(prompt), idx + len(kw) + 60)
            snippet = prompt[start:end].strip("，,。. ")
            if len(snippet) >= 10:
                return snippet

    # 回退：取角色名之前的环境部分
    earliest = len(prompt)
    for name in _DEFAULT_CHAR_NAMES:
        idx = prompt.find(name)
        if 0 <= idx < earliest:
            earliest = idx
    snippet = prompt[:max(earliest, 60)].strip("，,。. ")
    return snippet if len(snippet) >= 10 else prompt[:120].strip("，,。. ")


def _extract_prop_snippet(prop_name: str, prompt: str) -> str:
    """从含道具名的 prompt 中提取道具外观描述片段。"""
    idx = prompt.find(prop_name)
    if idx < 0:
        return ""
    start = max(0, idx - 10)
    end = min(len(prompt), idx + len(prop_name) + 60)
    segment = prompt[start:end]
    segment = segment.strip("，,。. ")
    return segment
