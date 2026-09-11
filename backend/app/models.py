"""核心数据模型（对应设计文档第六章）。

为简化本地起步，主键使用自增整数；生产可换 UUID。
JSON 字段用通用 JSON 类型，兼容 SQLite（开发）与 PostgreSQL（生产）。
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- 状态枚举 ----------
class AssetStatus(str, enum.Enum):
    pending = "待生成"
    generated = "已生成"
    locked = "已锁定"


class ShotStatus(str, enum.Enum):
    pending = "待生成"
    running = "生成中"
    review = "待审核"
    approved = "通过"
    redo = "需重做"


class CandidateStatus(str, enum.Enum):
    pending = "待审核"
    approved = "通过"
    rejected = "淘汰"


class TaskType(str, enum.Enum):
    detect = "detect"
    extract = "extract"
    image = "image"
    video = "video"
    tts = "tts"
    compose = "compose"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


# ---------- 表 ----------
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    style: Mapped[str] = mapped_column(String(64), default="写实电影感")
    status: Mapped[str] = mapped_column(String(16), default="进行中")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    scripts: Mapped[list["Script"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
    )


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    chapter: Mapped[int] = mapped_column(Integer, default=1)      # 集数/章节
    title: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")        # 剧本文本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="scripts")
    shots: Mapped[list["StoryboardShot"]] = relationship(
        back_populates="script", cascade="all, delete-orphan",
    )


class Asset(Base):
    """素材统一表：角色 / 场景 / 道具（type 区分）。"""
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
    )
    type: Mapped[str] = mapped_column(String(16))                 # character/scene/prop
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    identity_anchor: Mapped[str] = mapped_column(Text, default="")  # 全剧不可变的身份锚点（英文结构化描述），首帧生成强制注入
    extra: Mapped[dict] = mapped_column(JSON, default=dict)       # 性别/年龄/服装等
    reference_image: Mapped[str | None] = mapped_column(String(512))
    standard_image: Mapped[str | None] = mapped_column(String(512))  # 锁定的标准照 URL
    lora_name: Mapped[str | None] = mapped_column(String(256), nullable=True)   # ComfyUI models/loras 下的 LoRA 文件名（角色一致性）
    lora_strength: Mapped[float] = mapped_column(Float, default=0.9)            # LoRA 强度 0~1.2
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="assets")
    candidates: Mapped[list["ImageCandidate"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan",
    )


class ImageCandidate(Base):
    __tablename__ = "image_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=True,
    )
    shot_id: Mapped[int | None] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="CASCADE"), nullable=True,
    )
    image_url: Mapped[str] = mapped_column(String(512))
    prompt: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="comfyui")
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    asset: Mapped[Asset] = relationship(back_populates="candidates")


class StoryboardShot(Base):
    __tablename__ = "storyboard_shots"

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"),
    )
    shot_no: Mapped[int] = mapped_column(Integer)                 # 镜号
    scene: Mapped[str] = mapped_column(String(128), default="")   # 场景名
    description: Mapped[str] = mapped_column(Text, default="")    # 画面描述
    image_prompt: Mapped[str] = mapped_column(Text, default="")   # 文生图正提示词（从 CSV 导入）
    negative_prompt: Mapped[str] = mapped_column(Text, default="") # 文生图负提示词（从 CSV 导入）
    motion_prompt: Mapped[str] = mapped_column(Text, default="")  # 动作/运镜提示词（视频用）
    duration: Mapped[float] = mapped_column(Float, default=5.0)   # 秒
    camera_movement: Mapped[str] = mapped_column(String(64), default="")
    shot_size: Mapped[str] = mapped_column(String(32), default="")  # 景别
    dramatic_analysis: Mapped[str] = mapped_column(Text, default="")
    visual_notes: Mapped[str] = mapped_column(Text, default="")
    emotion_tone: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ShotStatus] = mapped_column(Enum(ShotStatus), default=ShotStatus.pending)
    character_ids: Mapped[list] = mapped_column(JSON, default=list)
    scene_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True,
    )
    first_frame_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True,
    )
    first_frame_image: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 镜头专属首帧图（image_prompt 生成）

    script: Mapped[Script] = relationship(back_populates="shots")
    candidates: Mapped[list["VideoCandidate"]] = relationship(
        back_populates="shot", cascade="all, delete-orphan",
    )
    dialogues: Mapped[list["Dialogue"]] = relationship(
        back_populates="shot", cascade="all, delete-orphan",
    )


class VideoCandidate(Base):
    __tablename__ = "video_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="CASCADE"),
    )
    video_url: Mapped[str] = mapped_column(String(512))
    duration: Mapped[float] = mapped_column(Float, default=5.0)
    model: Mapped[str] = mapped_column(String(64), default="wan2.1-i2v")
    prompt: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus), default=CandidateStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    shot: Mapped[StoryboardShot] = relationship(back_populates="candidates")


class Dialogue(Base):
    __tablename__ = "dialogues"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(
        ForeignKey("storyboard_shots.id", ondelete="CASCADE"),
    )
    character_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True,
    )
    speaker_name: Mapped[str] = mapped_column(String(32), default="")  # 导入时原文角色名（如"长老""字幕"），素材后建时用于回填 character_id
    text: Mapped[str] = mapped_column(Text)
    emotion: Mapped[str] = mapped_column(String(32), default="平静")
    voice_id: Mapped[str] = mapped_column(String(64), default="default")
    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    shot: Mapped[StoryboardShot] = relationship(back_populates="dialogues")


class Task(Base):
    """统一异步任务记录（含费用估算）。"""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    celery_id: Mapped[str] = mapped_column(String(64), default="")
    type: Mapped[TaskType] = mapped_column(Enum(TaskType))
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 关联对象 ID
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_yuan: Mapped[float] = mapped_column(Float, default=0.0)   # 实际/估算成本
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
