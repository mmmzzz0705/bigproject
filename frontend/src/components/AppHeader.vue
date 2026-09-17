<script setup>
defineProps({
  mode: { type: String, default: 'online' },
  sessionId: { type: String, default: '' },
  msgCount: { type: Number, default: 0 }
})
const emit = defineEmits(['clear'])
</script>

<template>
  <header class="hdr">
    <div class="h-left">
      <h1 class="h-title">智能问答与办事引导</h1>
      <div class="h-sub">
        <span class="tag" :class="mode === 'online' ? 'tag-ok' : 'tag-warn'">
          <span class="dot" :class="mode === 'online' ? 'on' : 'off'"></span>
          {{ mode === 'online' ? 'RAG 服务在线' : '演示模式' }}
        </span>
        <span class="tag">会话 {{ sessionId ? sessionId.slice(0, 10) + '…' : '—' }}</span>
        <span class="tag">上下文 {{ msgCount }} 条</span>
      </div>
    </div>
    <div class="h-right">
      <button class="btn" @click="emit('clear')">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
          <path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
        </svg>
        清空对话
      </button>
    </div>
  </header>
</template>

<style scoped>
.hdr {
  height: 62px; flex: 0 0 62px;
  background: rgba(255, 255, 255, .92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 22px;
}
.h-title { font-size: 16px; font-weight: 700; margin: 0 0 4px; letter-spacing: .3px; }
.h-sub { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.dot { width: 6px; height: 6px; border-radius: 50%; }
.dot.on { background: var(--ok); }
.dot.off { background: var(--warn); }
</style>
