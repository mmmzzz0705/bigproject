<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import SideBar from './components/SideBar.vue'
import AppHeader from './components/AppHeader.vue'
import WelcomePanel from './components/WelcomePanel.vue'
import MessageBubble from './components/MessageBubble.vue'
import Composer from './components/Composer.vue'
import Workbench from './components/Workbench.vue'
import { useChat } from './composables/useChat'

const {
  sessionId, messages, loading, mode, sessions, lastError,
  initSession, newSession, switchSession, removeSession, clearCurrent,
  send, stop, regenerate, setFeedback, scrollToBottom
} = useChat()

const composer = ref(null)
const showDemoTip = ref(true)
const view = ref('chat')          // chat | workbench

onMounted(() => { initSession() })

watch(
  () => messages.value.length,
  async () => { await nextTick(); scrollToBottom(true) }
)

function onPick(q) { send(q) }
function onFeedback({ msg, value }) { setFeedback(msg, value) }

// 侧栏点会话 / 新建对话都要回到问答视图：否则用户以为切了会话，
// 主区却还停在工作台，看不到任何变化。
function goChat(fn, arg) {
  view.value = 'chat'
  fn(arg)
}
function onNew() { goChat(newSession) }
function onSelect(sid) { goChat(switchSession, sid) }
</script>

<template>
  <div class="app-shell">
    <SideBar
      :sessions="sessions"
      :active-id="sessionId"
      :mode="mode"
      :view="view"
      @new="onNew"
      @select="onSelect"
      @remove="removeSession"
      @navigate="view = $event"
    />

    <Workbench v-if="view === 'workbench'" />

    <div v-show="view === 'chat'" class="main-col">
      <AppHeader :mode="mode" :session-id="sessionId" :msg-count="messages.length" @clear="clearCurrent" />

      <div v-if="mode === 'demo' && showDemoTip" class="tip">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none">
          <path d="M12 9v4M12 17h.01M10.3 3.9 2.4 17.5A1.9 1.9 0 0 0 4 20.4h16a1.9 1.9 0 0 0 1.6-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        后端服务未连接，当前展示本地演示数据。启动 FastAPI 服务（默认 http://127.0.0.1:8000）后将自动切换为真实 RAG 问答。
        <button class="tip-x" @click="showDemoTip = false">×</button>
      </div>

      <div id="chat-scroll" class="scroll">
        <div class="inner">
          <WelcomePanel v-if="!messages.length" @pick="onPick" />
          <MessageBubble
            v-for="m in messages"
            :key="m.id"
            :msg="m"
            @regenerate="regenerate"
            @feedback="onFeedback"
          />
        </div>
      </div>

      <Composer
        ref="composer"
        :loading="loading"
        :disabled="!sessionId"
        @send="send"
        @stop="stop"
      />
    </div>
  </div>
</template>

<style scoped>
.tip {
  display: flex; align-items: center; gap: 7px;
  margin: 10px 22px 0; padding: 8px 12px;
  background: #fff9ec; border: 1px solid #f5e3bd;
  border-radius: 10px; color: #8a6116; font-size: 12.5px;
}
.tip-x {
  margin-left: auto; border: none; background: none;
  color: #a4813a; font-size: 17px; line-height: 1; padding: 0 2px;
}

.scroll { flex: 1; overflow-y: auto; scroll-behavior: smooth; }
.inner {
  max-width: 900px;
  margin: 0 auto;
  padding: 18px 24px 8px;
  min-height: 100%;
}
</style>
