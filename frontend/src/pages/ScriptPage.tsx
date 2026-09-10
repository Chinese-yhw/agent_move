/** 剧本页：剧本历史列表 + 新建/编辑剧本 + AI 生成分镜 + 分镜表格编辑 */
import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  createScript, deleteScript, generateStoryboard, listScripts, listShots,
  replaceShots, updateScript, uploadStoryboardTxt, uploadCsvPrompts,
} from '../api'
import { ErrBox } from '../components'
import type { Script, ShotInput } from '../types'

const emptyShot = (no: number): ShotInput => ({
  shot_no: no, scene: '', description: '', image_prompt: '', negative_prompt: '',
  motion_prompt: '', duration: 5,
  camera_movement: '', shot_size: '', character_names: [], dialogues: [],
})

/** 解析粘贴的表格文本：支持 Tab 分隔（DeepSeek/Excel）与 Markdown 表格（| 分隔） */
function parseStoryboardTable(text: string): ShotInput[] {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  if (lines.length === 0) return []
  // 切成单元格：Markdown(|) > Tab > 2+ 空格；跳过 |:---| 分隔行
  let rows = lines.map(l => {
    if (l.includes('|')) {
      const cells = l.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
      if (cells.length > 1 && cells.every(c => /^:?-+:?$/.test(c.replace(/\s/g, '')) || c === '')) return null
      return cells
    }
    return l.split('\t')
  }).filter(Boolean) as string[][]
  if (rows.every(r => r.length <= 1)) {
    rows = lines.map(l => l.split(/\s{2,}/))
  }
  // 识别并跳过表头行
  const headerIdx = rows.findIndex(r => r.some(c => /镜\s*号/.test(c)))
  let colMap: Record<string, number> = {}
  if (headerIdx >= 0) {
    rows[headerIdx].forEach((h, i) => { colMap[h.replace(/\s/g, '')] = i })
    rows = rows.slice(headerIdx + 1)
  } else {
    colMap = { '镜号': 0, '景别': 1, '时长': 2, '画面描述': 3, '台词/内心独白': 4, '运镜/音效提示': 5 }
  }
  // 表头模糊匹配：支持「画面描述（含角色外貌…）」这类长表头
  const findCol = (...names: string[]) => {
    for (const n of names) {
      const hit = Object.entries(colMap).find(([k]) => k === n || k.startsWith(n))
      if (hit) return hit[1]
    }
    return undefined
  }
  const pick = (cols: string[], ...names: string[]) => {
    const idx = findCol(...names)
    if (idx !== undefined && cols[idx] !== undefined) return String(cols[idx]).trim()
    return ''
  }
  /** 台词单元格拆多条：「林渊：… 阿瑶：…」 */
  const parseDialogues = (cell: string) => {
    cell = (cell || '').trim()
    if (!cell || cell === '无' || cell.includes('无台词')) return []
    const ms = [...cell.matchAll(/([一-龥A-Za-z·]{2,8})：/g)]
    if (ms.length === 0) return [{ character: '', text: cell, emotion: '平静' }]
    const out: { character: string; text: string; emotion: string }[] = []
    ms.forEach((m, i) => {
      const end = i + 1 < ms.length ? (ms[i + 1].index ?? 0) : cell.length
      const t = cell.slice((m.index ?? 0) + m[0].length, end).trim().replace(/[；;]\s*$/, '')
      if (t) out.push({ character: m[1], text: t, emotion: '平静' })
    })
    return out
  }
  return rows.map((cols, i) => {
    const noRaw = pick(cols, '镜号') || String(i + 1)
    const durRaw = pick(cols, '时长', '时长(s)', '时长（秒）').replace(/[sS秒]/g, '')
    let duration = parseFloat(durRaw)
    if (!isFinite(duration) || duration <= 0) duration = 5
    duration = Math.min(Math.max(duration, 3), 8)
    const dialogueText = pick(cols, '台词/内心独白', '台词', '内心独白', '台词/独白')
    return {
      shot_no: parseInt(noRaw, 10) || i + 1,
      scene: pick(cols, '场景', '场景名'),
      description: pick(cols, '画面描述', '描述'),
      image_prompt: '',
      negative_prompt: '',
      motion_prompt: '',
      duration,
      camera_movement: pick(cols, '运镜/音效提示', '运镜', '运镜/音效'),
      shot_size: pick(cols, '景别'),
      character_names: [],
      dialogues: parseDialogues(dialogueText),
    }
  }).filter(s => s.description || s.dialogues.length)
}

export default function ScriptPage() {
  const projectId = Number(useParams().id)
  const [params, setParams] = useSearchParams()
  const scriptId = Number(params.get('sid') || 0) || null

  const [scripts, setScripts] = useState<Script[]>([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [shots, setShots] = useState<ShotInput[]>([])
  const [error, setError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [nf, setNf] = useState({ chapter: 1, title: '', content: '' })
  const [showPaste, setShowPaste] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const csvRef = useRef<HTMLInputElement>(null)

  /** 上传分镜表 txt：后端整体替换该剧本的分镜 */
  const onUploadTxt = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 清空以便重复选择同一文件
    if (!file || !scriptId) return
    setBusy(true); setError(null); setMsg(null)
    try {
      const r = await uploadStoryboardTxt(scriptId, file)
      setMsg(`已导入 ${r.created} 条分镜${r.format ? `（${r.format}）` : ''}`)
      await refreshList() // 刷新历史列表（shot_count 变化）
      const list = await listShots(scriptId).catch(() => [])
      setShots(list.map(sh => ({
        shot_no: sh.shot_no, scene: sh.scene, description: sh.description,
        image_prompt: sh.image_prompt ?? '', negative_prompt: sh.negative_prompt ?? '',
        motion_prompt: sh.motion_prompt, duration: sh.duration,
        camera_movement: sh.camera_movement, shot_size: sh.shot_size,
        character_names: [], dialogues: [],
      })))
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** 上传 CSV 提示词表（2.csv 格式）：覆盖镜头 prompt + 自动提取素材 */
  const onUploadCsv = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !scriptId) return
    setBusy(true); setError(null); setMsg(null)
    try {
      const r = await uploadCsvPrompts(scriptId, file)
      setMsg(`CSV 导入完成：解析 ${r.shots_parsed} 镜，更新 ${r.shots_updated} 镜，新建 ${r.shots_created} 镜，提取素材 ${r.assets_created} 个`)
      await refreshList()
      const list = await listShots(scriptId).catch(() => [])
      setShots(list.map(sh => ({
        shot_no: sh.shot_no, scene: sh.scene, description: sh.description,
        image_prompt: sh.image_prompt ?? '', negative_prompt: sh.negative_prompt ?? '',
        motion_prompt: sh.motion_prompt, duration: sh.duration,
        camera_movement: sh.camera_movement, shot_size: sh.shot_size,
        character_names: [], dialogues: [],
      })))
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /** 删除剧本（二次确认），若删的是当前选中剧本则清除 ?sid */
  const removeScript = async (id: number) => {
    if (!window.confirm(`确定删除剧本 #${id} 及其全部分镜？此操作不可恢复。`)) return
    setError(null); setMsg(null)
    try {
      await deleteScript(id)
      setMsg(`剧本 #${id} 已删除`)
      if (id === scriptId) {
        const next = new URLSearchParams(params)
        next.delete('sid')
        setParams(next, { replace: true })
        setShots([])
      }
      refreshList()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const applyPaste = () => {
    const parsed = parseStoryboardTable(pasteText)
    if (parsed.length === 0) { setError('没有解析出任何行，请确认粘贴内容包含表头（镜号/景别/时长/画面描述…）和数据行'); return }
    setShots(parsed)
    setShowPaste(false)
    setMsg(`已解析 ${parsed.length} 行填入表格，请检查后点「批量提交分镜」`)
  }

  const selectScript = (id: number) => {
    localStorage.setItem('drama_current_script', String(id))
    const next = new URLSearchParams(params)
    next.set('sid', String(id))
    setParams(next, { replace: true })
  }

  const refreshList = () => listScripts(projectId).then(setScripts).catch(e => setError(e.message))

  // 加载剧本历史列表
  useEffect(() => { refreshList(); setError(null) }, [projectId])

  // 选中剧本后回填编辑区 + 加载现有分镜
  useEffect(() => {
    if (!scriptId) return
    setError(null); setMsg(null)
    listScripts(projectId)
      .then(list => {
        setScripts(list)
        const s = list.find(x => x.id === scriptId)
        if (s) { setTitle(s.title); setContent(s.content) }
      })
      .catch(e => setError(e.message))
    listShots(scriptId).then(list =>
      setShots(list.map(sh => ({
        shot_no: sh.shot_no, scene: sh.scene, description: sh.description,
        image_prompt: sh.image_prompt ?? '', negative_prompt: sh.negative_prompt ?? '',
        motion_prompt: sh.motion_prompt, duration: sh.duration,
        camera_movement: sh.camera_movement, shot_size: sh.shot_size,
        character_names: [], dialogues: [],
      })))
    ).catch(() => setShots([]))
  }, [scriptId, projectId])

  const patch = (i: number, key: keyof ShotInput, val: any) =>
    setShots(prev => prev.map((s, j) => j === i ? { ...s, [key]: val } : s))

  const saveScript = async () => {
    if (!scriptId || !content.trim()) return
    setBusy(true); setError(null); setMsg(null)
    try {
      await updateScript(scriptId, { title, content })
      setMsg('剧本已保存')
      refreshList()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const aiGenerate = async (id?: number) => {
    const target = id ?? scriptId
    if (!target) return
    setAiBusy(true); setError(null); setMsg(null)
    try {
      const r = await generateStoryboard(target)
      setMsg(`已生成 ${r.created} 个分镜，请到下方/镜头页检查修改`)
      await refreshList()
      if (target === scriptId) {
        const list = await listShots(target).catch(() => [])
        setShots(list.map(sh => ({
          shot_no: sh.shot_no, scene: sh.scene, description: sh.description,
          motion_prompt: sh.motion_prompt, duration: sh.duration,
          camera_movement: sh.camera_movement, shot_size: sh.shot_size,
          character_names: [], dialogues: [],
        })))
      }
    } catch (e: any) {
      setError(e.message)
    } finally {
      setAiBusy(false)
    }
  }

  const submitNew = async () => {
    if (!nf.content.trim()) return
    setBusy(true); setError(null); setMsg(null)
    try {
      const r = await createScript(projectId, nf.chapter, nf.title, nf.content)
      setShowNew(false)
      setNf({ chapter: 1, title: '', content: '' })
      await refreshList()
      selectScript(r.id)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const submitShots = async () => {
    if (!scriptId || shots.length === 0) return
    setBusy(true); setError(null); setMsg(null)
    try {
      // 整体替换：成功后后端返回新分镜列表，重新拉取（含台词）回填编辑区，所见即所存
      const saved = await replaceShots(scriptId, shots)
      const fresh = await listShots(scriptId)
      setShots(fresh.map(s => ({
        shot_no: s.shot_no, scene: (s as any).scene ?? '', description: s.description,
        image_prompt: (s as any).image_prompt ?? '', negative_prompt: (s as any).negative_prompt ?? '',
        motion_prompt: s.motion_prompt ?? '', duration: s.duration,
        camera_movement: s.camera_movement ?? '', shot_size: s.shot_size ?? '',
        character_names: (s as any).character_names ?? [],
        dialogues: ((s as any).dialogues ?? []).map((d: any) => ({ character: d.character ?? '', text: d.text, emotion: d.emotion ?? '' })),
      })))
      setMsg(`✅ 已提交 ${saved.length} 条分镜并保存到数据库（可切换页面，数据不会丢）`)
      refreshList()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="page-head">
        <h2>📋 剧本</h2>
        <button onClick={() => { setShowNew(v => !v); setMsg(null) }}>＋ 新建剧本</button>
      </div>
      <ErrBox error={error} />
      {msg && <div className="taskbar ok">{msg}</div>}

      {showNew && (
        <div className="budget" style={{ marginTop: 0, marginBottom: 16 }}>
          <h3>新建剧本</h3>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <input type="number" min={1} style={{ width: 90 }} value={nf.chapter}
              onChange={e => setNf(p => ({ ...p, chapter: Number(e.target.value) || 1 }))} placeholder="集数" />
            <input style={{ width: 220 }} value={nf.title} placeholder="标题"
              onChange={e => setNf(p => ({ ...p, title: e.target.value }))} />
          </div>
          <textarea rows={8} style={{ minHeight: 140 }} placeholder="粘贴本集剧本正文…" value={nf.content}
            onChange={e => setNf(p => ({ ...p, content: e.target.value }))} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="primary" disabled={busy || !nf.content.trim()} onClick={submitNew}>创建</button>
            <button onClick={() => setShowNew(false)}>取消</button>
          </div>
        </div>
      )}

      <h3>剧本历史</h3>
      <table>
        <thead>
          <tr><th>ID</th><th>集数</th><th>标题</th><th>正文字数</th><th>分镜数</th><th>操作</th></tr>
        </thead>
        <tbody>
          {scripts.length === 0 && <tr><td colSpan={6} className="muted">暂无剧本，点击右上「＋ 新建剧本」。</td></tr>}
          {scripts.map(s => (
            <tr key={s.id} className={s.id === scriptId ? 'selected' : undefined}>
              <td>{s.id}</td>
              <td>第{s.chapter}集</td>
              <td>{s.title || '（无标题）'}</td>
              <td>{s.content.length}</td>
              <td>{s.shot_count}</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                <button onClick={() => selectScript(s.id)}>编辑</button>
                <button style={{ marginLeft: 8 }} disabled={!scriptValid(s) || aiBusy}
                  onClick={() => { if (s.id !== scriptId) selectScript(s.id); aiGenerate(s.id) }}>生成分镜</button>
                <button style={{ marginLeft: 8 }} onClick={() => removeScript(s.id)}>删除</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {scriptId && (
        <>
          <h3 style={{ marginTop: 24 }}>编辑剧本 #{scriptId}</h3>
          <input placeholder="标题" value={title} onChange={e => setTitle(e.target.value)} style={{ width: 260, marginBottom: 8 }} />
          <textarea rows={15} placeholder="剧本正文…" value={content} onChange={e => setContent(e.target.value)} />
          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button className="primary" disabled={busy || !content.trim()} onClick={saveScript}>保存剧本</button>
            <button disabled={aiBusy || busy || !content.trim()} onClick={() => aiGenerate()}>
              {aiBusy ? '🤖 AI 拆解中（约1分钟）…' : '🤖 AI 生成分镜'}
            </button>
          </div>

          <h3 style={{ marginTop: 24 }}>分镜表（剧本 #{scriptId}，提交将整体替换现有分镜）</h3>
          <table>
            <thead>
              <tr>
                <th>镜号</th><th>场景</th><th>画面描述</th>
                <th>正面 Prompt (image_prompt)</th><th>负面 Prompt (negative_prompt)</th>
                <th>动作提示词</th>
                <th>时长(s)</th><th>运镜</th><th>景别</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {shots.length === 0 && <tr><td colSpan={10} className="muted">该剧本暂无分镜，可用「AI 生成分镜」或手动添加。</td></tr>}
              {shots.map((s, i) => (
                <tr key={i}>
                  <td><input type="number" style={{ width: 52 }} value={s.shot_no} onChange={e => patch(i, 'shot_no', Number(e.target.value))} /></td>
                  <td><input value={s.scene} onChange={e => patch(i, 'scene', e.target.value)} /></td>
                  <td><input value={s.description} onChange={e => patch(i, 'description', e.target.value)} /></td>
                  <td><input value={s.image_prompt} onChange={e => patch(i, 'image_prompt', e.target.value)} placeholder="文生图正提示词（CSV 导入）" /></td>
                  <td><input value={s.negative_prompt} onChange={e => patch(i, 'negative_prompt', e.target.value)} placeholder="文生图负提示词（CSV 导入）" /></td>
                  <td><input value={s.motion_prompt} onChange={e => patch(i, 'motion_prompt', e.target.value)} /></td>
                  <td><input type="number" style={{ width: 52 }} value={s.duration} onChange={e => patch(i, 'duration', Number(e.target.value))} /></td>
                  <td><input value={s.camera_movement} onChange={e => patch(i, 'camera_movement', e.target.value)} /></td>
                  <td><input value={s.shot_size} onChange={e => patch(i, 'shot_size', e.target.value)} /></td>
                  <td><button onClick={() => setShots(prev => prev.filter((_, j) => j !== i))}>删除</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
            <button onClick={() => setShots(prev => [...prev, emptyShot(prev.length + 1)])}>＋ 添加一行</button>
            <button onClick={() => setShowPaste(v => !v)}>📋 粘贴表格导入</button>
            <button disabled={busy} onClick={() => fileRef.current?.click()}>📄 上传分镜表 txt/md</button>
            <input ref={fileRef} type="file" accept=".txt,.md" style={{ display: 'none' }} onChange={onUploadTxt} />
            <button disabled={busy} onClick={() => csvRef.current?.click()}>📑 上传 CSV 提示词</button>
            <input ref={csvRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={onUploadCsv} />
            <button className="primary" disabled={busy || shots.length === 0} onClick={submitShots}>批量提交分镜</button>
          </div>

          {showPaste && (
            <div className="budget" style={{ marginTop: 10 }}>
              <h3>从 DeepSeek / Excel 粘贴分镜表</h3>
              <p className="muted" style={{ margin: '4px 0' }}>
                直接复制表格粘贴到下方，点解析填入表格。支持 Tab 分隔（DeepSeek/Excel）和 Markdown 表格（| 分隔），
                表头含：镜号 / 景别 / 时长 / 画面描述 / 台词·内心独白 / 运镜·音效提示；台词中「角色：…」会自动拆成多条。
              </p>
              <textarea rows={8} style={{ minHeight: 140 }} placeholder={'镜号\t景别\t时长\t画面描述\t台词/内心独白\t运镜/音效提示\n1\t中景\t5s\t林夏推门进入咖啡馆\t我来了。\t跟拍'}
                value={pasteText} onChange={e => setPasteText(e.target.value)} />
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button className="primary" onClick={applyPaste}>解析并填入表格</button>
                <button onClick={() => { setShowPaste(false); setPasteText('') }}>取消</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function scriptValid(s: Script) {
  return !!s.content && s.content.trim().length > 0
}
