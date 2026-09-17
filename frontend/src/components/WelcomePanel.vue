<script setup>
import { SUGGEST_GROUPS } from '../api/mock'

const emit = defineEmits(['pick'])

const CAPS = [
  { icon: '📚', title: '政策原文检索', desc: '基于向量库的语义检索，答案可溯源到具体文档' },
  { icon: '🧾', title: '材料清单生成', desc: '自动区分必备材料与可选材料，逐项标注说明' },
  { icon: '💬', title: '多轮上下文对话', desc: '支持追问与指代消解，自动裁剪超长上下文' }
]
</script>

<template>
  <div class="welcome">
    <div class="w-hero">
      <div class="w-badge">政务大模型 · RAG 检索增强</div>
      <h2>您好，我是政务办事助手</h2>
      <p>
        我可以为您解答社保、医保、公积金、户籍、市场监管等领域的办事问题，
        并生成结构化的<strong>材料清单</strong>与<strong>办理流程</strong>。
        回答严格依据政务知识库，不编造政策。
      </p>
    </div>

    <div class="caps">
      <div v-for="c in CAPS" :key="c.title" class="cap">
        <div class="cap-ic">{{ c.icon }}</div>
        <div class="cap-t">{{ c.title }}</div>
        <div class="cap-d">{{ c.desc }}</div>
      </div>
    </div>

    <div class="suggest">
      <div v-for="g in SUGGEST_GROUPS" :key="g.name" class="sg">
        <div class="sg-h">
          <span class="sg-ic">{{ g.icon }}</span>{{ g.name }}
        </div>
        <div class="sg-items">
          <button v-for="q in g.items" :key="q" class="chip" @click="emit('pick', q)">
            {{ q }}
            <svg viewBox="0 0 24 24" width="13" height="13" fill="none">
              <path d="M5 12h13M12 5l7 7-7 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  max-width: 900px;
  margin: 0 auto;
  padding: 46px 24px 24px;
  animation: fadeUp .4s ease;
}
.w-hero { text-align: center; margin-bottom: 28px; }
.w-badge {
  display: inline-block; padding: 4px 12px; border-radius: 999px;
  background: var(--brand-50); color: var(--brand);
  font-size: 12px; font-weight: 600; margin-bottom: 14px;
}
.w-hero h2 { font-size: 26px; margin: 0 0 12px; letter-spacing: .5px; }
.w-hero p {
  max-width: 620px; margin: 0 auto; color: var(--text-2);
  font-size: 14px; line-height: 1.85;
}
.w-hero strong { color: var(--text); }

.caps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 26px; }
.cap {
  background: #fff; border: 1px solid var(--line);
  border-radius: var(--radius); padding: 14px;
  box-shadow: var(--shadow-s);
}
.cap-ic { font-size: 20px; margin-bottom: 6px; }
.cap-t { font-size: 13.5px; font-weight: 700; margin-bottom: 4px; }
.cap-d { font-size: 12px; color: var(--text-3); line-height: 1.6; }

.suggest { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.sg { background: #fff; border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; }
.sg-h { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 700; color: var(--text-2); margin-bottom: 10px; }
.sg-ic { font-size: 15px; }
.sg-items { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 7px 11px; border-radius: 999px;
  border: 1px solid var(--line); background: #fbfcfe;
  font-size: 12.5px; color: var(--text-2);
  transition: .16s;
}
.chip svg { opacity: 0; width: 0; transition: .16s; }
.chip:hover {
  border-color: var(--brand-100); background: var(--brand-50);
  color: var(--brand);
}
.chip:hover svg { opacity: 1; width: 13px; }

@media (max-width: 860px) {
  .caps { grid-template-columns: 1fr; }
  .suggest { grid-template-columns: 1fr; }
}
</style>
