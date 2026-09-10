/** 合成页：导出成片任务 + 视频预览下载 */
import { useState } from 'react'
import { composeExport } from '../api'
import { ErrBox, ScriptSelector, TaskBar, useScriptId } from '../components'
import { usePollTask } from '../usePollTask'

export default function ComposePage() {
  const scriptId = useScriptId()
  const [burn, setBurn] = useState(true)
  const [taskId, setTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { task, polling } = usePollTask(taskId)

  const start = async () => {
    setError(null); setTaskId(null)
    try {
      const t = await composeExport(scriptId, burn)
      setTaskId(t.id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const videoUrl = task?.status === 'success' ? task.result?.video_url as string | undefined : undefined

  return (
    <div>
      <div className="page-head">
        <h2>🎞 合成导出</h2>
        <ScriptSelector />
      </div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <button className="primary" disabled={polling} onClick={start}>
          {polling ? '合成中…' : '导出成片'}
        </button>
        <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={burn} onChange={e => setBurn(e.target.checked)} />
          烧录字幕
        </label>
      </div>
      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      <TaskBar task={task} polling={polling} label="成片合成" />
      {videoUrl && (
        <div style={{ marginTop: 16, maxWidth: 720 }}>
          <video src={videoUrl} controls style={{ width: '100%', borderRadius: 8, background: '#000' }} />
          <p><a href={videoUrl} download>⬇️ 下载成片</a></p>
        </div>
      )}
    </div>
  )
}
