<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['send', 'stop'])

const text = ref('')
const area = ref(null)

const QUICK = [
  '办理社保卡需要什么材料？',
  '公积金租房提取怎么办理？',
  '个体工商户营业执照怎么办？',
  '异地就医备案流程是什么？'
]

function autosize() {
  const el = area.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 150) + 'px'
}

function onInput() { autosize() }

function submit() {
  const v = text.value.trim()
  if (!v || props.loading || props.disabled) return
  emit('send', v)
  text.value = ''
  nextTick(() => autosize())
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

function useQuick(q) {
  text.value = q
  nextTick(() => { autosize(); area.value?.focus() })
}
defineExpose({ useQuick })
</script>

<template>
  <div class="composer">
    <div class="quick">
      <button v-for="q in QUICK" :key="q" class="q-chip" @click="useQuick(q)">{{ q }}</button>
    </div>

    <div class="box" :class="{ busy: loading }">
      <textarea
        ref="area"
        v-model="text"
        class="ta"
        rows="1"
        :placeholder="disabled ? '正在初始化会话…' : '请输入您的政务办事问题，例如：办理居住证需要哪些材料？'"
        :disabled="disabled"
        @input="onInput"
        @keydown="onKeydown"
      ></textarea>

      <div class="tools">
        <span class="hint">
          <kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行
        </span>
        <button v-if="loading" class="send stop" @click="emit('stop')">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
            <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>
          </svg>
          停止
        </button>
        <button v-else class="send" :disabled="!text.trim() || disabled" @click="submit">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <path d="M4 12h15M13 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          发送
        </button>
      </div>
    </div>

    <div class="disclaimer">
      回答由大语言模型基于政务知识库生成，仅供参考；具体以窗口最新政策与要求为准。
    </div>
  </div>
</template>

<style scoped>
.composer {
  flex: 0 0 auto;
  padding: 10px 22px 14px;
  background: linear-gradient(180deg, rgba(244, 247, 251, 0), var(--bg) 30%);
}
.quick { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 9px; }
.q-chip {
  padding: 5px 11px; border-radius: 999px;
  border: 1px solid var(--line); background: #fff;
  font-size: 12px; color: var(--text-2);
  box-shadow: var(--shadow-s); transition: .16s;
}
.q-chip:hover { border-color: var(--brand-100); color: var(--brand); background: var(--brand-50); }

.box {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow);
  padding: 8px 10px 6px;
  transition: .18s;
}
.box:focus-within { border-color: var(--brand-100); box-shadow: 0 8px 26px rgba(26, 95, 208, .13); }
.box.busy { border-color: var(--brand-100); }

.ta {
  width: 100%; border: none; outline: none; resize: none;
  font-family: inherit; font-size: 14px; line-height: 1.7;
  color: var(--text); background: transparent;
  max-height: 150px; padding: 4px 4px 2px;
}
.ta::placeholder { color: #a8b2c2; }

.tools { display: flex; align-items: center; justify-content: space-between; margin-top: 2px; }
.hint { font-size: 11px; color: var(--text-3); }
kbd {
  background: var(--bg-soft); border: 1px solid var(--line);
  border-radius: 4px; padding: 0 4px; font-size: 10.5px;
  font-family: inherit; color: var(--text-2);
}
.send {
  height: 32px; padding: 0 15px; border: none; border-radius: 9px;
  background: var(--brand); color: #fff;
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; transition: .16s;
}
.send:hover:not(:disabled) { background: var(--brand-600); }
.send:disabled { background: #c3cede; cursor: not-allowed; }
.send.stop { background: #fff; color: var(--danger); border: 1px solid #f3cfcf; }

.disclaimer { text-align: center; font-size: 11px; color: var(--text-3); margin-top: 8px; }
</style>
