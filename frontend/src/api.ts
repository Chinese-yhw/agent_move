/** fetch 封装：开发时经 vite proxy 走相对路径；生产构建时回退到后端 origin */
import type {
  Asset, Costs, Dialogue, ImageCandidate, Issue, Project, Script, Shot, ShotInput, Task, VideoCandidate,
} from './types'

// 开发时走 vite proxy（空字符串），生产时也走同源（nginx 反代 /api /media 到后端）
// 这样前端构建一次，部署到任何域名都能工作
export const API_BASE = ''

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ''}`)
  }
  return res.json() as Promise<T>
}

/** multipart/form-data 请求封装：不手动设 Content-Type，让浏览器自动带 boundary */
async function reqForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: form })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ''}`)
  }
  return res.json() as Promise<T>
}

// ---------- 健康检查 ----------
export const getHealth = () => req<{ ok: boolean; comfyui_reachable: boolean }>('/api/health')

// ---------- 项目 / 剧本 ----------
export const listProjects = () => req<Project[]>('/api/projects')
export const createProject = (name: string, style: string) =>
  req<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name, style }) })
export const deleteProject = (projectId: number) =>
  req<{ ok: boolean }>(`/api/projects/${projectId}`, { method: 'DELETE' })
export const createScript = (projectId: number, chapter: number, title: string, content: string) =>
  req<{ id: number }>(`/api/projects/${projectId}/scripts`, {
    method: 'POST',
    body: JSON.stringify({ chapter, title, content }),
  })
export const listScripts = (projectId: number) => req<Script[]>(`/api/projects/${projectId}/scripts`)
export const getScript = (scriptId: number) => req<Script>(`/api/scripts/${scriptId}`)
export const updateScript = (scriptId: number, patch: { title?: string; content?: string; chapter?: number }) =>
  req<Script>(`/api/scripts/${scriptId}`, { method: 'PUT', body: JSON.stringify(patch) })

// ---------- 分镜 ----------
export const listShots = (scriptId: number) => req<Shot[]>(`/api/scripts/${scriptId}/shots`)
export const importShots = (scriptId: number, shots: ShotInput[]) =>
  req<Shot[]>(`/api/scripts/${scriptId}/shots`, { method: 'POST', body: JSON.stringify({ shots }) })
/** 整体替换分镜（避免与旧数据重复） */
export const replaceShots = (scriptId: number, shots: ShotInput[]) =>
  req<Shot[]>(`/api/scripts/${scriptId}/shots/replace`, { method: 'POST', body: JSON.stringify({ shots }) })
/** AI 生成分镜：后端同步调 LLM，耗时约 20~60 秒，不设超时 */
export const generateStoryboard = (scriptId: number) =>
  req<{ created: number; shots: number[] }>(`/api/scripts/${scriptId}/generate_storyboard`, { method: 'POST' })
/** 上传分镜表 txt/md，自动识别表格或段落式 Markdown 分镜拆解 */
export const uploadStoryboardTxt = (scriptId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return reqForm<{ created: number; format?: string }>(`/api/scripts/${scriptId}/shots/upload`, form)
}
/** 上传 CSV 提示词表（2.csv 格式），覆盖镜头 image_prompt/negative_prompt + 自动提取素材 */
export const uploadCsvPrompts = (scriptId: number, file: File, createAssets = true) => {
  const form = new FormData()
  form.append('file', file)
  form.append('create_assets', String(createAssets))
  return reqForm<{ shots_parsed: number; shots_updated: number; shots_created: number; assets_created: number }>(`/api/scripts/${scriptId}/shots/upload-csv`, form)
}
/** 删除剧本及其分镜 */
export const deleteScript = (scriptId: number) =>
  req<{ ok: boolean }>(`/api/scripts/${scriptId}`, { method: 'DELETE' })

// ---------- 检测 / 提取 ----------
export const detectScript = (scriptId: number) => req<Task>(`/api/scripts/${scriptId}/detect`, { method: 'POST' })
export const extractAssets = (scriptId: number) => req<Task>(`/api/scripts/${scriptId}/extract`, { method: 'POST' })
export const getTask = (taskId: number) => req<Task>(`/api/tasks/${taskId}`)
/** 取消正在执行的异步任务（Celery revoke + 改 DB 状态）。已经在 ComfyUI 跑的无法中断，会继续跑完 */
export const cancelTask = (taskId: number) => req<{ ok: boolean; status: string }>(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
/** 查询某对象（type+refId）当前未结束的任务：切页/刷新回来后恢复进度条 */
export const getActiveTask = (type: string, refId: number) =>
  req<Task>(`/api/tasks/active?type=${encodeURIComponent(type)}&ref_id=${refId}`)

// ---------- 素材 ----------
export const listAssets = (projectId: number, scriptId?: number | null) => {
  const qs = scriptId ? `?script_id=${scriptId}` : ''
  return req<Asset[]>(`/api/projects/${projectId}/assets${qs}`)
}
/** 上传素材清单 txt（章节式 或【名字·标准照】式）；传 scriptId 时自动关联镜头↔素材 */
export const uploadAssetListTxt = (projectId: number, file: File, scriptId?: number | null) => {
  const form = new FormData()
  form.append('file', file)
  if (scriptId) form.append('script_id', String(scriptId))
  return reqForm<{ created: number; parsed: number; linked_shots: number }>(
    `/api/projects/${projectId}/assets/upload`, form)
}
export const updateAsset = (assetId: number, patch: { description?: string; identity_anchor?: string }) =>
  req<Asset>(`/api/assets/${assetId}`, { method: 'PATCH', body: JSON.stringify(patch) })
/** 上传角色参考脸图（FaceID 用）。只有 character 类型素材可用。 */
export const uploadReferenceImage = (assetId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return reqForm<Asset>(`/api/assets/${assetId}/reference-image`, form)
}
/** 设置角色一致性 LoRA：指定 ComfyUI models/loras/ 下的文件名 + 强度。 */
export const setAssetLora = (assetId: number, loraName: string, strength = 0.9) =>
  req<Asset>(`/api/assets/${assetId}/lora`, {
    method: 'POST', body: JSON.stringify({ lora_name: loraName, strength }),
  })

// ---------- 标准照 ----------
export const genImages = (assetId: number, n = 4, width = 832, height = 480) =>
  req<Task>(`/api/assets/${assetId}/images`, { method: 'POST', body: JSON.stringify({ n_candidates: n, width, height }) })
export const listImageCandidates = (assetId: number) =>
  req<ImageCandidate[]>(`/api/assets/${assetId}/candidates`)
export const selectStandard = (assetId: number, candidateId: number) =>
  req<{ ok: boolean; standard_image: string }>(`/api/assets/${assetId}/select`, {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId }),
  })
export const deleteImageCandidate = (candidateId: number) =>
  req<{ ok: boolean }>(`/api/candidates/images/${candidateId}`, { method: 'DELETE' })
export const deleteAsset = (assetId: number) =>
  req<{ ok: boolean }>(`/api/assets/${assetId}`, { method: 'DELETE' })

// ---------- 镜头视频 ----------
export const genVideo = (shotId: number, n = 2, duration?: number, force_t2v = false) =>
  req<Task>(`/api/shots/${shotId}/videos`, {
    method: 'POST',
    body: JSON.stringify({ n_candidates: n, duration, force_t2v }),
  })
export const listVideoCandidates = (shotId: number) =>
  req<VideoCandidate[]>(`/api/shots/${shotId}/candidates`)
export const approveVideo = (shotId: number, candidateId: number) =>
  req<{ ok: boolean }>(`/api/shots/${shotId}/approve`, { method: 'POST', body: JSON.stringify({ candidate_id: candidateId }) })
export const deleteVideoCandidate = (candidateId: number) =>
  req<{ ok: boolean }>(`/api/candidates/videos/${candidateId}`, { method: 'DELETE' })
export const deleteShot = (shotId: number) =>
  req<{ ok: boolean }>(`/api/shots/${shotId}`, { method: 'DELETE' })
export const deleteDialogue = (shotId: number, dialogueId: number) =>
  req<{ ok: boolean }>(`/api/shots/${shotId}/dialogues/${dialogueId}`, { method: 'DELETE' })
/** 镜头页选首帧用：剧本所属项目的全部素材 */
export const listScriptAssets = (scriptId: number) => req<Asset[]>(`/api/scripts/${scriptId}/assets`)
/** 手动指定镜头首帧（assetId=null 恢复自动选取） */
export const setShotFirstFrame = (shotId: number, assetId: number | null) =>
  req<{ ok: boolean; first_frame_asset_id: number | null }>(`/api/shots/${shotId}/first-frame`, {
    method: 'POST',
    body: JSON.stringify({ asset_id: assetId }),
  })

// ---------- 镜头首帧图（CSV image_prompt 生成） ----------
export interface ShotImageCand { id: number; image_url: string; prompt: string; is_selected: boolean }
export const genShotImages = (shotId: number, n = 2, width = 624, height = 352) =>
  req<Task>(`/api/shots/${shotId}/images`, {
    method: 'POST', body: JSON.stringify({ n_candidates: n, width, height }),
  })
export const listShotImages = (shotId: number) =>
  req<ShotImageCand[]>(`/api/shots/${shotId}/images`)
export const selectShotImage = (shotId: number, candId: number) =>
  req<{ ok: boolean; first_frame_image: string }>(`/api/shots/${shotId}/images/${candId}/select`, {
    method: 'POST', body: '{}',
  })

// ---------- 配音 ----------
export const listDialogues = (scriptId: number) => req<Dialogue[]>(`/api/scripts/${scriptId}/dialogues`)
export const genTts = (scriptId: number) => req<Task>(`/api/scripts/${scriptId}/tts`, { method: 'POST', body: '{}' })

// ---------- 合成 ----------
export const composeExport = (scriptId: number, burnSubtitle: boolean) =>
  req<Task>('/api/compose/export', { method: 'POST', body: JSON.stringify({ script_id: scriptId, burn_subtitle: burnSubtitle }) })

// ---------- 成本 ----------
export const getCosts = (projectId: number) => req<Costs>(`/api/projects/${projectId}/costs`)

export type { Asset, Costs, Dialogue, ImageCandidate, Issue, Project, Script, Shot, ShotInput, Task, VideoCandidate }
