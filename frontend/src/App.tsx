/** 路由表 + 项目工作区布局 */
import { useEffect, useState } from 'react'
import { NavLink, Outlet, Route, Routes, useParams } from 'react-router-dom'
import { getHealth, listProjects } from './api'
import type { Project } from './types'
import ProjectsPage from './pages/ProjectsPage'
import ScriptPage from './pages/ScriptPage'
import DetectPage from './pages/DetectPage'
import AssetsPage from './pages/AssetsPage'
import ImagesPage from './pages/ImagesPage'
import ShotsPage from './pages/ShotsPage'
import TtsPage from './pages/TtsPage'
import ComposePage from './pages/ComposePage'
import CostsPage from './pages/CostsPage'

const NAV = [
  { path: 'script', label: '📋 剧本' },
  { path: 'detect', label: '🔍 检测' },
  { path: 'assets', label: '🧩 素材' },
  { path: 'images', label: '🖼 标准照' },
  { path: 'shots', label: '🎬 镜头' },
  { path: 'tts', label: '🔊 配音' },
  { path: 'compose', label: '🎞 合成' },
  { path: 'costs', label: '💰 成本' },
]

/** GPU（ComfyUI）连接状态指示灯 */
function GpuStatus() {
  const [ok, setOk] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    const check = () => getHealth().then(h => alive && setOk(h.comfyui_reachable)).catch(() => alive && setOk(false))
    check()
    const t = window.setInterval(check, 15000)
    return () => { alive = false; window.clearInterval(t) }
  }, [])
  return (
    <span className="gpu">
      <span className={`dot ${ok ? 'on' : 'off'}`} />
      GPU {ok === null ? '检测中…' : ok ? '已连接' : '离线'}
    </span>
  )
}

/** 项目工作区：左侧导航 + 顶部项目栏 + 主内容 */
function Workspace() {
  const { id } = useParams()
  const projectId = Number(id)
  const [project, setProject] = useState<Project | null>(null)

  useEffect(() => {
    listProjects().then(list => setProject(list.find(p => p.id === projectId) ?? null)).catch(() => setProject(null))
  }, [projectId])

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo"><NavLink to="/" style={{ color: 'inherit' }}>🎭 AI 短剧</NavLink></div>
        <nav>
          {NAV.map(n => (
            <NavLink key={n.path} to={`/project/${id}/${n.path}`}>{n.label}</NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="proj">{project ? `《${project.name}》 · ${project.style}` : `项目 #${id}`}</span>
          <GpuStatus />
        </header>
        <main className="content" key={projectId}>
          <Outlet context={{ project }} />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/project/:id" element={<Workspace />}>
        <Route index element={<ScriptPage />} />
        <Route path="script" element={<ScriptPage />} />
        <Route path="detect" element={<DetectPage />} />
        <Route path="assets" element={<AssetsPage />} />
        <Route path="images" element={<ImagesPage />} />
        <Route path="shots" element={<ShotsPage />} />
        <Route path="tts" element={<TtsPage />} />
        <Route path="compose" element={<ComposePage />} />
        <Route path="costs" element={<CostsPage />} />
      </Route>
    </Routes>
  )
}
