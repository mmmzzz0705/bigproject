import axios from 'axios'

/**
 * 后端服务层接口封装（FastAPI）
 * ------------------------------------------------------------------
 * POST /api/session/create        创建会话 -> { session_id }
 * POST /api/chat                  问答      -> { answer, material_list }
 * GET  /api/chat/history          历史对话  -> [ ... ]
 */
const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 300000, // 推理类大模型（qwen3.x）单次可达数十秒，放宽超时
  headers: { 'Content-Type': 'application/json' }
})

// 简单输入过滤：截断超长输入、去除控制字符，规避恶意/异常提问
export function sanitizeInput(text = '') {
  return String(text)
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .trim()
    .slice(0, 1000)
}

/** 1. 创建会话：POST /api/session/create */
export async function createSession() {
  const { data } = await http.post('/api/session/create')
  return data?.session_id || data?.data?.session_id || ''
}

/** 2. 问答（核心）：POST /api/chat */
export async function chat(sessionId, question, { signal } = {}) {
  const { data } = await http.post(
    '/api/chat',
    { session_id: sessionId, question: sanitizeInput(question) },
    { signal }
  )
  return {
    answer: data?.answer ?? '',
    material_list: data?.material_list ?? null,
    sources: data?.sources ?? []
  }
}

/** 3. 查询历史对话：GET /api/chat/history?session_id=xxx */
export async function fetchHistory(sessionId) {
  const { data } = await http.get('/api/chat/history', { params: { session_id: sessionId } })
  const list = Array.isArray(data) ? data : (data?.data ?? data?.records ?? [])
  return (list || []).map((r) => ({
    question: r.question || '',
    answer: r.answer || '',
    create_time: r.create_time || r.createTime || ''
  }))
}

/** 工作台访问凭证：与后端 CORPUS_WRITE_TOKEN 对应，留空则不发送（后端也就不校验） */
const WORKBENCH_TOKEN = import.meta.env.VITE_WORKBENCH_TOKEN || ''
const corpusHeaders = () => (WORKBENCH_TOKEN ? { 'X-Workbench-Token': WORKBENCH_TOKEN } : {})

/** 4. 语料列表：GET /api/corpus */
export async function fetchCorpus() {
  const { data } = await http.get('/api/corpus', { headers: corpusHeaders() })
  return {
    total: data?.total ?? 0,
    totalChunks: data?.total_chunks ?? 0,
    vectorStore: data?.vector_store ?? '',
    degraded: !!data?.degraded,
    docs: (data?.docs ?? []).map((d) => ({
      docId: d.doc_id || '',
      docName: d.doc_name || '',
      source: d.source || '',
      chunks: Number(d.chunks || 0),
      uploadTime: d.upload_time || '',
      origin: d.origin || 'builtin',
      inIndex: d.in_index !== false,
      canReingest: !!d.can_reingest
    }))
  }
}

/** 5. 上传语料文件：POST /api/corpus/upload（multipart） */
export async function uploadCorpus(file, onProgress, title = '') {
  const form = new FormData()
  form.append('file', file)
  // 文件名常常没有语义（qz.pdf / 文档1.docx），让用户补一个显示名
  if (title) form.append('title', title)
  const { data } = await http.post('/api/corpus/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data', ...corpusHeaders() },
    onUploadProgress: (e) => {
      if (!onProgress || !e.total) return
      onProgress(Math.round((e.loaded / e.total) * 100))
    }
  })
  return data || {}
}

/** 6. 粘贴文本入库：POST /api/corpus/text */
export async function addCorpusText(title, content) {
  const { data } = await http.post('/api/corpus/text', { title, content }, { headers: corpusHeaders() })
  return data || {}
}

/** 6.5 切分预览：GET /api/corpus/{doc_id}/chunks */
export async function fetchCorpusChunks(docId, limit = 50) {
  const { data } = await http.get(`/api/corpus/${encodeURIComponent(docId)}/chunks`, {
    params: { limit },
    headers: corpusHeaders()
  })
  return {
    docName: data?.doc_name || '',
    chunks: (data?.chunks ?? []).map((c) => ({
      index: c.index ?? 0,
      section: c.section || '',
      chars: c.chars ?? 0,
      text: c.text || ''
    }))
  }
}

/** 7. 删除语料：DELETE /api/corpus/{doc_id} */
export async function deleteCorpusDoc(docId) {
  const { data } = await http.delete(
    `/api/corpus/${encodeURIComponent(docId)}`,
    { headers: corpusHeaders() }
  )
  return data || {}
}

/** 8. 重新导入内置语料：POST /api/corpus/{doc_id}/reingest */
export async function reingestCorpusDoc(docId) {
  const { data } = await http.post(
    `/api/corpus/${encodeURIComponent(docId)}/reingest`,
    null,
    { headers: corpusHeaders() }
  )
  return data || {}
}

export function isAbortError(err) {
  return axios.isCancel?.(err) || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError'
}

export default http
