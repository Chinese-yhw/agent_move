/** 项目列表页：卡片列表 + 新建项目 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createProject, deleteProject, listProjects } from '../api'
import { ErrBox } from '../components'
import type { Project } from '../types'

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [name, setName] = useState('')
  const [style, setStyle] = useState('写实电影感')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nav = useNavigate()

  const refresh = () => listProjects().then(setProjects).catch(e => setError(String(e.message || e)))
  useEffect(() => { refresh() }, [])

  const onCreate = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const p = await createProject(name.trim(), style)
      nav(`/project/${p.id}/script`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (id: number, pname: string) => {
    if (!window.confirm(`确定删除项目「${pname}」？\n其全部剧本、分镜、素材、候选图/视频和任务记录都会被删除，此操作不可恢复。`)) return
    setError(null)
    try {
      await deleteProject(id)
      // 若当前正停在被删项目里，回到首页
      if (window.location.pathname.startsWith(`/project/${id}/`)) nav('/')
      refresh()
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="content" style={{ maxWidth: 960, margin: '0 auto' }}>
      <h1>🎭 AI 短剧生成平台</h1>
      <div className="new-project">
        <input placeholder="项目名称" value={name} onChange={e => setName(e.target.value)} />
        <select value={style} onChange={e => setStyle(e.target.value)}>
          <option>写实电影感</option>
          <option>国漫风格</option>
          <option>日系动画</option>
          <option>赛博朋克</option>
          <option>古风水墨</option>
        </select>
        <button className="primary" disabled={busy || !name.trim()} onClick={onCreate}>
          {busy ? '创建中…' : '＋ 新建项目'}
        </button>
      </div>
      <ErrBox error={error} />
      {projects.length === 0 && !error && <p className="muted">还没有项目，先创建一个吧。</p>}
      <div className="cards">
        {projects.map(p => (
          <div key={p.id} className="card" onClick={() => nav(`/project/${p.id}/script`)}>
            <div className="name">{p.name}</div>
            <div className="meta">#{p.id} · {p.style} · {p.status}</div>
            <button
              className="card-del"
              title="删除项目"
              onClick={e => { e.stopPropagation(); onDelete(p.id, p.name) }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
