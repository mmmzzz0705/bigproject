<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  material: { type: Object, required: true }
})

const tab = ref('required')
const checked = ref({})

const hasRequired = computed(() => props.material.required?.length > 0)
const hasOptional = computed(() => props.material.optional?.length > 0)
const hasSteps = computed(() => props.material.steps?.length > 0)

const progress = computed(() => {
  const list = props.material.required || []
  if (!list.length) return 0
  return list.filter((_, i) => checked.value['r' + i]).length
})

function toggle(k) { checked.value[k] = !checked.value[k] }

function copyList() {
  const m = props.material
  const lines = [`【${m.title || '办事材料清单'}】`]
  if (m.department) lines.push(`受理部门：${m.department}`)
  if (m.legal_time) lines.push(`承诺时限：${m.legal_time}`)
  if (m.fee) lines.push(`收费标准：${m.fee}`)
  lines.push('')
  lines.push('一、必备材料')
  m.required?.forEach((i, n) => lines.push(`${n + 1}. ${i.name}${i.desc ? '（' + i.desc + '）' : ''}`))
  if (m.optional?.length) {
    lines.push('', '二、可选材料')
    m.optional.forEach((i, n) => lines.push(`${n + 1}. ${i.name}${i.desc ? '（' + i.desc + '）' : ''}`))
  }
  if (m.steps?.length) {
    lines.push('', '三、办理流程')
    m.steps.forEach((s, n) => lines.push(`${n + 1}. ${s}`))
  }
  navigator.clipboard?.writeText(lines.join('\n'))
}
</script>

<template>
  <div class="mat">
    <div class="mat-hd">
      <div class="mat-l">
        <span class="mat-icon">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none">
            <path d="M8 3h8l5 5v13H3V3z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
            <path d="M8 12h8M8 16h5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>
          </svg>
        </span>
        <div>
          <div class="mat-title">{{ material.title || '办事材料清单' }}</div>
          <div class="mat-sub">AI 依据知识库生成 · 请以窗口实际要求为准</div>
        </div>
      </div>
      <div class="mat-r">
        <span v-if="hasRequired" class="pill">
          已准备 {{ progress }}/{{ material.required.length }}
        </span>
        <button class="btn btn-ghost" title="复制清单" @click="copyList">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
            <path d="M9 9h10v12H9zM5 15V3h10" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
          </svg>
          复制
        </button>
      </div>
    </div>

    <div v-if="material.department || material.legal_time || material.fee || material.channel" class="meta">
      <div v-if="material.department" class="meta-i">
        <span class="mk">受理部门</span><span class="mv">{{ material.department }}</span>
      </div>
      <div v-if="material.legal_time" class="meta-i">
        <span class="mk">承诺时限</span><span class="mv">{{ material.legal_time }}</span>
      </div>
      <div v-if="material.fee" class="meta-i">
        <span class="mk">收费标准</span><span class="mv">{{ material.fee }}</span>
      </div>
      <div v-if="material.channel" class="meta-i meta-full">
        <span class="mk">办理渠道</span><span class="mv">{{ material.channel }}</span>
      </div>
    </div>

    <div v-if="hasRequired" class="bar">
      <div class="bar-in" :style="{ width: (progress / material.required.length * 100) + '%' }"></div>
    </div>

    <div class="tabs">
      <button v-if="hasRequired" class="tab" :class="{ on: tab === 'required' }" @click="tab = 'required'">
        必备材料 <b>{{ material.required.length }}</b>
      </button>
      <button v-if="hasOptional" class="tab" :class="{ on: tab === 'optional' }" @click="tab = 'optional'">
        可选材料 <b>{{ material.optional.length }}</b>
      </button>
      <button v-if="hasSteps" class="tab" :class="{ on: tab === 'steps' }" @click="tab = 'steps'">
        办理流程 <b>{{ material.steps.length }}</b>
      </button>
    </div>

    <!-- 必备材料 -->
    <div v-show="tab === 'required' && hasRequired" class="list">
      <label
        v-for="(it, i) in material.required"
        :key="'r' + i"
        class="item"
        :class="{ ck: checked['r' + i] }"
        @click.prevent="toggle('r' + i)"
      >
        <span class="cbx">
          <svg v-if="checked['r' + i]" viewBox="0 0 24 24" width="11" height="11" fill="none">
            <path d="m5 13 4 4L19 7" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <span class="it-main">
          <span class="it-name">
            {{ it.name }}
            <em v-if="it.count" class="cnt">{{ it.count }}</em>
          </span>
          <span v-if="it.desc" class="it-desc">{{ it.desc }}</span>
        </span>
      </label>
    </div>

    <!-- 可选材料 -->
    <div v-show="tab === 'optional' && hasOptional" class="list">
      <label
        v-for="(it, i) in material.optional"
        :key="'o' + i"
        class="item"
        :class="{ ck: checked['o' + i] }"
        @click.prevent="toggle('o' + i)"
      >
        <span class="cbx cbx-o">
          <svg v-if="checked['o' + i]" viewBox="0 0 24 24" width="11" height="11" fill="none">
            <path d="m5 13 4 4L19 7" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
        <span class="it-main">
          <span class="it-name">{{ it.name }}</span>
          <span v-if="it.desc" class="it-desc">{{ it.desc }}</span>
        </span>
      </label>
    </div>

    <!-- 办理流程 -->
    <div v-show="tab === 'steps' && hasSteps" class="steps">
      <div v-for="(s, i) in material.steps" :key="'s' + i" class="step">
        <span class="sn">{{ i + 1 }}</span>
        <span class="st">{{ s }}</span>
      </div>
    </div>

    <div v-if="material.tips?.length" class="tips">
      <div class="tips-h">温馨提示</div>
      <ul>
        <li v-for="(t, i) in material.tips" :key="i">{{ t }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.mat {
  margin-top: 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: #fff;
  overflow: hidden;
  box-shadow: var(--shadow-s);
  animation: fadeUp .3s ease;
}
.mat-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px;
  background: linear-gradient(90deg, #f4f8ff, #fbfcfe);
  border-bottom: 1px solid var(--line-2);
}
.mat-l { display: flex; align-items: center; gap: 9px; }
.mat-icon {
  width: 28px; height: 28px; border-radius: 8px;
  background: var(--brand); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.mat-title { font-size: 14px; font-weight: 700; }
.mat-sub { font-size: 11px; color: var(--text-3); }
.mat-r { display: flex; align-items: center; gap: 6px; }
.pill {
  font-size: 11.5px; padding: 3px 9px; border-radius: 999px;
  background: #fff; border: 1px solid var(--brand-100); color: var(--brand);
}

.meta {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; background: var(--line-2);
}
.meta-i { background: #fbfcfe; padding: 8px 14px; display: flex; gap: 8px; align-items: baseline; }
.meta-full { grid-column: 1 / -1; }
.mk { font-size: 11.5px; color: var(--text-3); flex: 0 0 58px; }
.mv { font-size: 12.5px; color: var(--text); }

.bar { height: 3px; background: var(--line-2); }
.bar-in { height: 100%; background: linear-gradient(90deg, #1a5fd0, #49a0ff); transition: width .3s ease; }

.tabs { display: flex; gap: 4px; padding: 8px 10px 0; border-bottom: 1px solid var(--line-2); }
.tab {
  border: none; background: none; padding: 6px 10px 9px;
  font-size: 12.5px; color: var(--text-3);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tab b { font-size: 11px; opacity: .7; }
.tab.on { color: var(--brand); font-weight: 700; border-bottom-color: var(--brand); }

.list { padding: 6px 8px 8px; }
.item {
  display: flex; gap: 9px; padding: 8px 8px;
  border-radius: 8px; cursor: pointer; transition: .14s;
}
.item:hover { background: var(--bg-soft); }
.cbx {
  width: 16px; height: 16px; flex: 0 0 16px; margin-top: 3px;
  border: 1.6px solid #c6cddb; border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  transition: .14s;
}
.cbx-o { border-radius: 50%; }
.item.ck .cbx { background: var(--brand); border-color: var(--brand); }
.it-main { display: flex; flex-direction: column; min-width: 0; }
.it-name { font-size: 13px; color: var(--text); }
.item.ck .it-name { color: var(--text-3); text-decoration: line-through; }
.cnt {
  font-style: normal; font-size: 10.5px; margin-left: 5px;
  background: var(--bg-soft); color: var(--text-3);
  padding: 1px 5px; border-radius: 4px;
}
.it-desc { font-size: 11.5px; color: var(--text-3); line-height: 1.6; margin-top: 1px; }

.steps { padding: 10px 14px 12px; }
.step { display: flex; gap: 9px; margin-bottom: 9px; }
.sn {
  width: 18px; height: 18px; flex: 0 0 18px; margin-top: 3px;
  border-radius: 50%; background: var(--brand-50); color: var(--brand);
  font-size: 11px; display: flex; align-items: center; justify-content: center;
  font-weight: 700;
}
.st { font-size: 13px; color: var(--text-2); }

.tips { margin: 0 10px 10px; padding: 9px 11px; background: #fff9ec; border-radius: 8px; }
.tips-h { font-size: 11.5px; font-weight: 700; color: var(--warn); margin-bottom: 3px; }
.tips ul { margin: 0; padding-left: 16px; }
.tips li { font-size: 12px; color: #8a6116; line-height: 1.7; }
</style>
