import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

/** Markdown -> 安全 HTML */
export function renderMarkdown(text = '') {
  if (!text) return ''
  const raw = marked.parse(String(text))
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['target', 'rel'] })
}

/**
 * 材料清单归一化
 * 后端可能返回：结构化对象 / JSON 字符串 / 纯文本清单 / null
 * 统一为：{ title, department, legal_time, fee, channel, required[], optional[], steps[], tips[] }
 */
export function normalizeMaterial(raw) {
  if (!raw) return null
  let data = raw

  if (typeof data === 'string') {
    const t = data.trim()
    if (!t) return null
    if (t.startsWith('{') || t.startsWith('[')) {
      try {
        data = JSON.parse(t)
      } catch {
        return { title: '', required: parseTextList(t), optional: [], steps: [], tips: [] }
      }
    } else {
      return { title: '', required: parseTextList(t), optional: [], steps: [], tips: [] }
    }
  }

  if (!data || typeof data !== 'object') return null

  const pick = (o, keys) => {
    for (const k of keys) {
      if (o[k] !== undefined && o[k] !== null && o[k] !== '') return o[k]
    }
    return ''
  }

  const required = toItemList(data.required ?? data.必备材料 ?? data.must ?? [])
  const optional = toItemList(data.optional ?? data.可选材料 ?? data.maybe ?? [])
  const steps = toStrList(data.steps ?? data.流程 ?? data.process ?? [])
  const tips = toStrList(data.tips ?? data.温馨提示 ?? data.notes ?? [])

  if (!required.length && !optional.length && !steps.length) return null

  return {
    title: pick(data, ['title', '事项名称', 'name', '事项']),
    department: pick(data, ['department', '受理部门', 'dept']),
    legal_time: pick(data, ['legal_time', '承诺时限', 'time_limit']),
    fee: pick(data, ['fee', '收费标准', '收费']),
    channel: pick(data, ['channel', '办理渠道', '办理地点']),
    required,
    optional,
    steps,
    tips
  }
}

function toItemList(list) {
  if (!Array.isArray(list)) return []
  return list
    .map((it) => {
      if (typeof it === 'string') return { name: it, desc: '', count: '' }
      return {
        name: it.name || it.材料名称 || it.material || '',
        desc: it.desc || it.说明 || it.remark || it.description || '',
        count: it.count || it.份数 || it.num || ''
      }
    })
    .filter((it) => it.name)
}

function toStrList(list) {
  if (!Array.isArray(list)) return []
  return list
    .map((it) => (typeof it === 'string' ? it : (it?.text ?? it?.desc ?? it?.name ?? '')))
    .filter(Boolean)
}

/** 把"1. xxx\n2. xxx"或"-\nxxx"解析为条目 */
function parseTextList(text) {
  return text
    .split('\n')
    .map((l) => l.replace(/^\s*([0-9]+[.、)]|[-*•])\s*/, '').trim())
    .filter(Boolean)
    .map((name) => ({ name, desc: '', count: '' }))
}

export function fmtTime(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

export function uid(prefix = 'm') {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}
