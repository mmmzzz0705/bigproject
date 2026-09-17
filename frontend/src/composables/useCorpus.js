import { ref } from 'vue'
import * as api from '../api'

/**
 * 工作台语料管理：列表 / 上传 / 粘贴 / 删除 / 重新导入。
 *
 * 与 useChat 的分工：这里只管"知识库里有哪些语料"，不涉及会话与问答。
 * 所有后端错误统一收敛成 notice（{ type, text }），组件只负责渲染。
 */
const ACCEPT = ['.txt', '.md', '.markdown', '.pdf', '.docx']

export function useCorpus() {
  const docs = ref([])
  const total = ref(0)
  const totalChunks = ref(0)
  const vectorStore = ref('')
  const degraded = ref(false)

  const loading = ref(false)     // 列表加载
  const busy = ref(false)        // 入库 / 删除中（耗时可达数十秒：要调 Embedding）
  const progress = ref(0)        // 文件上传进度（0~100）
  const notice = ref(null)
  const online = ref(true)

  function msgOf(err, fallback) {
    return err?.response?.data?.detail || err?.message || fallback
  }

  function setNotice(type, text) {
    notice.value = { type, text }
  }
  function clearNotice() {
    notice.value = null
  }

  async function load() {
    loading.value = true
    try {
      const r = await api.fetchCorpus()
      docs.value = r.docs
      total.value = r.total
      totalChunks.value = r.totalChunks
      vectorStore.value = r.vectorStore
      degraded.value = r.degraded
      online.value = true
    } catch (e) {
      online.value = false
      setNotice('err', msgOf(e, '无法连接后端服务，语料管理不可用'))
    } finally {
      loading.value = false
    }
  }

  function pick(file, onProgress, title) {
    return api.uploadCorpus(file, onProgress, title)
  }

  async function uploadFile(file, title = '') {
    if (!file) return false
    const suffix = (file.name.slice(file.name.lastIndexOf('.')) || '').toLowerCase()
    if (!ACCEPT.includes(suffix)) {
      setNotice('err', `不支持的文件类型 ${suffix || '（无扩展名）'}，仅支持 ${ACCEPT.join(' / ')}`)
      return false
    }
    if (file.size > 10 * 1024 * 1024) {
      setNotice('err', `文件 ${(file.size / 1024 / 1024).toFixed(1)}MB 超过 10MB 上限`)
      return false
    }

    busy.value = true
    progress.value = 0
    clearNotice()
    try {
      const r = await pick(file, (p) => { progress.value = p }, title)
      setNotice('ok', `《${r.doc_name || file.name}》已入库，切分 ${r.chunks ?? 0} 个片段`)
      await load()
      return true
    } catch (e) {
      setNotice('err', msgOf(e, '入库失败，请稍后重试'))
      return false
    } finally {
      busy.value = false
      progress.value = 0
    }
  }

  async function addText(title, content) {
    if ((title || '').trim().length < 2) {
      setNotice('err', '语料标题至少 2 个字符')
      return false
    }
    if ((content || '').trim().length < 20) {
      setNotice('err', '正文至少 20 字，太短切不出有效片段')
      return false
    }
    busy.value = true
    clearNotice()
    try {
      const r = await api.addCorpusText(title.trim(), content.trim())
      setNotice('ok', `《${r.doc_name || title}》已入库，切分 ${r.chunks ?? 0} 个片段`)
      await load()
      return true
    } catch (e) {
      setNotice('err', msgOf(e, '入库失败，请稍后重试'))
      return false
    } finally {
      busy.value = false
    }
  }

  async function removeDoc(doc) {
    busy.value = true
    clearNotice()
    try {
      const r = await api.deleteCorpusDoc(doc.docId)
      const extra = r.recoverable ? '（源文件保留，可随时重新导入）' : ''
      setNotice('ok', `已移出知识库：${r.removed_chunks ?? 0} 个片段${extra}`)
      await load()
      return true
    } catch (e) {
      setNotice('err', msgOf(e, '删除失败，请稍后重试'))
      return false
    } finally {
      busy.value = false
    }
  }

  async function reingest(doc) {
    busy.value = true
    clearNotice()
    try {
      const r = await api.reingestCorpusDoc(doc.docId)
      setNotice('ok', `《${r.doc_name || doc.docName}》已重新入库，${r.chunks ?? 0} 个片段`)
      await load()
      return true
    } catch (e) {
      setNotice('err', msgOf(e, '重新导入失败：源文件可能已不在内置语料目录'))
      return false
    } finally {
      busy.value = false
    }
  }

  return {
    docs, total, totalChunks, vectorStore, degraded,
    loading, busy, progress, notice, online,
    load, uploadFile, addText, removeDoc, reingest, clearNotice,
    accept: ACCEPT
  }
}
