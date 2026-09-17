<script setup>
import { computed, onMounted, ref } from 'vue'
import { useCorpus } from '../composables/useCorpus'

/**
 * 工作台：知识库语料的自助维护。
 *
 * 交互上刻意做成"先选文件、再点入库"，而不是选完即传 ——
 * 入库要调用 Embedding 接口，一篇长文档可能要几十秒，
 * 让用户看清自己选了什么再触发，避免误传后只能等它跑完。
 */
const {
  docs, total, totalChunks, vectorStore, degraded,
  loading, busy, progress, notice, online,
  previewId, chunks, chunksLoading,
  load, uploadFile, addText, removeDoc, reingest, clearNotice, togglePreview, accept
} = useCorpus()

const tab = ref('file')
const fileInput = ref(null)
const picked = ref(null)
const dragging = ref(false)
const keyword = ref('')
const confirmId = ref('')
const title = ref('')
const content = ref('')
const uploadTitle = ref('')

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return docs.value
  return docs.value.filter(
    (d) => d.docName.toLowerCase().includes(k) || d.source.toLowerCase().includes(k)
  )
})

// 文件名看不出内容（qz.pdf / doc1.docx / scan001.pdf）时提醒用户补个名称，
// 否则库里的文档名会是 PDF 页眉里的一行元数据（"事项版本：4" 之类），列表里没法认。
const nameOpaque = computed(() => {
  if (!picked.value) return false
  const stem = picked.value.name.replace(/\.[^.]+$/, '')
  return !/[\u4e00-\u9fff]/.test(stem) || stem.length < 4
})

const sizeText = computed(() => {
  if (!picked.value) return ''
  const mb = picked.value.size / 1024 / 1024
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(picked.value.size / 1024))} KB`
})

onMounted(() => { load() })

function onPickFile(e) {
  picked.value = e.target.files?.[0] || null
}
function onDrop(e) {
  dragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) picked.value = f
}
function resetFile() {
  picked.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function submitUpload() {
  const ok = await uploadFile(picked.value, uploadTitle.value)
  if (ok) { resetFile(); uploadTitle.value = '' }
}

async function submitText() {
  const ok = await addText(title.value, content.value)
  if (ok) { title.value = ''; content.value = '' }
}

async function doRemove(doc) {
  confirmId.value = ''
  await removeDoc(doc)
}

const pvOpen = ref([])

function togglePv(i) {
  const s = new Set(pvOpen.value)
  if (s.has(i)) s.delete(i)
  else s.add(i)
  pvOpen.value = [...s]
}

function fmtTime(t) {
  if (!t) return '—'
  // 后端返回 "2026-09-17 16:00:00.123456"，只取到分钟
  return String(t).slice(0, 16)
}

function originLabel(d) {
  if (!d.inIndex) return '已移出'
  return d.origin === 'uploaded' ? '上传' : '内置'
}
</script>

<template>
  <div class="wb">
    <div class="wb-scroll">
      <div class="inner">
        <div class="hd">
          <div>
            <h2 class="hd-t">知识库工作台</h2>
            <p class="hd-s">上传或粘贴政务办事指南，即时纳入检索范围；不再需要的语料可随时移出。</p>
          </div>
          <button class="btn" :disabled="loading || busy" @click="load">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
              <path d="M21 12a9 9 0 1 1-3.5-7.1M21 3v5h-5" stroke="currentColor" stroke-width="1.7"
                stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            刷新
          </button>
        </div>

        <div class="stats">
          <div class="stat">
            <span class="s-k">语料总数</span>
            <span class="s-v">{{ total }}</span>
          </div>
          <div class="stat">
            <span class="s-k">文本片段</span>
            <span class="s-v">{{ totalChunks }}</span>
          </div>
          <div class="stat">
            <span class="s-k">向量库</span>
            <span class="s-v sm">{{ vectorStore || '—' }}</span>
          </div>
          <div class="stat">
            <span class="s-k">服务状态</span>
            <span class="s-v sm" :class="degraded ? 'bad' : 'good'">
              {{ !online ? '后端未连接' : degraded ? '向量库降级' : '正常' }}
            </span>
          </div>
        </div>

        <div v-if="notice" class="notice" :class="notice.type">
          <span>{{ notice.text }}</span>
          <button class="n-x" @click="clearNotice">×</button>
        </div>

        <section class="card">
          <div class="card-hd">
            <div class="tabs">
              <button class="tab" :class="{ on: tab === 'file' }" @click="tab = 'file'">上传文件</button>
              <button class="tab" :class="{ on: tab === 'text' }" @click="tab = 'text'">粘贴文本</button>
            </div>
            <span class="hint">支持 {{ accept.join(' / ') }}，单个文件 ≤ 10MB</span>
          </div>

          <div v-if="tab === 'file'" class="pane">
            <div
              class="drop"
              :class="{ over: dragging, disabled: busy }"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
              @click="!busy && fileInput.click()"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none">
                <path d="M12 16V4m0 0L8 8m4-4 4 4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
                  stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <p class="drop-t">拖拽文件到此处，或点击选择</p>
              <p class="drop-s">PDF 需含文字层，扫描件解析不出内容</p>
              <!-- 必须 .stop：input 就在 drop 区域内，它的 click 会冒泡回 drop 的
                   click 处理器，再次触发 input.click()，形成死循环 -->
              <input ref="fileInput" class="file" type="file" :accept="accept.join(',')"
                @click.stop @change="onPickFile" />
            </div>

            <div v-if="picked" class="picked">
              <span class="p-name">{{ picked.name }}</span>
              <span class="p-size">{{ sizeText }}</span>
              <button class="btn btn-ghost" :disabled="busy" @click="resetFile">移除</button>
            </div>

            <label v-if="picked" class="fld">
              <span class="f-k">语料名称</span>
              <input v-model="uploadTitle" class="ipt" type="text" maxlength="120"
                :class="{ warn: nameOpaque && !uploadTitle }"
                placeholder="可选：文件名看不出内容时填一个（如：残疾人证办理指南）" />
            </label>
            <p v-if="picked && nameOpaque && !uploadTitle" class="warn-t">
              文件名「{{ picked.name }}」看不出内容，建议填写语料名称，否则会取 PDF 首页的一行文字当标题。
            </p>

            <div v-if="busy && progress" class="prog">
              <div class="prog-bar" :style="{ width: progress + '%' }"></div>
            </div>

            <div class="acts">
              <button class="btn btn-primary" :disabled="!picked || busy" @click="submitUpload">
                {{ busy ? '入库中…' : '开始入库' }}
              </button>
              <span v-if="busy" class="tip">正在切分并向量化，请稍候</span>
            </div>
          </div>

          <div v-else class="pane">
            <label class="fld">
              <span class="f-k">语料标题</span>
              <input v-model="title" class="ipt" type="text" maxlength="120"
                placeholder="例：住房公积金租房提取办事指南" />
            </label>
            <label class="fld">
              <span class="f-k">正文内容</span>
              <textarea v-model="content" class="ipt area" rows="9"
                placeholder="粘贴办事指南全文（受理范围 / 材料清单 / 办理流程…），至少 20 字"></textarea>
            </label>
            <div class="acts">
              <span class="tip">{{ content.length }} 字</span>
              <button class="btn btn-primary" :disabled="busy || !title || !content" @click="submitText">
                {{ busy ? '入库中…' : '加入知识库' }}
              </button>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-hd">
            <div class="tabs"><span class="sec-t">语料列表</span></div>
            <input v-model="keyword" class="ipt search" type="text" placeholder="搜索名称 / 文件名" />
          </div>

          <div v-if="loading && !docs.length" class="empty">加载中…</div>
          <div v-else-if="!filtered.length" class="empty">
            {{ docs.length ? '没有匹配的语料' : '知识库还没有语料，先上传一篇试试' }}
          </div>

          <table v-else class="tbl">
            <thead>
              <tr>
                <th>语料名称</th>
                <th class="c">来源</th>
                <th class="c">片段</th>
                <th class="c">入库时间</th>
                <th class="r">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="d in filtered" :key="d.docId">
                <tr :class="{ off: !d.inIndex, open: previewId === d.docId }">
                  <td>
                    <div class="d-name" :title="d.source">{{ d.docName }}</div>
                    <div class="d-src">{{ d.source }}</div>
                  </td>
                  <td class="c">
                    <span class="tag" :class="{
                      'tag-brand': d.origin === 'uploaded' && d.inIndex,
                      'tag-warn': !d.inIndex
                    }">{{ originLabel(d) }}</span>
                  </td>
                  <td class="c">{{ d.chunks }}</td>
                  <td class="c time">{{ fmtTime(d.uploadTime) }}</td>
                  <td class="r">
                    <div v-if="confirmId === d.docId" class="confirm">
                      <span class="c-txt">确认移出？</span>
                      <button class="btn danger" :disabled="busy" @click="doRemove(d)">确认</button>
                      <button class="btn btn-ghost" :disabled="busy" @click="confirmId = ''">取消</button>
                    </div>
                    <div v-else class="ops">
                      <button v-if="d.inIndex" class="btn btn-ghost" :disabled="busy"
                        @click="togglePreview(d)">
                        {{ previewId === d.docId ? '收起片段' : '看切分' }}
                      </button>
                      <button v-if="d.canReingest" class="btn btn-ghost" :disabled="busy"
                        @click="reingest(d)">重新导入</button>
                      <button v-if="d.inIndex" class="btn btn-ghost del" :disabled="busy"
                        @click="confirmId = d.docId">移出知识库</button>
                    </div>
                  </td>
                </tr>

                <tr v-if="previewId === d.docId" class="pv-row">
                  <td colspan="5">
                    <div v-if="chunksLoading" class="pv-empty">加载中…</div>
                    <div v-else-if="!chunks.length" class="pv-empty">没有读到片段</div>
                    <div v-else class="pv-list">
                      <div v-for="c in chunks" :key="c.index" class="pv-item">
                        <div class="pv-head">
                          <span class="pv-idx">#{{ c.index }}</span>
                          <span class="pv-sec">{{ c.section || '（无章节名）' }}</span>
                          <span class="pv-chars">{{ c.chars }} 字</span>
                        </div>
                        <div class="pv-text" :class="{ clamp: !pvOpen.includes(c.index) }"
                          @click="togglePv(c.index)">{{ c.text }}</div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <ul class="foot-tip">
            <li>内置语料（GD 系列办事指南）移出后源文件仍保留，可一键重新导入；用户上传的语料删除后不可恢复。</li>
            <li>新增语料若含全新事项名，需同步 <code>rag.py::ENTITY_HINTS</code>，否则相关问题会被判成"没说清办什么"而走候选引导。</li>
            <li>批量增删语料会改变相关性分分布，建议跑 <code>scripts/calibrate_gate.py</code> 与
              <code>scripts/probe_gate.py</code> 复核 <code>VECTOR_MIN_SCORE</code> 等闸门阈值。</li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wb { flex: 1; min-width: 0; display: flex; flex-direction: column; position: relative; }
.wb-scroll { flex: 1; overflow-y: auto; }
.inner { max-width: 1080px; margin: 0 auto; padding: 22px 24px 40px; }

.hd { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.hd-t { margin: 0 0 4px; font-size: 17px; font-weight: 700; letter-spacing: .3px; }
.hd-s { margin: 0; font-size: 12.5px; color: var(--text-3); }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 16px 0; }
.stat {
  background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 12px 14px; display: flex; flex-direction: column; gap: 2px;
}
.s-k { font-size: 11.5px; color: var(--text-3); }
.s-v { font-size: 19px; font-weight: 700; letter-spacing: .3px; }
.s-v.sm { font-size: 13.5px; font-weight: 600; }
.s-v.good { color: var(--ok); }
.s-v.bad { color: var(--danger); }

.notice {
  display: flex; align-items: center; gap: 8px; margin-bottom: 14px;
  padding: 9px 12px; border-radius: var(--radius-s); font-size: 13px;
}
.notice.ok { background: #eefaf2; border: 1px solid #cbead7; color: #17734a; }
.notice.err { background: #fdecec; border: 1px solid #f6cdd0; color: var(--danger); }
.n-x { margin-left: auto; border: none; background: none; font-size: 17px; line-height: 1; color: inherit; opacity: .7; }

.card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 14px 16px 16px; margin-bottom: 16px;
}
.card-hd {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 12px;
}
.tabs { display: flex; gap: 6px; }
.tab {
  height: 30px; padding: 0 14px; border: 1px solid transparent; background: transparent;
  border-radius: 8px; font-size: 13px; color: var(--text-2); transition: .16s;
}
.tab:hover { background: var(--bg-soft); }
.tab.on { background: var(--brand-50); color: var(--brand); font-weight: 600; }
.sec-t { font-size: 13.5px; font-weight: 600; padding-left: 2px; }
.hint { font-size: 11.5px; color: var(--text-3); }

.pane { display: flex; flex-direction: column; gap: 12px; }
.drop {
  border: 1.5px dashed var(--brand-100); border-radius: var(--radius);
  background: #fbfdff; padding: 26px 16px; text-align: center; color: var(--brand);
  transition: .16s; cursor: pointer;
}
.drop:hover { background: var(--brand-50); }
.drop.over { border-color: var(--brand); background: var(--brand-50); }
.drop.disabled { opacity: .55; cursor: not-allowed; }
.drop-t { margin: 8px 0 2px; font-size: 13.5px; font-weight: 600; color: var(--text); }
.drop-s { margin: 0; font-size: 11.5px; color: var(--text-3); }
.file { display: none; }

.picked {
  display: flex; align-items: center; gap: 8px; font-size: 13px;
  background: var(--bg-soft); border-radius: var(--radius-s); padding: 7px 10px;
}
.p-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.p-size { color: var(--text-3); font-size: 12px; }

.prog { height: 4px; background: var(--bg-soft); border-radius: 4px; overflow: hidden; }
.prog-bar { height: 100%; background: var(--brand); transition: width .2s; }

.acts { display: flex; align-items: center; gap: 10px; }
.tip { font-size: 12px; color: var(--text-3); }
.acts .btn-primary { margin-left: auto; }

.fld { display: flex; gap: 8px; align-items: flex-start; }
.f-k { width: 62px; flex: 0 0 62px; font-size: 13px; color: var(--text-2); line-height: 34px; }
.ipt {
  flex: 1; min-width: 0; height: 34px; padding: 0 10px;
  border: 1px solid var(--line); border-radius: var(--radius-s);
  font-size: 13px; color: var(--text); background: #fff; outline: none; font-family: inherit;
}
.ipt:focus { border-color: var(--brand); }
.ipt.warn { border-color: var(--warn); background: #fffaf0; }
.warn-t {
  margin: -4px 0 0 70px; font-size: 11.5px; color: var(--warn); line-height: 1.6;
}
.ipt.area { height: auto; padding: 9px 10px; line-height: 1.7; resize: vertical; }
.search { flex: 0 0 210px; height: 30px; }

.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th {
  text-align: left; font-size: 11.5px; font-weight: 600; color: var(--text-3);
  padding: 6px 8px; border-bottom: 1px solid var(--line);
}
.tbl td { padding: 10px 8px; border-bottom: 1px solid var(--line-2); vertical-align: middle; }
.tbl tr:last-child td { border-bottom: none; }
.tbl tr.off { opacity: .62; }
.c { text-align: center; }
.r { text-align: right; white-space: nowrap; }
.d-name { font-size: 13.5px; font-weight: 600; }
.d-src { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.time { font-size: 12px; color: var(--text-2); }

.ops { display: inline-flex; gap: 2px; }
.confirm { display: inline-flex; align-items: center; gap: 6px; }
.c-txt { font-size: 12px; color: var(--danger); }
.btn.danger { background: var(--danger); border-color: var(--danger); color: #fff; height: 28px; }
.btn.danger:hover { background: #b91c1c; color: #fff; }
.del { color: var(--danger); }
.del:hover { background: #fdecec; }

.empty { padding: 26px 0; text-align: center; font-size: 13px; color: var(--text-3); }

/* ---- 切分预览 ---- */
.tbl tr.open { background: var(--brand-50); }
.pv-row td { background: var(--side-2); padding: 0 8px 12px; }
.pv-empty { padding: 14px 4px; font-size: 12px; color: var(--text-3); }
.pv-list { display: flex; flex-direction: column; gap: 8px; padding: 10px 4px 2px; }
.pv-item {
  background: #fff; border: 1px solid var(--line);
  border-radius: var(--radius-s); padding: 8px 10px;
}
.pv-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.pv-idx {
  font-size: 11px; font-weight: 700; color: var(--brand);
  background: var(--brand-50); border-radius: 5px; padding: 1px 6px;
}
.pv-sec { font-size: 12px; font-weight: 600; color: var(--text-2); }
.pv-chars { margin-left: auto; font-size: 11px; color: var(--text-3); }
.pv-text {
  font-size: 12.5px; line-height: 1.7; color: var(--text-2);
  white-space: pre-wrap; word-break: break-word; cursor: pointer;
}
.pv-text.clamp {
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden;
}
.pv-text:hover { color: var(--text); }
.foot-tip {
  margin: 14px 0 0; font-size: 11.5px; color: var(--text-3); line-height: 1.75;
  border-top: 1px solid var(--line-2); padding: 10px 0 0 18px;
}
.foot-tip li { margin: 2px 0; }
.foot-tip code {
  background: #f1f4f9; border: 1px solid var(--line-2); border-radius: 5px;
  padding: 1px 4px; font-size: 11px;
}
</style>
