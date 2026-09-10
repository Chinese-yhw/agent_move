/** 镜头页：分镜列表 + 首帧图生成（image_prompt + IP-Adapter）+ 视频抽卡 + 候选审核 */
import { useEffect, useState } from 'react'
import {
  approveVideo, cancelTask, deleteVideoCandidate, deleteShot, genVideo, listScriptAssets, listShots, listVideoCandidates, setShotFirstFrame,
  genShotImages, listShotImages, selectShotImage,
  type ShotImageCand,
} from '../api'
import { ErrBox, ScriptSelector, TaskBar, useScriptId } from '../components'
import { usePollTask } from '../usePollTask'
import type { Asset, Shot, VideoCandidate } from '../types'

const STATUS_BADGE: Record<string, string> = {
  '待生成': 'gray', '生成中': 'blue', '待审核': 'yellow', '通过': 'green', '需重做': 'red',
}

const TYPE_LABEL: Record<string, string> = { character: '角色', scene: '场景', prop: '道具' }

export default function ShotsPage() {
  const scriptId = useScriptId()
  const [shots, setShots] = useState<Shot[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    listShots(scriptId).then(setShots).catch(e => setError(e.message))
    listScriptAssets(scriptId).then(setAssets).catch(() => {})
  }
  useEffect(() => { refresh() }, [scriptId])

  return (
    <div>
      <div className="page-head">
        <h2>🎬 镜头生成与审核</h2>
        <ScriptSelector />
      </div>
      <p className="muted" style={{ marginTop: -6 }}>
        <b>推荐流程</b>：先到「标准照」页为角色/场景生成并锁定标准照 →
        回到本页点 <b>「🖼 生成首帧图」</b>（用 CSV 的 image_prompt + IP-Adapter 参考标准照）→
        选一张作为首帧 → 再点 <b>「🎬 生成视频」</b>（I2V，画面会动起来）。
        没生成专属首帧图时，会用关联素材的标准照作为首帧。
      </p>
      {shots.length === 0 && <p className="muted">暂无镜头，请先在「剧本」页提交分镜。</p>}
      <ErrBox error={error} />

      {shots.map(s => <ShotCard key={s.id} shot={s} assets={assets} onChanged={refresh} />)}
    </div>
  )
}

/** 单个镜头卡片：独立持有视频生成任务，scopeKey=video:<shotId>
 *  切到别的页面再回来，进度条会从 localStorage / 后端任务恢复 */
function ShotCard({ shot: s, assets, onChanged }: { shot: Shot; assets: Asset[]; onChanged: () => void }) {
  const [cands, setCands] = useState<VideoCandidate[] | null>(null)
  const [imgCands, setImgCands] = useState<ShotImageCand[] | null>(null)
  const [open, setOpen] = useState(false)
  const [openImgs, setOpenImgs] = useState(false)
  const [taskId, setTaskId] = useState<number | null>(null)
  const [imgTaskId, setImgTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [frameBusy, setFrameBusy] = useState(false)
  const [useT2V, setUseT2V] = useState(false)
  const { task, polling } = usePollTask(taskId, `video:${s.id}`)
  const { task: imgTask, polling: imgPolling } = usePollTask(imgTaskId, `shot-image:${s.id}`)

  // 当前生效首帧：专属首帧图 > 手动指定素材 > refs 中 is_first_frame 的那个
  const firstRef = s.refs.find(r => r.is_first_frame)
  const allAssets = assets
  const hasFirstFrame = Boolean(s.first_frame_image || firstRef)

  const loadCands = () =>
    listVideoCandidates(s.id).then(setCands).catch(e => setError(e.message))
  const loadImgCands = () =>
    listShotImages(s.id).then(setImgCands).catch(e => setError(e.message))

  useEffect(() => {
    if (task?.status === 'success') {
      setOpen(true)
      loadCands()
      onChanged()
    }
    if (imgTask?.status === 'success') {
      setOpenImgs(true)
      loadImgCands()
      onChanged()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.status, imgTask?.status])

  const changeFirstFrame = async (assetIdStr: string) => {
    setError(null)
    setFrameBusy(true)
    try {
      await setShotFirstFrame(s.id, assetIdStr ? Number(assetIdStr) : null)
      onChanged()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setFrameBusy(false)
    }
  }

  const generateImage = async () => {
    setError(null)
    try {
      const t = await genShotImages(s.id, 2)
      setImgTaskId(t.id)
      setOpenImgs(true)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const pickImage = async (cid: number) => {
    setError(null)
    try {
      await selectShotImage(s.id, cid)
      await loadImgCands()
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const generate = async () => {
    setError(null)
    try {
      const t = await genVideo(s.id, 2, undefined, useT2V)
      setTaskId(t.id)
      setOpen(true)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const approve = async (cid: number) => {
    try {
      await approveVideo(s.id, cid)
      await Promise.all([loadCands(), onChanged()])
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="shot-card">
      <div className="head">
        <strong>#{s.shot_no}</strong>
        <span className={`badge ${STATUS_BADGE[s.status] ?? 'gray'}`}>{s.status}</span>
        <span className="muted">{s.scene} · {s.shot_size} · {s.camera_movement} · {s.duration}s</span>
        <span style={{ flex: 1 }} />
        <button disabled={imgPolling} onClick={generateImage} title="用 CSV 的 image_prompt 生成镜头专属首帧图（IP-Adapter 参考角色/场景标准照）">
          {imgPolling ? '生图…' : '🖼 生成首帧图 ×2'}
        </button>
        {imgPolling && imgTaskId && (
          <button className="danger" onClick={async () => {
            try { await cancelTask(imgTaskId); setImgTaskId(null); } catch (e: any) { setError(e.message) }
          }}>⛔ 取消</button>
        )}
        <button onClick={() => { setOpenImgs(!openImgs); loadImgCands() }}>
          {openImgs ? '收起图候选' : '图候选'}
        </button>
        <button className="primary" disabled={polling} onClick={generate}>
          {polling ? '生成中…' : '🎬 生成视频 ×2'}
        </button>
        {polling && taskId && (
          <button className="danger" onClick={async () => {
            try { await cancelTask(taskId); setTaskId(null); } catch (e: any) { setError(e.message) }
          }}>
            ⛔ 取消
          </button>
        )}
        <label style={{ marginLeft: 8, fontSize: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={useT2V} onChange={e => setUseT2V(e.target.checked)} />
          <span style={{ marginLeft: 4 }}>特效模式（文生视频，跳过首帧）</span>
        </label>
        <button onClick={() => { setOpen(!open); loadCands() }}>
          {open ? '收起候选' : '查看候选'}
        </button>
        <button className="danger" title="删除此镜头（及其全部候选视频和台词）"
          onClick={async () => {
            if (!window.confirm(`确定删除镜头 #${s.shot_no}？其候选视频和台词也会被一并删除。`)) return
            try { await deleteShot(s.id); onChanged() } catch (e: any) { setError(e.message) }
          }}
        >🗑 删镜头</button>
      </div>
      {!hasFirstFrame && !useT2V && (
        <div style={{ color: '#e09050', fontSize: 12, marginTop: 4 }}>
          ⚠️ 该镜头无首帧图（也没关联素材标准照），未勾选特效模式会被拒绝生成视频
        </div>
      )}
      <div className="desc">{s.description}</div>
      {s.image_prompt && (
        <details style={{ marginTop: 4 }}>
          <summary className="muted" style={{ cursor: 'pointer', fontSize: 12 }}>📷 image_prompt（CSV 导入）</summary>
          <div style={{ fontSize: 12, color: '#888', padding: '4px 8px', background: '#1a1a1a', borderRadius: 4 }}>
            <div><b>正:</b> {s.image_prompt}</div>
            {s.negative_prompt && <div><b>负:</b> {s.negative_prompt}</div>}
          </div>
        </details>
      )}

      {/* 镜头专属首帧图（image_prompt 生成） */}
      {s.first_frame_image && (
        <div className="shot-first-frame" style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="badge green">已选首帧</span>
          <img src={s.first_frame_image} alt="镜头首帧" style={{ width: 160, borderRadius: 4 }} />
          <span className="muted" style={{ fontSize: 12 }}>此图作为视频 I2V 的首帧</span>
        </div>
      )}

      {/* 镜头首帧图候选 */}
      {openImgs && (
        <div className="image-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8, marginTop: 8 }}>
          {(imgCands ?? []).length === 0 && <span className="muted">暂无首帧图候选，点上方「生成首帧图」</span>}
          {(imgCands ?? []).map(c => (
            <div key={c.id} style={{ position: 'relative' }}>
              <img src={c.image_url} alt="候选" style={{ width: '100%', borderRadius: 4, border: c.is_selected ? '2px solid #4caf50' : '1px solid #333' }} />
              <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                <button style={{ flex: 1, padding: '2px 4px', fontSize: 11 }}
                  disabled={c.is_selected} onClick={() => pickImage(c.id)}>
                  {c.is_selected ? '已选' : '选为首帧'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      <ErrBox error={error || (imgTask?.status === 'failed' ? imgTask.error : null)} />
      <TaskBar task={imgTask} polling={imgPolling} label="首帧图生成（约 30~60s）" />

      {/* 关联素材与首帧 */}
      <div className="shot-refs">
        {s.refs.length === 0 && (
          <span className="muted">⚠️ 该镜头未关联到任何角色/场景（分镜中的名称与素材名不一致，或对应素材未提取）。
            可在下方手动选择一个素材作为首帧。</span>
        )}
        {s.refs.map(r => (
          <div key={r.id} className={`shot-ref ${r.is_first_frame ? 'is-first' : ''}`}
               title={r.is_first_frame ? '视频首帧' : TYPE_LABEL[r.type] ?? r.type}>
            {r.standard_image
              ? <img src={r.standard_image} alt={r.name} />
              : <div className="shot-ref-empty">无标准照</div>}
            <div className="shot-ref-name">
              <span className={`badge ${r.type === 'character' ? 'blue' : r.type === 'scene' ? 'yellow' : 'gray'}`}>
                {TYPE_LABEL[r.type] ?? r.type}
              </span> {r.name}
            </div>
            {r.is_first_frame && <div className="first-frame-tag">首帧</div>}
            {!r.standard_image && <div className="shot-ref-warn">待生成</div>}
          </div>
        ))}

        <div className="shot-frame-select">
          <label>首帧素材：</label>
          <select
            value={s.first_frame_asset_id ?? ''}
            disabled={frameBusy || allAssets.length === 0}
            onChange={e => changeFirstFrame(e.target.value)}
          >
            <option value="">自动（角色 → 场景）</option>
            {allAssets.map(a => (
              <option key={a.id} value={a.id}>
                {TYPE_LABEL[a.type] ?? a.type} · {a.name}
                {a.standard_image ? '' : '  (无标准照)'}
              </option>
            ))}
          </select>
          {allAssets.length === 0 && <span className="muted">项目还没有任何素材</span>}
          {!hasFirstFrame && allAssets.length > 0 && (
            <span className="muted">⚠️ 自动匹配不到：请在左侧手动选一个素材作为首帧</span>
          )}
        </div>
      </div>

      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      <TaskBar task={task} polling={polling} label={`视频生成（约 ${Math.round(s.duration)}s 镜头，单条 2~6 分钟）`} />

      {open && (cands?.length ?? 0) > 0 && (
        <div className="video-grid">
          {cands!.map(c => (
            <div key={c.id}>
              <video src={c.video_url} controls preload="metadata" />
              <div className="cand-actions">
                <span className={`badge ${c.status === '通过' ? 'green' : c.status === '淘汰' ? 'red' : 'gray'}`}>
                  {c.status === '通过' ? '已通过' : c.status === '淘汰' ? '已淘汰' : '待审核'}
                </span>
                {c.status !== '通过' && (
                  <button className="primary" onClick={() => approve(c.id)}>通过</button>
                )}
                <button className="danger" onClick={async () => {
                  try { await deleteVideoCandidate(c.id); await loadCands(); } catch (e: any) { setError(e.message) }
                }}>🗑 删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
