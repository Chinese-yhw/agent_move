/** 成本页：按任务类型汇总 GPU 费用 + ¥500/100集 预算进度条 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getCosts } from '../api'
import { ErrBox } from '../components'
import type { Costs } from '../types'

const TYPE_LABEL: Record<string, string> = {
  detect: '检测', extract: '提取', image: '标准照', video: '镜头视频', tts: '配音', compose: '合成',
}

const EPISODES = 100        // 全季集数估算
const BUDGET_PER_100 = 500  // ¥500 / 100 集目标

export default function CostsPage() {
  const projectId = Number(useParams().id)
  const [costs, setCosts] = useState<Costs | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCosts(projectId).then(setCosts).catch(e => setError(e.message))
  }, [projectId])

  const total = costs?.total_yuan ?? 0
  const seasonEst = total * EPISODES           // 单集成本 × 100 集
  const pct = Math.min(100, (seasonEst / BUDGET_PER_100) * 100)

  return (
    <div>
      <div className="page-head"><h2>💰 成本看板</h2></div>
      <ErrBox error={error} />
      <p className="big-num">¥{total.toFixed(4)}</p>
      <p className="muted">本项目累计 GPU 费用（单集）</p>

      <table style={{ marginTop: 10 }}>
        <thead><tr><th>任务类型</th><th>次数</th><th>费用(¥)</th></tr></thead>
        <tbody>
          {Object.entries(costs?.by_type ?? {}).map(([k, v]) => (
            <tr key={k}>
              <td>{TYPE_LABEL[k] ?? k}</td>
              <td>{v.count}</td>
              <td>{v.cost_yuan.toFixed(4)}</td>
            </tr>
          ))}
          {costs && Object.keys(costs.by_type).length === 0 && (
            <tr><td colSpan={3} className="muted">尚无产生费用的任务</td></tr>
          )}
        </tbody>
      </table>

      <div className="budget">
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>🎯 预算目标：¥{BUDGET_PER_100} / {EPISODES} 集</span>
          <span className={seasonEst > BUDGET_PER_100 ? '' : 'muted'}>
            按当前单集成本估算全季 ≈ <strong style={{ color: seasonEst > BUDGET_PER_100 ? 'var(--red)' : 'var(--green)' }}>
              ¥{seasonEst.toFixed(2)}
            </strong>
          </span>
        </div>
        <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
          {seasonEst > BUDGET_PER_100
            ? '⚠️ 已超出预算，请降低抽卡次数或缩短镜头时长。'
            : `预算使用 ${pct.toFixed(1)}%，仍有 ¥${(BUDGET_PER_100 - seasonEst).toFixed(2)} 余量。`}
        </p>
      </div>
    </div>
  )
}
