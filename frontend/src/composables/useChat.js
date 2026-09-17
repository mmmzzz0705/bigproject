import { ref, reactive, nextTick, computed } from 'vue'
import * as api from '../api'
import { mockAnswer } from '../api/mock'
import { normalizeMaterial, uid, fmtTime } from '../utils/format'

const MOCK_ENABLED = (import.meta.env.VITE_ENABLE_MOCK ?? 'true') !== 'false'
const LS_SESSIONS = 'govqa:sessions'
const msgKey = (sid) => `govqa:messages:${sid}`

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 首屏展示的"智能体"执行链路 */
const TRACE = [
  { key: 'ctx', label: '加载会话上下文', delay: 260 },
  { key: 'intent', label: '意图识别与问题改写', delay: 320 },
  { key: 'embed', label: '问题向量化（Embedding）', delay: 380 },
  { key: 'retrieve', label: '向量库语义检索 Top-K', delay: 700 },
  { key: 'rerank', label: '片段重排与上下文裁剪', delay: 340 },
  { key: 'llm', label: '组装 Prompt 并调用大模型', delay: 520 }
]

export function useChat() {
  const sessionId = ref('')
  const messages = ref([])
  const loading = ref(false)
  const mode = ref('online') // online = 后端可用；demo = 离线演示数据
  const sessions = ref(loadSessions())
  const lastError = ref('')

  let controller = null
  let stopped = false

  const canSend = computed(() => !loading.value && !!sessionId.value)

  /* ---------------- 会话管理 ---------------- */
  function loadSessions() {
    try {
      return JSON.parse(localStorage.getItem(LS_SESSIONS) || '[]')
    } catch {
      return []
    }
  }

  function persistSessions() {
    localStorage.setItem(LS_SESSIONS, JSON.stringify(sessions.value))
  }

  function persistMessages(sid = sessionId.value) {
    if (!sid) return
    const plain = messages.value
      .filter((m) => m.status === 'done')
      .map((m) => ({
        role: m.role,
        content: m.content,
        material: m.material || null,
        sources: m.sources || [],
        time: m.time
      }))
    localStorage.setItem(msgKey(sid), JSON.stringify(plain))
  }

  function upsertSession(sid, title) {
    const idx = sessions.value.findIndex((s) => s.id === sid)
    if (idx >= 0) {
      sessions.value[idx].updatedAt = Date.now()
      if (title) sessions.value[idx].title = title
      sessions.value.unshift(sessions.value.splice(idx, 1)[0])
    } else {
      sessions.value.unshift({
        id: sid,
        title: title || '新会话',
        updatedAt: Date.now()
      })
    }
    persistSessions()
  }

  async function initSession() {
    try {
      const sid = await api.createSession()
      if (sid) {
        sessionId.value = sid
        mode.value = 'online'
        upsertSession(sid, '新会话')
        return
      }
      throw new Error('empty session_id')
    } catch (e) {
      mode.value = 'demo'
      lastError.value = '后端服务未连接，已切换为本地演示数据'
      fallbackSession()
    }
  }

  function fallbackSession() {
    sessionId.value = `local_${Date.now().toString(36)}`
    upsertSession(sessionId.value, '新会话')
  }

  async function switchSession(sid) {
    if (sid === sessionId.value) return
    stop()
    sessionId.value = sid
    // 优先读取本地缓存，保证离线可用
    let cached = []
    try {
      cached = JSON.parse(localStorage.getItem(msgKey(sid)) || '[]')
    } catch { /* ignore */ }
    messages.value = cached.map((m) => ({ ...m, id: uid(), status: 'done' }))

    if (mode.value === 'online') {
      try {
        const rows = await api.fetchHistory(sid)
        if (rows?.length) {
          const merged = []
          rows.forEach((r) => {
            merged.push({
              id: uid(), role: 'user', content: r.question,
              time: r.create_time, status: 'done', feedback: ''
            })
            merged.push({
              id: uid(), role: 'assistant', content: r.answer,
              material: normalizeMaterial(r.material_list) || null,
              sources: [], time: r.create_time, status: 'done', feedback: ''
            })
          })
          messages.value = merged
        }
      } catch { /* 保留本地缓存 */ }
    }
    await nextTick()
    scrollToBottom()
  }

  function newSession() {
    stop()
    if (mode.value === 'online') {
      api.createSession()
        .then((sid) => {
          sessionId.value = sid || `local_${Date.now().toString(36)}`
          messages.value = []
          upsertSession(sessionId.value, '新会话')
        })
        .catch(() => {
          mode.value = 'demo'
          messages.value = []
          fallbackSession()
        })
    } else {
      messages.value = []
      fallbackSession()
    }
  }

  function removeSession(sid) {
    sessions.value = sessions.value.filter((s) => s.id !== sid)
    localStorage.removeItem(msgKey(sid))
    persistSessions()
    if (sid === sessionId.value) newSession()
  }

  function clearCurrent() {
    messages.value = []
    localStorage.removeItem(msgKey(sessionId.value))
    const s = sessions.value.find((x) => x.id === sessionId.value)
    if (s) { s.title = '新会话'; persistSessions() }
  }

  /* ---------------- 发送问题 ---------------- */
  async function send(rawQuestion) {
    const question = api.sanitizeInput(rawQuestion)
    if (!question || loading.value) return

    stopped = false
    loading.value = true
    lastError.value = ''

    if (!sessionId.value) {
      mode.value === 'online' ? await initSession() : fallbackSession()
    }

    const userMsg = reactive({
      id: uid(), role: 'user', content: question,
      time: fmtTime(), status: 'done', feedback: ''
    })
    messages.value.push(userMsg)

    const aiMsg = reactive({
      id: uid(), role: 'assistant', content: '',
      material: null, sources: [], time: '', status: 'thinking',
      feedback: '', elapsed: 0,
      thinking: {
        steps: TRACE.map((s) => ({ label: s.label, status: 'wait', detail: '' })),
        expanded: true
      }
    })
    messages.value.push(aiMsg)
    await nextTick()
    scrollToBottom()

    // 首次提问时将会话标题更新为问题摘要
    if (messages.value.filter((m) => m.role === 'user').length === 1) {
      upsertSession(sessionId.value, question.length > 18 ? question.slice(0, 18) + '…' : question)
    }

    const startAt = Date.now()
    controller = new AbortController()
    let payload = null
    let usedMock = false

    // 并行：链路动画 + 真实请求
    const request = (async () => {
      try {
        return await api.chat(sessionId.value, question, { signal: controller.signal })
      } catch (err) {
        if (api.isAbortError(err)) return null
        if (MOCK_ENABLED) {
          usedMock = true
          await sleep(500)
          return mockAnswer(question)
        }
        throw err
      }
    })()

    const trace = (async () => {
      for (let i = 0; i < aiMsg.thinking.steps.length; i++) {
        if (stopped || aiMsg.status !== 'thinking') break
        aiMsg.thinking.steps[i].status = 'active'
        await sleep(TRACE[i].delay)
        if (aiMsg.status !== 'thinking') break
        aiMsg.thinking.steps[i].status = 'done'
        if (TRACE[i].key === 'retrieve') aiMsg.thinking.steps[i].detail = 'Top-K = 4'
        if (TRACE[i].key === 'llm') aiMsg.thinking.steps[i].detail = 'temperature = 0.2'
      }
    })()

    try {
      payload = await request
    } catch (err) {
      await trace
      aiMsg.status = 'error'
      aiMsg.content = '抱歉，服务暂时不可用：' + (err?.response?.data?.detail || err?.message || '未知错误') + '\n\n请稍后重试或咨询线下政务窗口。'
      loading.value = false
      controller = null
      return
    }

    await trace
    if (stopped) { loading.value = false; controller = null; return }

    if (usedMock && mode.value === 'online') {
      mode.value = 'demo'
      lastError.value = '后端服务未连接，已切换为本地演示数据'
    }

    aiMsg.thinking.steps.forEach((s) => (s.status = 'done'))
    aiMsg.elapsed = ((Date.now() - startAt) / 1000).toFixed(1)
    aiMsg.sources = payload?.sources || []
    aiMsg.material = normalizeMaterial(payload?.material_list)
    aiMsg.status = 'streaming'
    aiMsg.thinking.expanded = false
    await nextTick()

    await typeOut(aiMsg, payload?.answer || '')

    if (!stopped) {
      aiMsg.status = 'done'
      aiMsg.time = fmtTime()
    }
    loading.value = false
    controller = null
    persistMessages()
  }

  /** 打字机输出，营造流式回答体验 */
  async function typeOut(msg, text) {
    if (!text) return
    const step = text.length > 600 ? 10 : 6
    for (let i = 0; i < text.length; i += step) {
      if (stopped) break
      msg.content += text.slice(i, i + step)
      scrollToBottom(true)
      await sleep(14)
    }
    if (stopped && msg.content.length < text.length) {
      // 用户中断：补全剩余内容，避免答案残缺
      msg.content = text
    }
    msg.status = 'done'
  }

  function stop() {
    stopped = true
    controller?.abort()
    controller = null
    loading.value = false
    messages.value.forEach((m) => {
      if (m.status === 'thinking' || m.status === 'streaming') {
        m.status = 'done'
        m.time = m.time || fmtTime()
        m.thinking?.steps.forEach((s) => (s.status = 'done'))
      }
    })
    persistMessages()
  }

  function regenerate(msgId) {
    const idx = messages.value.findIndex((m) => m.id === msgId)
    if (idx < 1) return
    const question = messages.value[idx - 1]?.content
    messages.value.splice(idx)
    persistMessages()
    send(question)
  }

  function setFeedback(msg, value) {
    msg.feedback = msg.feedback === value ? '' : value
  }

  function scrollToBottom(smooth = false) {
    const el = document.getElementById('chat-scroll')
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }

  return {
    sessionId, messages, loading, mode, sessions, lastError, canSend,
    initSession, newSession, switchSession, removeSession, clearCurrent,
    send, stop, regenerate, setFeedback, scrollToBottom
  }
}
