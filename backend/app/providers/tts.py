"""CosyVoice TTS Provider：调用 AutoDL 上部署的 CosyVoice HTTP 服务。

兼容两种常见部署形态：
1. FastAPI 封装版（cosyvoice webui/api）：POST /tts {text, speaker, emotion} -> wav bytes
2. 自建极简服务：同上约定
若你的部署接口不同，只需改 _request 一处。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from app.config import get_settings

settings = get_settings()


class TTSError(RuntimeError):
    pass


class CosyVoiceProvider:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.tts_base_url).rstrip("/")
        self.client = httpx.Client(base_url=self.base_url or "http://invalid", timeout=120.0)

    def tts(self, text: str, voice_id: str = "default", emotion: str = "平静") -> Path:
        if not self.base_url:
            raise TTSError("未配置 TTS_BASE_URL")
        resp = self.client.post("/tts", json={
            "text": text,
            "speaker": voice_id,
            "emotion": emotion,
            "mode": settings.tts_mode,
        })
        if resp.status_code != 200:
            raise TTSError(f"TTS 调用失败 {resp.status_code}: {resp.text[:300]}")
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
