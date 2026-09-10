"""Celery 应用。

开发环境无 Redis 时自动退化为线程同步执行（BROKER=memory + ALWAYS_EAGER），
生产 Docker Compose 中启用真实 Redis broker + worker。
"""
from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "drama_gen",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.generation"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    # 视频任务可能跑 10 分钟以上
    task_time_limit=settings.comfyui_video_timeout + 300,
    soft_time_limit=settings.comfyui_video_timeout,
    worker_prefetch_multiplier=1,   # GPU 串行：一次只领一个生成任务，避免打爆显存
    broker_connection_retry_on_startup=True,
)

# 开发环境无 Redis 时退化为同步执行（.delay() 变成立即返回的 EagerResult，
# 任务本体由 API 进程内后台线程执行，避免阻塞请求）
import threading

try:
    import redis as _redis

    _redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
except Exception:  # noqa: BLE001
    from celery.result import EagerResult

    def _eager_delay(self, *args, **kwargs):
        def _run():
            try:
                # 走 apply() 完整任务 trace（而非直接 __call__），
                # 这样 on_failure / 重试耗尽 等回调才会执行并把失败写回 tasks 表
                self.apply(args=args, kwargs=kwargs)
            except Exception:  # noqa: BLE001
                pass  # 任务内部已把失败写入 tasks 表
        threading.Thread(target=_run, daemon=True).start()
        return EagerResult("eager", None, "PENDING")

    from celery import Task as _Task

    _Task.apply_async = _eager_delay  # type: ignore[assignment]
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
