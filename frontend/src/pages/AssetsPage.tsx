/** 素材页：LLM 提取素材 + 按类型分 Tab 展示 + 编辑描述 */
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { extractAssets, listAssets, updateAsset, uploadAssetListTxt, deleteAsset } from '../api'
import { ErrBox, ScriptSelector, TaskBar, useScriptId } from '../components'
import { usePollTask } from '../usePollTask'
import type { Asset } from '../types'

const TABS = [
  { key: 'character', label: '角色' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
]

export default function AssetsPage() {
  const projectId = Number(useParams().id)
  const scriptId = useScriptId()
  const [assets, setAssets] = useState<Asset[]>([])
  const [tab, setTab] = useState('character')
  const [taskId, setTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [anchorDraft, setAnchorDraft] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const { task, polling } = usePollTask(taskId)

  /** 上传素材清单 txt：后端解析并新增素材条目；带当前剧本时自动关联镜头 */
  const onUploadTxt = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 清空以便重复选择同一文件
    if (!file) return
    setError(null); setMsg(null)
    try {
      const r = await uploadAssetListTxt(projectId, file, scriptId)
      setMsg(`解析 ${r.parsed} 项素材，新增 ${r.created} 条`
        + (r.linked_shots ? `，并已自动关联 ${r.linked_shots} 个镜头（可到镜头页查看首帧对应）`
                          : (scriptId ? '（未发生镜头关联：请先导入分镜，或清单中含【镜号N】对应块）' : '（提示：先在右上选择剧本，可自动关联镜头）')))
      refresh()
    } catch (err: any) {
      setError(err.message)
    }
  }

  const refresh = () => listAssets(projectId, scriptId).then(setAssets).catch(e => setError(e.message))
  useEffect(() => { refresh() }, [projectId, scriptId])
  useEffect(() => { if (task?.status === 'success') refresh() }, [task?.status])

  const start = async () => {
    setTaskId(null); setError(null)
    try {
      const t = await extractAssets(scriptId)
      setTaskId(t.id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const saveDesc = async (a: Asset) => {
    try {
      await updateAsset(a.id, { description: draft, identity_anchor: anchorDraft })
      setEditing(null)
      refresh()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const shown = assets.filter(a => a.type === tab)

  return (
    <div>
      <div className="page-head">
        <h2>🧩 素材</h2>
        <ScriptSelector />
      </div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button className="primary" disabled={polling} onClick={start}>
          {polling ? '提取中…' : '提取素材'}
        </button>
        <button onClick={() => fileRef.current?.click()}>📄 上传素材清单 txt</button>
        <input ref={fileRef} type="file" accept=".txt" style={{ display: 'none' }} onChange={onUploadTxt} />
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>
        支持两种清单：①「角色/物品/场景」章节式（变体自动拆条）；
        ②【名字·标准照】+ 提示词式，文件中带【镜号N】元素块时，会自动把素材绑定到对应镜头。
        {!scriptId && <b style={{ color: 'var(--yellow)' }}> 请先在右上角选择剧本，上传后才能自动关联镜头。</b>}
      </p>
      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      {msg && <div className="taskbar ok">{msg}</div>}
      <TaskBar task={task} polling={polling} label="素材提取" />

      <div className="tabs" style={{ marginTop: 16 }}>
        {TABS.map(t => (
          <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>
            {t.label}（{assets.filter(a => a.type === t.key).length}）
          </button>
        ))}
      </div>

      <div className="asset-list">
        {shown.length === 0 && <p className="muted">暂无{tab === 'character' ? '角色' : tab === 'scene' ? '场景' : '道具'}素材，先执行「提取素材」。</p>}
        {shown.map(a => (
          <div key={a.id} className="asset-row">
            <strong>{a.name}</strong>
            <span className={`badge ${a.status === '已锁定' ? 'green' : a.status === '已生成' ? 'blue' : 'gray'}`}>{a.status}</span>
            <div className="grow">
              {editing === a.id ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <label className="muted" style={{ fontSize: 12 }}>外观描述（中文，可含动作/氛围）</label>
                  <textarea style={{ minHeight: 48 }} value={draft} onChange={e => setDraft(e.target.value)} />
                  {a.type !== 'prop' && (
                    <>
                      <label className="muted" style={{ fontSize: 12 }}>
                        🔒 身份锚点 identity_anchor（英文，全剧不可变，强制注入每个镜头首帧）
                      </label>
                      <textarea
                        style={{ minHeight: 48, borderColor: 'var(--yellow)' }}
                        placeholder='例：fictional young man, square jaw, sharp dark eyes, black hair tied in topknot, plain teal ancient robe'
                        value={anchorDraft} onChange={e => setAnchorDraft(e.target.value)} />
                    </>
                  )}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="primary" onClick={() => saveDesc(a)}>保存</button>
                    <button onClick={() => setEditing(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <>
                  <span className="muted">{a.description || '（无描述）'}</span>
                  {a.type !== 'prop' && a.identity_anchor && (
                    <div style={{ marginTop: 4, fontSize: 12 }}>
                      <span className="badge green">🔒 锚点</span>{' '}
                      <span className="muted" style={{ fontStyle: 'italic' }}>{a.identity_anchor}</span>
                    </div>
                  )}
                </>
              )}
            </div>
            {editing !== a.id && (
              <>
                <button onClick={() => { setEditing(a.id); setDraft(a.description); setAnchorDraft(a.identity_anchor || '') }}>编辑</button>
                <button
                  className="danger"
                  title="删除素材及其全部候选图"
                  onClick={async () => {
                    if (!window.confirm(`确定删除素材「${a.name}」？其全部候选图也会被删除。`)) return
                    try { await deleteAsset(a.id); refresh() } catch (e: any) { setError(e.message) }
                  }}
                >删除</button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
