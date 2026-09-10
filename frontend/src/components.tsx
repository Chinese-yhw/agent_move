/** 通用小组件：错误提示、任务状态条、剧本选择器 */
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listProjects, listScripts } from './api'
import type { Task } from './types'

export function ErrBox({ error }: { error: string | null }) {
  if (!error) return null
  return <div className="err">{error}</div>
}

/** 轮询中的任务进度条 */
export function TaskBar({ task, polling, label }: { task: Task | null; polling: boolean; label?: string }) {
  if (!task) return null
  if (task.status === 'success') {
    return <div className="taskbar ok">✅ {label ?? '任务'}完成（费用 ¥{task.cost_yuan.toFixed(4)}）</div>
  }
  if (task.status === 'failed') {
    return <div className="taskbar fail">❌ {label ?? '任务'}失败：{task.error || '未知错误'}</div>
  }
  return (
    <div className="taskbar running">
      ⏳ {label ?? '任务'}进行中（{task.status}）…
      <div className="progress"><div style={{ width: `${Math.max(task.progress, 5)}%` }} /></div>
      {polling ? '' : ''}
    </div>
  )
}

/** 图片灯箱：点击候选图放大查看，点击空白处或按 Esc 关闭 */
export function Lightbox({ src, alt, onClose }: { src: string; alt?: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="lightbox" onClick={onClose} title="点击关闭（Esc 亦可）">
      <img src={src} alt={alt ?? ''} onClick={e => e.stopPropagation()} />
    </div>
  )
}

/** 全局当前剧本选择：存 localStorage，跨页面保持；URL ?sid=N 优先 */
const LS_KEY = 'drama_current_script'

export function getCurrentScriptId(): number {
  return Number(localStorage.getItem(LS_KEY) || 1)
}

export function ScriptSelector() {
  const [params, setParams] = useSearchParams()
  const urlSid = params.get('sid') ? Number(params.get('sid')) : null
  const [scripts, setScripts] = useState<{ id: number; chapter: number; title: string; shot_count?: number }[]>([])
  const sid = urlSid ?? getCurrentScriptId()

  // 拉取全部剧本供下拉（多项目时按项目分组拼接）
  useEffect(() => {
    listProjects()
      .then(ps => Promise.all(ps.map(p => listScripts(p.id).catch(() => []))))
      .then(groups => setScripts(groups.flat().sort((a, b) => a.id - b.id)))
      .catch(() => setScripts([]))
  }, [])

  useEffect(() => {
    localStorage.setItem(LS_KEY, String(sid))
  }, [sid])

  const apply = (n: number) => {
    if (!n) return
    localStorage.setItem(LS_KEY, String(n))
    const next = new URLSearchParams(params)
    next.set('sid', String(n))
    setParams(next, { replace: true })
  }

  const cur = scripts.find(s => s.id === sid)
  return (
    <label className="script-sel">
      当前剧本:
      <select value={cur ? cur.id : ''} onChange={e => apply(Number(e.target.value))}>
        {!cur && <option value="" disabled>#{sid}{scripts.length ? '' : '（暂无剧本）'}</option>}
        {scripts.map(s => (
          <option key={s.id} value={s.id}>
            #{s.id} EP{s.chapter} {s.title}{s.shot_count != null ? `（${s.shot_count}镜）` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

export function useScriptId(): number {
  const [params] = useSearchParams()
  const [, force] = useState(0)
  // localStorage 变化（其他标签页/组件切换）时刷新
  useEffect(() => {
    const onStorage = () => force(x => x + 1)
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return params.get('sid') ? Number(params.get('sid')) : getCurrentScriptId()
}
