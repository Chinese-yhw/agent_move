"""全局配置：环境变量驱动，本地开发与 Docker 部署共用。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 数据库 / 队列
    database_url: str = "sqlite+aiosqlite:///./data/drama_gen.db"
    redis_url: str = "redis://localhost:6379/0"

    # 文件存储
    media_root: str = "./data/media"
    media_base_url: str = "/media"

    # ComfyUI（AutoDL）
    comfyui_base_url: str = ""
    comfyui_image_workflow: str = "workflows/z_image_turbo_api.json"
    comfyui_video_workflow: str = "workflows/wan21_i2v_api.json"
    comfyui_poll_interval: float = 3.0      # 轮询间隔（秒）
    comfyui_image_timeout: int = 600        # 文生图超时
    comfyui_video_timeout: int = 3600       # 图生视频超时

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # TTS
    tts_base_url: str = ""
    tts_mode: str = "s1"

    # 成本估算（本地部署：只算 GPU 时租，单位 元/小时）
    gpu_hourly_cost: float = 1.88
    est_image_seconds: int = 20             # 单张标准照预计耗时（秒）
    est_video_seconds_per_clip: int = 300   # 单个 5s 480p 镜头预计耗时（秒）


@lru_cache
def get_settings() -> Settings:
    return Settings()
