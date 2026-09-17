# 政明白（GovRAG）—— 前端展示层（Vue 3 + Vite + Nginx）

基于 **Vue 3 + Vite** 的 Web 对话页面，负责接收用户输入、调用后端 REST API、渲染 AI 回答与结构化办事材料清单。

## 一、技术栈

| 项 | 选型 | 说明 |
| --- | --- | --- |
| 框架 | Vue 3（`<script setup>` 组合式 API） | 组件化、响应式 |
| 构建 | Vite 5 | 开发热更新、生产打包 |
| HTTP | Axios | 统一封装、超时与中断控制 |
| 渲染 | marked + DOMPurify | Markdown 渲染 + XSS 过滤 |

## 二、目录结构

```
frontend/
├─ index.html
├─ vite.config.js            # /api 代理到 FastAPI (127.0.0.1:8000)
├─ src/
│  ├─ main.js
│  ├─ App.vue                # 整体布局（侧边栏 + 头部 + 会话区 + 输入区）
│  ├─ api/
│  │  ├─ index.js            # 后端接口封装（会话/问答/历史）
│  │  └─ mock.js             # 离线演示知识库（后端不可用时兜底）
│  ├─ composables/
│  │  └─ useChat.js          # 会话状态、发送流程、链路动画、打字机输出
│  ├─ components/
│  │  ├─ SideBar.vue         # 会话列表、新建/切换/删除、服务状态
│  │  ├─ AppHeader.vue       # 标题、服务状态、会话 ID、清空对话
│  │  ├─ WelcomePanel.vue    # 首屏欢迎页、能力卡片、分类推荐问题
│  │  ├─ MessageBubble.vue   # 消息气泡（流式光标、复制、重新生成、点赞）
│  │  ├─ ThinkingSteps.vue   # 智能体执行链路（意图识别→向量检索→生成）
│  │  ├─ MaterialList.vue    # 结构化材料清单（必备/可选/流程 + 勾选进度）
│  │  ├─ SourceRefs.vue      # 参考依据与相似度打分，答案可溯源
│  │  └─ Composer.vue        # 输入框（Enter 发送、停止生成、快捷问题）
│  └─ utils/format.js        # Markdown 渲染、材料清单归一化、时间工具
```

## 三、接口对接

| 接口 | 方法 | 请求 | 返回 |
| --- | --- | --- | --- |
| `/api/session/create` | POST | — | `{ "session_id": "xxx" }` |
| `/api/chat` | POST | `{ "session_id": "xxx", "question": "..." }` | `{ "answer": "...", "material_list": {...} }` |
| `/api/chat/history` | GET | `?session_id=xxx` | 历史问答记录数组 |

`material_list` 推荐返回结构（前端已做归一化，字符串 / JSON / 对象均可兼容）：

```json
{
  "title": "社会保障卡首次申领",
  "department": "市人社局 · 社保卡服务中心",
  "legal_time": "1 个工作日",
  "fee": "首次申领免费",
  "channel": "社保经办大厅 / 政务服务网",
  "required": [{ "name": "居民身份证原件", "desc": "正反面复印", "count": "1 份" }],
  "optional": [{ "name": "代办人身份证", "desc": "委托代办时提供" }],
  "steps": ["提交材料", "核验身份", "即时制卡"],
  "tips": ["未满 16 周岁需监护人代办"]
}
```

建议在返回体中追加 `sources: [{ doc_name, snippet, score }]`，前端会自动渲染"参考依据"卡片。

## 四、启动

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # 产出 dist/，静态部署
npm run preview    # 本地预览构建产物
```

- 后端默认地址 `http://127.0.0.1:8000`，可在 `vite.config.js` 的 proxy 中修改。
- 后端未启动时，页面自动降级为**本地演示数据**（顶部黄色提示条），可完整演示问答与材料清单链路。
- 关闭降级：`.env.development` 中设置 `VITE_ENABLE_MOCK=false`。

## 五、交互特性

- **智能体式执行链路**：提问后展示"加载上下文 → 意图识别 → 问题向量化 → 向量库检索 → 片段重排 → 大模型生成"的进度，检索完成标注 `Top-K=4`。
- **流式打字机输出**：后端返回后逐字渲染，支持随时点"停止"。
- **结构化材料清单**：必备/可选/流程三页签，材料可勾选并显示"已准备 x/y"进度，支持一键复制。
- **答案可溯源**：展示命中的政策文档、原文片段与相似度得分。
- **多会话管理**：会话列表本地持久化，可新建、切换、删除、清空。
- **容错与安全**：60s 超时、请求中断、超长输入截断、控制字符过滤、Markdown XSS 过滤、检索无结果时提示线下窗口。
