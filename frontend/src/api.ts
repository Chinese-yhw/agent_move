/** fetch 封装：开发时经 vite proxy 走相对路径；生产构建时回退到后端 origin */
import type {
  Asset, Costs, Dialogue, ImageCandidate, Issue, Project, Script, Shot, ShotInput, ShotRef, Task, VideoCandidate,
} from './types'

export const API_BASE = import.meta.env.DEV ? '' : 'http://localhost:8000'

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
/** 上传 DeepSeek 格式分镜表 txt，直接导入该剧本的分镜（整体替换） */
export const uploadStoryboardTxt = (scriptId: number, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return reqForm<{ created: number }>(`/api/scripts/${scriptId}/shots/upload`, form)
}
/** 删除剧本及其分镜 */
export const deleteScript = (scriptId: number) =>
  req<{ ok: boolean }>(`/api/scripts/${scriptId}`, { method: 'DELETE' })

// ---------- 检测 / 提取 ----------
export const detectScript = (scriptId: number) => req<Task>(`/api/scripts/${scriptId}/detect`, { method: 'POST' })
export const extractAssets = (scriptId: number) => req<Task>(`/api/scripts/${scriptId}/extract`, { method: 'POST' })
export const getTask = (taskId: number) => req<Task>(`/api/tasks/${taskId}`)
/** 查询某对象（type+refId）当前未结束的任务：切页/刷新回来后恢复进度条 */
export const getActiveTask = (type: string, refId: number) =>
  req<Task>(`/api/tasks/active?type=${encodeURIComponent(type)}&ref_id=${refId}`)

// ---------- 素材 ----------
export const listAssets = (projectId: number) => req<Asset[]>(`/api/projects/${projectId}/assets`)
/** 上传素材清单 txt（章节式 或【名字·标准照】式）；传 scriptId 时自动关联镜头↔素材 */
export const uploadAssetListTxt = (projectId: number, file: File, scriptId?: number | null) => {
  const form = new FormData()
  form.append('file', file)
  if (scriptId) form.append('script_id', String(scriptId))
  return reqForm<{ created: number; parsed: number; linked_shots: number }>(
    `/api/projects/${projectId}/assets/upload`, form)
}
export const updateAsset = (assetId: number, description: string) =>
  req<Asset>(`/api/assets/${assetId}`, { method: 'PATCH', body: JSON.stringify({ description }) })

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

// ---------- 镜头视频 ----------
export const genVideo = (shotId: number, n = 2) =>
  req<Task>(`/api/shots/${shotId}/videos`, { method: 'POST', body: JSON.stringify({ n_candidates: n }) })
export const listVideoCandidates = (shotId: number) =>
  req<VideoCandidate[]>(`/api/shots/${shotId}/candidates`)
export const approveVideo = (shotId: number, candidateId: number) =>
  req<{ ok: boolean }>(`/api/shots/${shotId}/approve`, { method: 'POST', body: JSON.stringify({ candidate_id: candidateId }) })
/** 镜头页选首帧用：剧本所属项目的全部素材 */
export const listScriptAssets = (scriptId: number) => req<Asset[]>(`/api/scripts/${scriptId}/assets`)
/** 手动指定镜头首帧（assetId=null 恢复自动选取） */
export const setShotFirstFrame = (shotId: number, assetId: number | null) =>
  req<{ ok: boolean; first_frame_asset_id: number | null }>(`/api/shots/${shotId}/first-frame`, {
    method: 'POST',
    body: JSON.stringify({ asset_id: assetId }),
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
