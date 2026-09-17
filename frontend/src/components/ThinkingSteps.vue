<script setup>
defineProps({
  steps: { type: Array, default: () => [] },
  done: { type: Boolean, default: false },
  elapsed: { type: [String, Number], default: '' }
})
</script>

<template>
  <div class="think">
    <div class="th-head">
      <svg v-if="!done" class="spin" viewBox="0 0 24 24" width="13" height="13" fill="none">
        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.4" opacity=".2"/>
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>
      </svg>
      <svg v-else viewBox="0 0 24 24" width="13" height="13" fill="none">
        <path d="m5 13 4 4L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span class="th-title">{{ done ? '已完成检索与生成' : '正在检索政务知识库…' }}</span>
      <span v-if="done && elapsed" class="th-time">耗时 {{ elapsed }}s</span>
    </div>

    <div class="th-steps">
      <div
        v-for="(s, i) in steps"
        :key="i"
        class="th-step"
        :class="s.status"
      >
        <span class="th-dot">
          <span v-if="s.status === 'wait'" class="d-wait"></span>
          <span v-else-if="s.status === 'active'" class="d-active"></span>
          <svg v-else viewBox="0 0 24 24" width="9" height="9" fill="none">
            <path d="m5 13 4 4L19 7" stroke="#fff" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <span class="th-label">{{ s.label }}</span>
        <span v-if="s.detail" class="tag tag-brand th-detail">{{ s.detail }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.think {
  background: #fafbfd;
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
  padding: 10px 12px;
  margin-bottom: 10px;
}
.th-head {
  display: flex; align-items: center; gap: 6px;
  font-size: 12.5px; color: var(--text-2); font-weight: 600;
  margin-bottom: 8px;
}
.spin { animation: spin .8s linear infinite; }
.th-time { margin-left: auto; font-weight: 400; color: var(--text-3); font-size: 11.5px; }

.th-steps { display: flex; flex-direction: column; gap: 6px; }
.th-step { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.th-step.wait { color: var(--text-3); }
.th-step.active { color: var(--brand); font-weight: 600; }
.th-step.done { color: var(--text-2); }

.th-dot {
  width: 14px; height: 14px; border-radius: 50%; flex: 0 0 14px;
  display: flex; align-items: center; justify-content: center;
}
.d-wait { width: 5px; height: 5px; border-radius: 50%; background: #c6cddb; }
.d-active {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid var(--brand-100);
  border-top-color: var(--brand);
  animation: spin .7s linear infinite;
}
.th-step.done .th-dot { background: var(--ok); }
.th-detail { height: 18px; font-size: 10.5px; }
</style>
