/** 配音页：台词表 + 批量 TTS + 音频试听 */
import { useEffect, useState } from 'react'
import { genTts, listDialogues, deleteDialogue } from '../api'
import { ErrBox, ScriptSelector, TaskBar, useScriptId } from '../components'
import { usePollTask } from '../usePollTask'
import type { Dialogue } from '../types'

export default function TtsPage() {
  const scriptId = useScriptId()
  const [rows, setRows] = useState<Dialogue[]>([])
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<number | null>(null)
  const { task, polling } = usePollTask(taskId)

  const refresh = () => listDialogues(scriptId).then(setRows).catch(e => setError(e.message))
  useEffect(() => { refresh() }, [scriptId])
  useEffect(() => { if (task?.status === 'success') refresh() }, [task?.status])

  const start = async () => {
    setError(null); setTaskId(null)
    try {
      const t = await genTts(scriptId)
      setTaskId(t.id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div>
      <div className="page-head">
        <h2>🔊 配音</h2>
        <ScriptSelector />
      </div>
      <button className="primary" disabled={polling} onClick={start}>
        {polling ? '配音中…' : '批量配音'}
      </button>
      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      <TaskBar task={task} polling={polling} label="批量配音" />

      <table style={{ marginTop: 14 }}>
        <thead>
          <tr><th>镜号</th><th>角色</th><th>台词</th><th>情绪</th><th style={{ width: 300 }}>音频</th><th>操作</th></tr>
        </thead>
        <tbody>
          {rows.map(d => (
            <tr key={d.id}>
              <td>{d.shot_no}</td>
              <td>{d.speaker_name || (d.character_id ? `角色#${d.character_id}` : '-')}</td>
              <td>{d.text}</td>
              <td><span className="badge blue">{d.emotion}</span></td>
              <td>{d.audio_url ? <audio src={d.audio_url} controls /> : <span className="muted">未配音</span>}</td>
              <td>
                <button className="danger" onClick={async () => {
                  if (!window.confirm('确定删除此台词？')) return
                  try { await deleteDialogue(d.shot_id, d.id); refresh() } catch (e: any) { setError(e.message) }
                }}>🗑</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="muted">暂无台词（先在剧本页提交含台词的分镜）</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
