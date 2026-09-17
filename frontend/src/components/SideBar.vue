<script setup>
import { computed } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  mode: { type: String, default: 'online' },
  view: { type: String, default: 'chat' }   // chat | workbench
})
const emit = defineEmits(['new', 'select', 'remove', 'navigate'])

const today = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})

function fmt(ts) {
  const d = new Date(ts)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <aside class="side">
    <div class="side-top">
      <div class="brand">
        <div class="brand-logo">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
            <path d="M3 21h18M5 21V10l7-5 7 5v11M9 21v-6h6v6" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <div class="brand-txt">
          <div class="t1">政明白</div>
          <div class="t2">办事引导系统</div>
        </div>
      </div>

      <nav class="nav">
        <button class="nav-i" :class="{ on: view === 'chat' }" @click="emit('navigate', 'chat')">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
              stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
          </svg>
          智能问答
        </button>
        <button class="nav-i" :class="{ on: view === 'workbench' }" @click="emit('navigate', 'workbench')">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
          </svg>
          工作台
        </button>
      </nav>

      <button class="new-btn" @click="emit('new')">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
          <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        </svg>
        新建对话
      </button>
    </div>

    <div class="side-list">
      <div class="list-title">历史会话</div>
      <div v-if="!sessions.length" class="empty">暂无会话记录</div>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="s-item"
        :class="{ active: s.id === activeId }"
        @click="emit('select', s.id)"
      >
        <svg class="ic" viewBox="0 0 24 24" width="14" height="14" fill="none">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
        </svg>
        <span class="s-name">{{ s.title }}</span>
        <span class="s-time">{{ fmt(s.updatedAt) }}</span>
        <button class="del" title="删除" @click.stop="emit('remove', s.id)">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
            <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="side-foot">
      <div class="kb-card">
        <div class="kb-row">
          <span class="dot" :class="mode === 'online' ? 'on' : 'off'"></span>
          <span class="kb-k">服务状态</span>
          <span class="kb-v">{{ mode === 'online' ? '后端已连接' : '本地演示数据' }}</span>
        </div>
        <div class="kb-row">
          <span class="kb-k">知识库</span>
          <span class="kb-v">政务文档库 v2026.09</span>
        </div>
        <div class="kb-row">
          <span class="kb-k">检索策略</span>
          <span class="kb-v">向量召回 Top-K=4</span>
        </div>
      </div>
      <div class="date">{{ today }}</div>
    </div>
  </aside>
</template>

<style scoped>
.side {
  width: 262px;
  flex: 0 0 262px;
  background: var(--side);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  height: 100%;
}
.side-top { padding: 16px 14px 12px; }
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.brand-logo {
  width: 32px; height: 32px; border-radius: 9px;
  background: linear-gradient(135deg, #1a5fd0, #3f83f1);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 12px rgba(26, 95, 208, .28);
}
.brand-txt .t1 { font-size: 15px; font-weight: 700; letter-spacing: .3px; }
.brand-txt .t2 { font-size: 11px; color: var(--text-3); letter-spacing: 1px; }

.nav { display: flex; gap: 6px; margin-bottom: 12px; }
.nav-i {
  flex: 1; height: 34px;
  display: flex; align-items: center; justify-content: center; gap: 5px;
  border: 1px solid transparent; background: var(--side-2);
  border-radius: 9px; font-size: 13px; color: var(--text-2);
  transition: .16s;
}
.nav-i:hover { background: var(--bg-soft); color: var(--text); }
.nav-i.on {
  background: var(--brand-50); border-color: var(--brand-100);
  color: var(--brand); font-weight: 600;
}

.new-btn {
  width: 100%; height: 38px;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  border: 1px solid var(--brand-100);
  background: var(--brand-50);
  color: var(--brand);
  border-radius: 10px;
  font-size: 13.5px; font-weight: 600;
  transition: .16s;
}
.new-btn:hover { background: var(--brand); color: #fff; border-color: var(--brand); }

.side-list { flex: 1; overflow-y: auto; padding: 4px 10px 10px; }
.list-title {
  font-size: 11px; color: var(--text-3); letter-spacing: 1px;
  padding: 6px 6px 8px;
}
.empty { font-size: 12px; color: var(--text-3); padding: 8px 8px; }
.s-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 9px; border-radius: 9px;
  cursor: pointer; color: var(--text-2);
  transition: .14s;
}
.s-item:hover { background: var(--side-2); }
.s-item.active { background: var(--brand-50); color: var(--brand); }
.s-item .ic { flex: 0 0 auto; opacity: .8; }
.s-name {
  flex: 1; min-width: 0; font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: inherit;
}
.s-time { font-size: 10.5px; color: var(--text-3); flex: 0 0 auto; }
.s-item.active .s-time { color: var(--brand); opacity: .8; }
.del {
  flex: 0 0 auto; width: 20px; height: 20px; border: none; background: none;
  color: var(--text-3); border-radius: 5px; display: none;
  align-items: center; justify-content: center; padding: 0;
}
.s-item:hover .del { display: flex; }
.del:hover { background: #fdecec; color: var(--danger); }

.side-foot { padding: 10px 14px 14px; border-top: 1px solid var(--line-2); }
.kb-card {
  background: var(--side-2); border: 1px solid var(--line-2);
  border-radius: 10px; padding: 10px 11px; margin-bottom: 8px;
}
.kb-row { display: flex; align-items: center; font-size: 11.5px; margin: 3px 0; }
.kb-k { color: var(--text-3); width: 58px; flex: 0 0 58px; }
.kb-v { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dot { width: 7px; height: 7px; border-radius: 50%; margin-right: 4px; }
.dot.on { background: var(--ok); box-shadow: 0 0 0 3px rgba(15, 157, 88, .15); }
.dot.off { background: var(--warn); box-shadow: 0 0 0 3px rgba(217, 119, 6, .15); }
.date { font-size: 11px; color: var(--text-3); text-align: center; }
</style>
