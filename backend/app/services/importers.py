"""文本导入解析器：分镜表 txt / 素材清单 txt。

支持两种分镜表格式：
1. DeepSeek/Excel 复制：Tab 分隔（或 2+ 空格），含表头
2. Markdown 表格：| 镜号 | 景别 | 时长 | … |，含 |:---| 分隔行

支持两种素材清单格式：
1. 章节式：「角色 / 物品 / 场景」大节 + 主体/变体/音色字段
2. 标准照提示词式：【名字·标准照】+ 提示词段落；
   文件前部可带【镜号N】元素清单块，用于自动关联镜头↔素材
"""
from __future__ import annotations

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
