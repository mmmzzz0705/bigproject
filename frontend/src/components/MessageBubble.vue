<script setup>
import { computed } from 'vue'
import { renderMarkdown } from '../utils/format'
import ThinkingSteps from './ThinkingSteps.vue'
import MaterialList from './MaterialList.vue'
import SourceRefs from './SourceRefs.vue'

const props = defineProps({
  msg: { type: Object, required: true }
})
const emit = defineEmits(['regenerate', 'feedback'])

const html = computed(() => renderMarkdown(props.msg.content))
const isStreaming = computed(() => props.msg.status === 'streaming')
const isError = computed(() => props.msg.status === 'error')
const showThinking = computed(
  () => props.msg.role === 'assistant' && props.msg.thinking && props.msg.status !== 'done'
)

function copy() {
  navigator.clipboard?.writeText(props.msg.content)
  props.msg.copied = true
  setTimeout(() => (props.msg.copied = false), 1500)
}
</script>

<template>
  <div class="row" :class="msg.role">
    <!-- 助手消息 -->
    <template v-if="msg.role === 'assistant'">
      <div class="ava ai">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
          <path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="col">
        <div class="bub ai" :class="{ err: isError }">
          <ThinkingSteps
            v-if="showThinking"
            :steps="msg.thinking.steps"
            :done="msg.status === 'streaming'"
            :elapsed="msg.elapsed"
          />

          <div v-if="msg.content" class="md-body" v-html="html"></div>
          <span v-if="isStreaming" class="caret"></span>

          <div v-if="!msg.content && msg.status === 'thinking'" class="dots">
            <i></i><i></i><i></i>
          </div>

          <MaterialList v-if="msg.material && msg.status === 'done'" :material="msg.material" />
          <SourceRefs v-if="msg.status === 'done'" :sources="msg.sources" />
        </div>

        <div v-if="msg.status === 'done' && msg.content" class="acts">
          <span class="tm">{{ msg.time }}</span>
          <button class="ab" title="复制" @click="copy">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M9 9h10v12H9zM5 15V3h10" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
            </svg>
            {{ msg.copied ? '已复制' : '复制' }}
          </button>
          <button class="ab" title="重新生成" @click="emit('regenerate', msg.id)">
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 5v3.5h3.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M4 13a8 8 0 0 0 13.7 4.7L20 15.5M20 19v-3.5h-3.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            重新生成
          </button>
          <button
            class="ab" :class="{ on: msg.feedback === 'up' }"
            title="有帮助" @click="emit('feedback', { msg, value: 'up' })"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M7 10v11H4V10h3zM7 10l4.5-8a2.5 2.5 0 0 1 2.3 3.5L13 10h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 16.8 21H7" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
          </button>
          <button
            class="ab" :class="{ on: msg.feedback === 'down' }"
            title="没帮助" @click="emit('feedback', { msg, value: 'down' })"
          >
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M7 14V3H4v11h3zM7 14l4.5 8a2.5 2.5 0 0 0 2.3-3.5L13 14H8" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </div>
    </template>

    <!-- 用户消息 -->
    <template v-else>
      <div class="col user">
        <div class="bub user">{{ msg.content }}</div>
        <div class="acts user-acts"><span class="tm">{{ msg.time }}</span></div>
      </div>
      <div class="ava me">我</div>
    </template>
  </div>
</template>

<style scoped>
.row { display: flex; gap: 10px; margin-bottom: 22px; animation: fadeUp .28s ease; }
.row.user { flex-direction: row; }

.ava {
  width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
}
.ava.ai {
  background: linear-gradient(135deg, #1a5fd0, #4390f5);
  box-shadow: 0 3px 10px rgba(26, 95, 208, .25);
}
.ava.me { background: #eef1f6; color: var(--text-2); border: 1px solid var(--line); }

.col { min-width: 0; max-width: 100%; flex: 1; }
.col.user { display: flex; flex-direction: column; align-items: flex-end; }

.bub {
  display: inline-block;
  max-width: 100%;
  padding: 12px 15px;
  border-radius: 4px 14px 14px 14px;
  font-size: 14px;
  line-height: 1.8;
}
.bub.ai {
  background: #fff;
  border: 1px solid var(--line);
  box-shadow: var(--shadow-s);
  width: 100%;
}
.bub.ai.err {
  border-color: #f6cdcd; background: #fff8f8; color: #a33838; white-space: pre-wrap;
}
.bub.user {
  background: var(--brand);
  color: #fff;
  border-radius: 14px 4px 14px 14px;
  box-shadow: 0 4px 14px rgba(26, 95, 208, .22);
  white-space: pre-wrap;
  word-break: break-word;
}

.caret {
  display: inline-block; width: 2px; height: 15px;
  background: var(--brand); vertical-align: -2px; margin-left: 2px;
  animation: blink 1s infinite;
}
.dots { display: flex; gap: 4px; padding: 2px 0; }
.dots i { width: 6px; height: 6px; border-radius: 50%; background: var(--brand); animation: dotJump 1.2s infinite; }
.dots i:nth-child(2) { animation-delay: .18s; }
.dots i:nth-child(3) { animation-delay: .36s; }

.acts { display: flex; align-items: center; gap: 2px; margin-top: 7px; }
.user-acts { justify-content: flex-end; }
.tm { font-size: 11px; color: var(--text-3); margin-right: 4px; }
.ab {
  display: inline-flex; align-items: center; gap: 4px;
  height: 26px; padding: 0 7px; border: none; background: none;
  border-radius: 6px; color: var(--text-3); font-size: 11.5px;
  transition: .14s;
}
.ab:hover { background: var(--bg-soft); color: var(--text-2); }
.ab.on { color: var(--brand); background: var(--brand-50); }
</style>
