/** 标准照页：素材卡片 + 抽卡生成候选图 + 选定标准照锁定 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { genImages, listAssets, listImageCandidates, selectStandard } from '../api'
import { ErrBox, Lightbox, TaskBar } from '../components'
import { usePollTask } from '../usePollTask'
import type { Asset, ImageCandidate } from '../types'

export default function ImagesPage() {
  const projectId = Number(useParams().id)
  const [assets, setAssets] = useState<Asset[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = () => listAssets(projectId).then(setAssets).catch(e => setError(e.message))
  useEffect(() => { refresh() }, [projectId])

  return (
    <div>
      <div className="page-head"><h2>🖼 标准照抽卡</h2></div>
      {assets.length === 0 && <p className="muted">暂无素材，请先在「素材」页执行提取。</p>}
      <ErrBox error={error} />

      <div className="masonry">
        {assets.map(a => <AssetCard key={a.id} asset={a} onChanged={refresh} />)}
      </div>
    </div>
  )
}

/** 单个素材卡片：独立持有生成任务，scopeKey=image:<assetId>
 *  切到别的页面再回来，进度条会从 localStorage / 后端任务恢复 */
function AssetCard({ asset: a, onChanged }: { asset: Asset; onChanged: () => void }) {
  const [cands, setCands] = useState<ImageCandidate[] | null>(null)
  const [taskId, setTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState<string | null>(null)
  const { task, polling } = usePollTask(taskId, `image:${a.id}`)

  const loadCands = () =>
    listImageCandidates(a.id).then(setCands).catch(e => setError(e.message))

  // 任务完成后刷新本卡片候选与素材状态
  useEffect(() => {
    if (task?.status === 'success') {
      loadCands()
      onChanged()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.status])

  const generate = async () => {
    setError(null)
    try {
      const t = await genImages(a.id, 4, 832, 480)
      setCands(null)
      setTaskId(t.id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const pick = async (cid: number) => {
    try {
      await selectStandard(a.id, cid)
      await Promise.all([loadCands(), onChanged()])
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div className="asset-row" onClick={() => !cands && loadCands()}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <strong>{a.name}</strong>
        <span className={`badge ${a.status === '已锁定' ? 'green' : 'gray'}`}>{a.status}</span>
      </div>
      <div className="muted" style={{ fontSize: 12, margin: '4px 0' }}>{a.description}</div>
      {a.standard_image && (
        <img className="std-img" src={a.standard_image} alt={`${a.name} 标准照`}
             onClick={e => { e.stopPropagation(); setZoom(a.standard_image!) }} />
      )}

      <ErrBox error={error || (task?.status === 'failed' ? task.error : null)} />
      <TaskBar task={task} polling={polling} label="候选图生成（约 1~2 分钟）" />

      {cands && cands.length > 0 && (
        <div className="img-grid">
          {cands.map(c => (
            <figure key={c.id}>
              <img src={c.image_url} alt={c.prompt} loading="lazy" title="点击放大"
                   onClick={e => { e.stopPropagation(); setZoom(c.image_url) }} />
              <figcaption>
                {c.is_selected
                  ? <span className="badge green">已选定</span>
                  : <button onClick={e => { e.stopPropagation(); pick(c.id) }}>设为标准照</button>}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <button className="primary" disabled={polling} onClick={e => { e.stopPropagation(); generate() }}>
          {polling ? '生成中…' : '生成候选 ×4'}
        </button>
        <button onClick={e => { e.stopPropagation(); loadCands() }}>查看候选</button>
      </div>

      {zoom && <Lightbox src={zoom} alt={a.name} onClose={() => setZoom(null)} />}
    </div>
  )
}
