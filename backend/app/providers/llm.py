"""LLM 服务：剧本/分镜内容检测 + 素材提取（DeepSeek，OpenAI 兼容协议）。"""
from __future__ import annotations

import json

from openai import OpenAI

from app.config import get_settings

settings = get_settings()

DETECT_PROMPT = """你是资深短剧制片与剧本审校。请检查下面的【剧本】与【分镜】，找出问题并输出 JSON。

检测维度：
1. character_consistency 角色一致性：同一角色名/性别/身份前后矛盾
2. scene_continuity 场景连续性：相邻分镜场景跳变无过渡
3. prop_closure 道具闭环：道具出现后无下文
4. dialogue_owner 台词归属：台词没有明确说话人
5. duration 时长合理性：镜头时长不在 3~8 秒
6. camera 景别/运镜完整性：缺少景别或运镜描述
7. plot_logic 剧情逻辑：时间线、因果关系不通顺

只输出 JSON，格式：
{"issues": [{"dimension": "...", "severity": "error|warning", "location": "第N镜/段落", "detail": "问题描述", "suggestion": "修改建议"}]}

【剧本】
{script}

【分镜】
{storyboard}
"""

EXTRACT_PROMPT = """你是短剧美术指导。从下面的【剧本】与【分镜】中提取所有角色、场景、道具，输出 JSON。

要求：
- appearance/description 必须是可直接用于 AI 文生图的中文外观描述（脸型、发型发色、服装材质颜色、光线氛围等），每个角色 100~200 字
- 角色需给出 gender、age、costume（主要服装）
- 场景给出 time_of_day（白天/夜晚/傍晚…）
- 不要遗漏只在台词中提到的道具

只输出 JSON：
{{"characters": [{{"name":"","gender":"","age":"","appearance":"","costume":"","personality":""}}],
 "scenes": [{{"name":"","description":"","time_of_day":""}}],
 "props": [{{"name":"","description":""}}]}}

【剧本】
{script}

【分镜】
{storyboard}
"""

TRANSLATE_PROMPT = """把下面的中文分镜画面描述翻译成 Wan 视频模型用的英文提示词。
规则：只写「人物动作 + 镜头运动 + 简短氛围」，不要描述长相服装（外貌由首帧图决定）。
一个镜头一个简单动作。总长不超过 40 个英文单词。只输出提示词本身。

中文描述：{description}
运镜：{camera_movement}
"""


def _client() -> OpenAI:
    if not settings.llm_api_key:
        raise RuntimeError(
            "未配置 LLM_API_KEY：请在 backend/.env 填入 DeepSeek API Key"
            "（https://platform.deepseek.com 注册→创建 API Key→充值 ¥10 够用很久）"
        )
    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def _chat(prompt: str) -> str:
    resp = _client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""


def _extract_json(text: str) -> dict:
    """容错解析：剥掉 markdown 代码块再 loads。"""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.removeprefix("json").removeprefix("JSON").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"LLM 未返回 JSON，原始内容: {text[:300]}")
    result = json.loads(text[start:end + 1])
    if not isinstance(result, dict):
        raise ValueError(f"LLM 返回的不是 JSON 对象: {str(result)[:200]}")
    return result


def detect_issues(script_content: str, storyboard_json: str) -> list[dict]:
    raw = _chat(DETECT_PROMPT.format(script=script_content, storyboard=storyboard_json))
    data = _extract_json(raw)
    issues = data.get("issues")
    if issues is None:  # LLM 偶尔直接返回数组本体
        return data if isinstance(data, list) else []
    return issues


STORYBOARD_PROMPT = """你是专业短剧分镜师。把下面的【剧本正文】拆解成分镜脚本，输出 JSON。

规则：
1. 每集总时长约 {target_seconds} 秒，单镜头 3~8 秒（平均 5 秒），据此估算镜头数量（一般 12~20 个）
2. 每个镜头包含：shot_no(从1连续编号)、scene(场景名)、description(画面描述：谁在哪做什么，中文)、motion_prompt(英文视频提示词：只写动作+运镜+氛围，不超过30词，不写长相服装)、duration(秒)、camera_movement(运镜：固定/推近/拉远/跟拍/环绕/摇移等)、shot_size(景别：远景/全景/中景/近景/特写)、character_names(出场角色名数组)、dialogues(该镜头台词数组，每项{{"character":"说话人","text":"台词","emotion":"情绪"}}，无台词则空数组)
3. 开场交代环境，对话用正反打，结尾留悬念钩子；相邻镜头景别要有变化
4. 角色名、场景名必须与剧本一致，不要发明新角色

只输出 JSON：{{"shots": [...]}}

【剧本正文】
{script}
"""


def generate_storyboard(script_content: str, target_seconds: int = 90) -> list[dict]:
    """剧本 → 分镜草稿数组。"""
    raw = _chat(STORYBOARD_PROMPT.format(script=script_content, target_seconds=target_seconds))
    data = _extract_json(raw)
    shots = data.get("shots")
    if shots is None and isinstance(data, list):
        shots = data
    if not shots:
        raise ValueError(f"LLM 未生成分镜: {str(data)[:200]}")
    return shots


def extract_assets(script_content: str, storyboard_json: str) -> dict:
    raw = _chat(EXTRACT_PROMPT.format(script=script_content, storyboard=storyboard_json))
    return _extract_json(raw)


def translate_motion_prompt(description: str, camera_movement: str = "") -> str:
    """分镜中文描述 → Wan 英文动作提示词。失败则回退原文。"""
    try:
        return _chat(TRANSLATE_PROMPT.format(
            description=description, camera_movement=camera_movement or "无特殊运镜"
        )).strip()
    except Exception:
        return description
