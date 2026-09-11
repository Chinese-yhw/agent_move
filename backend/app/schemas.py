"""Pydantic 请求/响应模型。"""
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Project / Script ----------
class ProjectCreate(BaseModel):
    name: str
    style: str = "写实电影感"


class ProjectOut(ORMModel):
    id: int
    name: str
    style: str
    status: str


class ScriptCreate(BaseModel):
    chapter: int = 1
    title: str = ""
    content: str


class ScriptUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    chapter: int | None = None


class ScriptOut(BaseModel):
    id: int
    project_id: int
    chapter: int
    title: str
    content: str
    shot_count: int = 0


class ShotIn(BaseModel):
    """分镜行（导入/批量创建用）。"""
    shot_no: int
    scene: str = ""
    description: str = ""
    image_prompt: str = ""
    negative_prompt: str = ""
    motion_prompt: str = ""
    duration: float = 5.0
    camera_movement: str = ""
    shot_size: str = ""
    dramatic_analysis: str = ""
    visual_notes: str = ""
    emotion_tone: str = ""
    character_names: list[str] = Field(default_factory=list)
    dialogues: list[dict] = Field(default_factory=list)  # {character, text, emotion}


class ShotsImport(BaseModel):
    shots: list[ShotIn]


class DialogueBrief(BaseModel):
    id: int = 0
    character: str = ""
    text: str
    emotion: str = ""


class ShotRefOut(BaseModel):
    """镜头关联的角色/场景素材摘要（含标准照与首帧标记）。"""
    id: int
    name: str
    type: str                    # character / scene / prop
    standard_image: str | None = None
    status: str = ""
    is_first_frame: bool = False


class ShotOut(ORMModel):
    id: int
    script_id: int
    shot_no: int
    scene: str
    description: str
    image_prompt: str = ""
    negative_prompt: str = ""
    motion_prompt: str
    duration: float
    camera_movement: str
    shot_size: str
    dramatic_analysis: str = ""
    visual_notes: str = ""
    emotion_tone: str = ""
    status: str
    character_ids: list
    scene_id: int | None = None
    first_frame_asset_id: int | None = None
    first_frame_image: str | None = None
    refs: list[ShotRefOut] = []
    dialogues: list[DialogueBrief] = []


# ---------- Asset ----------
class AssetOut(ORMModel):
    id: int
    project_id: int
    type: str
    name: str
    description: str
    identity_anchor: str = ""
    standard_image: str | None
    lora_name: str | None = None
    lora_strength: float = 0.9
    status: str


class AssetUpdate(BaseModel):
    description: str | None = None
    identity_anchor: str | None = None
    reference_image: str | None = None
    lora_name: str | None = None
    lora_strength: float | None = None


class SetLoraReq(BaseModel):
    """直接指定 ComfyUI models/loras/ 下的 LoRA 文件名（已在 GPU 端放好）。"""
    lora_name: str
    strength: float = 0.9


class GenerateImagesReq(BaseModel):
    n_candidates: int = 4          # 抽卡张数
    width: int = 832
    height: int = 480


class SelectCandidateReq(BaseModel):
    candidate_id: int


# ---------- Video ----------
class GenerateVideoReq(BaseModel):
    n_candidates: int = 2          # 每镜头候选数（控成本默认 2）
    duration: float | None = None  # 覆盖分镜时长
    force_t2v: bool = False        # 强制文生视频（忽略首帧检查）


class ApproveVideoReq(BaseModel):
    candidate_id: int


class SetFirstFrameReq(BaseModel):
    asset_id: int | None = None       # null = 恢复自动选取


# ---------- TTS ----------
class TtsGenerateReq(BaseModel):
    dialogue_ids: list[int] = Field(default_factory=list)  # 空=该集全部


# ---------- Compose ----------
class ComposeReq(BaseModel):
    script_id: int
    bgm_path: str | None = None
    burn_subtitle: bool = True


# ---------- Task ----------
class TaskOut(ORMModel):
    id: int
    type: str
    status: str
    progress: int
    result: dict | None
    error: str | None
    cost_yuan: float
