/** 检测页：发起内容检测任务，轮询后按严重度分组渲染问题清单 */
import { useState } from 'react'
import { detectScript } from '../api'
import { ErrBox, ScriptSelector, TaskBar, useScriptId } from '../components'
import { usePollTask } from '../usePollTask'
import type { Issue } from '../types'

function IssueList({ issues, severity }: { issues: Issue[]; severity: 'error' | 'warning' }) {
  if (issues.length === 0) return null
  return (
    <>
      <h3>{severity === 'error' ? '🔴 错误' : '🟡 警告'}（{issues.length}）</h3>
      {issues.map((it, i) => (
        <div key={i} className={`issue ${severity}`}>
          <span className="dim">{it.dimension}</span>
          <span className="loc">{it.location}</span>
          <div>{it.detail}</div>
          {it.suggestion && <div className="sug">💡 建议：{it.suggestion}</div>}
        </div>
      ))}
    </>
  )
}

export default function DetectPage() {
  const scriptId = useScriptId()
  const [taskId, setTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { task, polling } = usePollTask(taskId)

  const start = async () => {
    setTaskId(null); setError(null)
    try {
      const t = await detectScript(scriptId)
      setTaskId(t.id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const issues: Issue[] = task?.status === 'success' ? (task.result?.issues ?? []) : []
  const errs = issues.filter(i => i.severity === 'error')
  const warns = issues.filter(i => i.severity !== 'error')

  return (
    <div>
      <div className="page-head">
        <h2>🔍 内容检测</h2>
        <ScriptSelector />
      </div>
      <button className="primary" disabled={polling} onClick={start}>
        {polling ? '检测中…' : '开始检测'}
      </button>
      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      <TaskBar task={task} polling={polling} label="检测" />
      {task?.status === 'success' && (
        issues.length === 0
          ? <div className="taskbar ok">未发现问题 ✨</div>
          : <>
              <IssueList issues={errs} severity="error" />
              <IssueList issues={warns} severity="warning" />
            </>
      )}
    </div>
  )
}
