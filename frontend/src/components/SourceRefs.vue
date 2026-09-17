<script setup>
import { ref } from 'vue'

const props = defineProps({
  sources: { type: Array, default: () => [] }
})
const open = ref(false)
</script>

<template>
  <div v-if="sources.length" class="refs">
    <button class="refs-hd" @click="open = !open">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
      </svg>
      参考依据 · {{ sources.length }} 篇文档
      <span class="arrow" :class="{ up: open }">
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none">
          <path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        </svg>
      </span>
    </button>

    <div v-show="open" class="refs-body">
      <div v-for="(s, i) in sources" :key="i" class="ref">
        <div class="ref-h">
          <span class="ref-n">{{ s.doc_name }}</span>
          <span v-if="s.score" class="score">
            <i class="sbar"><b :style="{ width: Math.round(s.score * 100) + '%' }"></b></i>
            {{ s.score.toFixed(2) }}
          </span>
        </div>
        <div class="ref-s">{{ s.snippet }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.refs { margin-top: 10px; border: 1px solid var(--line-2); border-radius: 10px; overflow: hidden; }
.refs-hd {
  width: 100%; display: flex; align-items: center; gap: 6px;
  padding: 8px 11px; background: #fafbfd; border: none;
  font-size: 12.5px; color: var(--text-2); font-weight: 600;
}
.refs-hd:hover { background: var(--bg-soft); }
.arrow { margin-left: auto; display: flex; transition: .2s; }
.arrow.up { transform: rotate(180deg); }

.refs-body { padding: 4px 11px 10px; }
.ref { padding: 8px 0; border-top: 1px dashed var(--line-2); }
.ref:first-child { border-top: none; }
.ref-h { display: flex; align-items: center; gap: 8px; margin-bottom: 3px; }
.ref-n { font-size: 12.5px; font-weight: 600; color: var(--text); }
.score { margin-left: auto; display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--brand); }
.sbar { width: 44px; height: 4px; background: var(--brand-100); border-radius: 3px; overflow: hidden; display: block; }
.sbar b { display: block; height: 100%; background: var(--brand); border-radius: 3px; }
.ref-s {
  font-size: 11.5px; color: var(--text-3); line-height: 1.7;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
