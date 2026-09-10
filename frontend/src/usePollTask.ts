/** 任务轮询 hook：每 3 秒查询一次，直到 success / failed。
 *
 * 传入 scopeKey（格式 "类型:对象ID"，如 image:19 / video:4）时具备切页恢复能力：
 * - 提交任务后 taskId 持久化到 localStorage
 * - 切页/刷新后组件重新挂载：先用本地 ID 继续轮询（进度条不丢）；
 *   本地没有记录时，主动向后端查询该对象仍在运行的任务并接管
 * - 任务终态（success/failed）后自动清除本地记录
 * 任务在后端 Celery worker 中执行，切页、关浏览器都不影响任务本身。
 */
import { useEffect, useState } from 'react'
import { getActiveTask, getTask } from './api'
import type { Task } from './types'

const LS_PREFIX = 'drama_task:'
const POLL_INTERVAL = 3000

export function usePollTask(taskId: number | null, scopeKey?: string) {
  const [task, setTask] = useState<Task | null>(null)
  const [polling, setPolling] = useState(false)

  useEffect(() => {
    let stopped = false
    let timer: number | null = null

    const clearTimer = () => {
      if (timer != null) { window.clearInterval(timer); timer = null }
    }

    const accept = (t: Task) => {
      if (stopped) return
      setTask(t)
      if (t.status === 'success' || t.status === 'failed') {
        setPolling(false)
        clearTimer()
        if (scopeKey) localStorage.removeItem(LS_PREFIX + scopeKey)
      }
    }

    const startPolling = (id: number) => {
      if (stopped) return
      setPolling(true)
      clearTimer()
      timer = window.setInterval(() => {
        getTask(id).then(accept).catch(() => { /* 网络抖动：下一轮继续 */ })
      }, POLL_INTERVAL)
      getTask(id).then(accept).catch(() => { /* 首轮失败：等下一轮 */ })
    }

    const adopt = (id: number) => {
      if (scopeKey) localStorage.setItem(LS_PREFIX + scopeKey, String(id))
      startPolling(id)
    }

    const boot = async () => {
      let id = taskId
      // 1) 未显式传入任务：先从 localStorage 找回（切页/刷新恢复）
      if (id == null && scopeKey) {
        const saved = localStorage.getItem(LS_PREFIX + scopeKey)
        if (saved) id = Number(saved)
      }

      if (id != null && Number.isFinite(id)) {
        try {
          const t = await getTask(id)
          if (t.status === 'pending' || t.status === 'running') {
            adopt(id)
            return
          }
          // 本地记录的任务已结束：清掉，落到下面的 active 查询兜底
          if (scopeKey) localStorage.removeItem(LS_PREFIX + scopeKey)
          accept(t)
        } catch {
          /* 任务 ID 失效（404）：继续走 active 查询 */
        }
      }

      // 2) 本地无有效任务：查询该对象当前是否有运行中的任务（后端任务恢复）
      if (scopeKey) {
        const [type, refId] = scopeKey.split(':')
        const active = await getActiveTask(type, Number(refId)).catch(() => null)
        if (!stopped && active && (active.status === 'pending' || active.status === 'running')) {
          adopt(active.id)
          return
        }
      }

      if (!stopped) {
        setPolling(false)
        clearTimer()
      }
    }

    boot()
    return () => {
      stopped = true
      clearTimer()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, scopeKey])

  // 新提交任务时立即持久化
  useEffect(() => {
    if (scopeKey && taskId != null) localStorage.setItem(LS_PREFIX + scopeKey, String(taskId))
  }, [taskId, scopeKey])

  return { task, polling }
}
