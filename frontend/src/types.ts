/** 与后端 schemas.py / routes.py 对应的类型定义 */

export interface Project {
  id: number
  name: string
  style: string
  status: string
}

export interface Script {
  id: number
  project_id: number
  chapter: number
  title: string
  content: string
  shot_count: number
}

export interface Task {
  id: number
  type: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  progress: number
  result: Record<string, any> | null
  error: string | null
  cost_yuan: number
}

export interface DialogueIn {
  character: string
  text: string
  emotion: string
}

/** 分镜行（提交格式） */
export interface ShotInput {
  shot_no: number
  scene: string
  description: string
  image_prompt: string
  negative_prompt: string
  motion_prompt: string
  duration: number
  camera_movement: string
  shot_size: string
  character_names: string[]
  dialogues: DialogueIn[]
}

/** 镜头关联的角色/场景素材（含标准照与首帧标记） */
export interface ShotRef {
  id: number
  name: string
  type: 'character' | 'scene' | 'prop' | string
  standard_image: string | null
  status: string
  is_first_frame: boolean
}

/** 分镜行（后端返回） */
export interface Shot {
  id: number
  script_id: number
  shot_no: number
  scene: string
  description: string
  image_prompt: string
  negative_prompt: string
  motion_prompt: string
  duration: number
  camera_movement: string
  shot_size: string
  status: string
  character_ids: number[]
  scene_id: number | null
  first_frame_asset_id: number | null
  first_frame_image: string | null
  refs: ShotRef[]
  dialogues: { id: number; character: string; text: string; emotion: string }[]
}

export interface Asset {
  id: number
  project_id: number
  type: 'character' | 'scene' | 'prop' | string
  name: string
  description: string
  reference_image: string | null
  standard_image: string | null
  status: string
}

export interface ImageCandidate {
  id: number
  image_url: string
  prompt: string
  is_selected: boolean
  created_at: string
}

export interface VideoCandidate {
  id: number
  video_url: string
  prompt: string
  status: string
  duration: number
}

export interface Dialogue {
  id: number
  shot_id: number
  shot_no: number
  character_id: number | null
  speaker_name: string
  text: string
  emotion: string
  voice_id: string | null
  audio_url: string | null
}

export interface Issue {
  dimension: string
  severity: 'error' | 'warning' | string
  location: string
  detail: string
  suggestion: string
}

export interface Costs {
  by_type: Record<string, { count: number; cost_yuan: number }>
  total_yuan: number
}
