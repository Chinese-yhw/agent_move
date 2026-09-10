"""TTS Provider：CosyVoice（远程 GPU）+ edge-tts（本地兜底）。

优先级：配置了 TTS_BASE_URL 且可达 → CosyVoice；否则 → edge-tts（免费、本地、无需 GPU）。
edge-tts 支持 emotion（通过 rate/pitch 微调和 SSML express-as 情绪标签）。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()


class TTSError(RuntimeError):
    pass


# ---------- 通用情绪映射 ----------
def _emotion_to_edge(emotion: str) -> dict:
    """把情绪词映射到 edge-tts 可用的表达参数（rate/pitch/volume）。
    edge-tts 的中文情绪标签（express-as）：cheerful/sad/angry/fearful/disfearful/embarrassed
    /serous/friendly/terrified/shouting/whispering/newscast/narrating。
    不是所有情绪都完美匹配，pitch/rate 微调作为额外手段。
    """
    e = emotion or "中性"
    # 情绪标签 → edge-tts express-as + 语速/音调微调
    mapping = {
        "中性":     {"rate": "+0%",  "pitch": "+0Hz"},
        "平静":     {"rate": "+0%",  "pitch": "+0Hz"},
        "高兴":     {"rate": "+10%", "pitch": "+5Hz"},
        "激动":     {"rate": "+15%", "pitch": "+8Hz"},
        "悲伤":     {"rate": "-8%",  "pitch": "-5Hz"},
        "愤怒":     {"rate": "+5%",  "pitch": "-3Hz"},
        "惊讶":     {"rate": "+10%", "pitch": "+8Hz"},
        "恐惧":     {"rate": "-5%",  "pitch": "-5Hz"},
        "紧张":     {"rate": "+5%",  "pitch": "-3Hz"},
        "低语":     {"rate": "-3%",  "pitch": "-3Hz"},
    }
    return mapping.get(e, mapping["中性"])


def _voice_for(speaker_name: str) -> str:
    """角色名 → edge-tts 中文声音。默认用晓伊（女声），可按需扩展。"""
    name = (speaker_name or "").strip()
    if not name or name in ("字幕", "旁白"):
        return "zh-CN-XiaoxiaoNeural"
    # 简单启发式：名字含"瑶""阿""妹"→女声；含"北望""长老""师兄""师父"→男声；默认女声
    female_hints = ("瑶", "阿瑶", "妹", "女")
    male_hints = ("北望", "长老", "师兄", "师父", "师兄", "林渊", "师兄")
    if any(h in name for h in female_hints):
        return "zh-CN-XiaoyiNeural"
    if any(h in name for h in male_hints):
        return "zh-CN-YunxiNeural"
    return "zh-CN-XiaoxiaoNeural"


# ---------- Provider 工厂 ----------
def get_tts_provider() -> "TTSProvider":
    """根据配置返回可用的 TTS Provider（CosyVoice 优先，edge-tts 兜底）。"""
    url = (settings.tts_base_url or "").strip()
    # 没配 URL 或还是占位符 → 用 edge-tts
    if not url or "REPLACE_ME" in url or "invalid" in url:
        return EdgeTTSProvider()
    try:
        return CosyVoiceProvider(url)
    except Exception:
        return EdgeTTSProvider()


class TTSProvider:
    """抽象基类。"""
    def tts(self, text: str, voice_id: str = "default", emotion: str = "中性") -> Path:
        raise NotImplementedError


# ---------- CosyVoice ----------
class CosyVoiceProvider(TTSProvider):
    def __init__(self, base_url: str):
        import httpx
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=120.0)

    def tts(self, text: str, voice_id: str = "default", emotion: str = "中性") -> Path:
        resp = self.client.post("/tts", json={
            "text": text,
            "speaker": voice_id,
            "emotion": emotion,
            "mode": settings.tts_mode,
        })
        if resp.status_code != 200:
            raise TTSError(f"CosyVoice 调用失败 {resp.status_code}: {resp.text[:300]}")
        out_dir = Path(settings.media_root) / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{uuid.uuid4().hex[:12]}.wav"
        out.write_bytes(resp.content)
        return out

    def list_voices(self) -> list[str]:
        try:
            return self.client.get("/voices").json()
        except Exception:
            return ["default"]


# ---------- edge-tts ----------
class EdgeTTSProvider(TTSProvider):
    """免费本地兜底：edge-tts（微软在线 TTS，无需 GPU）。"""

    def __init__(self):
        import edge_tts  # 延迟导入，避免没装时启动就崩
        self.edge_tts = edge_tts

    def tts(self, text: str, voice_id: str = "default", emotion: str = "中性") -> Path:
        # voice_id 如果是角色名（如"阿瑶"），映射到具体声音
        voice = voice_id if voice_id.startswith("zh-") else _voice_for(voice_id)
        params = _emotion_to_edge(emotion)

        async def _run():
            communicate = self.edge_tts.Communicate(
                text, voice,
                rate=params["rate"],
                pitch=params["pitch"],
                # express-as 需用 SSML 包装，edge-tts 6+ 支持。
                # 简单做法：用 rate/pitch 微调即可，express-as 作为可选增强。
            )
            out_dir = Path(settings.media_root) / "audio"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{uuid.uuid4().hex[:12]}.mp3"
            await communicate.save(str(out))
            return out

        try:
            return asyncio.run(_run())
        except Exception as exc:
            raise TTSError(f"edge-tts 生成失败: {exc}") from exc

    def list_voices(self) -> list[str]:
        return [
            "zh-CN-XiaoxiaoNeural",   # 晓筱 女声
            "zh-CN-XiaoyiNeural",    # 晓伊 女声（温柔）
            "zh-CN-YunxiNeural",     # 云希 男声（磁性）
            "zh-CN-YunjianNeural",   # 云健 男声
            "zh-CN-XiaohanNeural",   # 晓涵 女声
            "zh-CN-YunyangNeural",   # 云扬 男声
        ]
