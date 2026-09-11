"""FastAPI 入口：CORS、媒体静态目录、建表、路由挂载。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.db import Base, engine

settings = get_settings()
Path(settings.media_root).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI 短剧生成平台", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    # 开发期直接建表；生产切换 alembic 迁移（见 README）
    Path(settings.media_root).mkdir(parents=True, exist_ok=True)
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 轻量迁移：老 SQLite 库补列（create_all 不会改已存在的表）
        for ddl in (
            "ALTER TABLE storyboard_shots ADD COLUMN first_frame_asset_id INTEGER",
            "ALTER TABLE dialogues ADD COLUMN speaker_name VARCHAR(32) DEFAULT ''",
            "ALTER TABLE assets ADD COLUMN lora_name VARCHAR(256)",
            "ALTER TABLE assets ADD COLUMN lora_strength FLOAT DEFAULT 0.9",
            "ALTER TABLE assets ADD COLUMN identity_anchor TEXT DEFAULT ''",
        ):
            try:
                await conn.execute(text(ddl))
            except Exception:  # 列已存在时忽略
                pass


app.mount(settings.media_base_url,
          StaticFiles(directory=settings.media_root), name="media")
app.include_router(router)


@app.get("/api/health")
async def health():
    from app.providers.comfyui import ComfyUIProvider, ComfyUIError
    comfyui_ok = False
    try:
        comfyui_ok = ComfyUIProvider().health_check()
    except (ComfyUIError, Exception):  # noqa: BLE001
        pass
    return {"ok": True, "comfyui_reachable": comfyui_ok}
