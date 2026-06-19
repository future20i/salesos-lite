# SalesOS Lite 3A 级收件箱前端 — 实现计划

> **For Hermes:** 纯前端项目，无 TDD。使用 curl + browser snapshot 验证。CSS 设计系统和布局由主 Agent 执行，JS 交互逻辑可委托子 Agent。

**目标:** 将 `static/index.html` 替换为 3A 级设计系统（Geist + shadow-as-border + 8 态覆盖），对接 M1 API。

**架构:** 单文件 SPA — HTML 结构 + CSS 变量系统 + Vanilla JS。Geist CDN 字体。无框架，无构建步骤。

**API 对接:**
- `POST /api/auth/login` → JWT
- `GET /api/auth/me` → 会话恢复
- `GET /api/inbox/leads` → 线索列表
- `GET /api/inbox/leads/{id}` → 线索详情 + 消息
- `POST /api/inbox/leads/{id}/reply` → 发送回复
- `GET /api/inbox/stream` → SSE 实时推送

**服务端口:** `uvicorn src.app:app --host 0.0.0.0 --port 8001`

---

## Phase 1: HTML 结构 + CSS 设计系统

### Task 1: 创建 HTML 骨架

**目标:** 建立 DOCTYPE、meta、Geist 字体 CDN、导航/侧栏/对话/面板四区 DOM 结构

**文件:**
- 覆写: `static/index.html`

**步骤:**

**Step 1: 写入完整 HTML 结构**

创建包含以下区域但无 CSS 样式的骨架：
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>SalesOS Lite</title>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
</head>
<body>
  <!-- Login overlay -->
  <div id="login-overlay">...</div>
  <!-- App container -->
  <div id="app" class="hidden">
    <nav id="nav">...</nav>
    <aside id="sidebar">...</aside>
    <main id="main">...</main>
  </div>
</body>
</html>
```

**Step 2: 检查文件存在并验证结构**

```bash
grep -c 'id="nav"\|id="sidebar"\|id="main"\|id="login-overlay"' static/index.html
```
期望: `4`

**Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat: add 3A-grade HTML skeleton with four-zone layout"
```

---

### Task 2: 写入完整 CSS 设计系统

**目标:** 将所有 3A 级 token 写入 `<style>` 标签 — 颜色、阴影、字体、间距、圆角、动效、组件样式

**文件:**
- 修改: `static/index.html`（在 `<style>` 中追加）

**步骤:**

**Step 1: 写入 CSS 变量层**

从 DESIGN.md 复制完整 token 集：
```css
:root {
  --bg-root: #fafafa;
  --bg-surface: #ffffff;
  --bg-subtle: #f5f5f5;
  --bg-hover: rgba(0,0,0,0.03);
  --bg-active: rgba(0,0,0,0.05);
  --text-primary: #171717;
  --text-secondary: #4d4d4d;
  --text-tertiary: #808080;
  --text-quaternary: #a3a3a3;
  --text-disabled: #d4d4d4;
  --accent: #6c5ce7;
  --accent-hover: #5a4bd1;
  --accent-soft: rgba(108,92,231,0.06);
  --whatsapp: #25D366;
  --email: #5B9CF5;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --shadow-border: 0 0 0 1px rgba(0,0,0,0.06);
  --shadow-card: 0 0 0 1px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-elevated: 0 0 0 1px rgba(0,0,0,0.06), 0 2px 8px rgba(0,0,0,0.06), 0 0 0 1px #fafafa inset;
  --shadow-focus: 0 0 0 2px rgba(108,92,231,0.4);
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 24px; --space-6: 32px; --space-7: 48px;
  --radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px; --radius-xl: 16px; --radius-pill: 9999px;
  --font-sans: 'Geist', system-ui, -apple-system, sans-serif;
  --font-mono: 'Geist Mono', ui-monospace, SFMono-Regular, monospace;
  --ease-out: cubic-bezier(0.16,1,0.3,1);
  --duration-fast: 150ms;
  --duration-normal: 200ms;
  --duration-slow: 300ms;
}
```

**Step 2: 写入基础样式**

body font-family + antialiased + liga，scrollbar 样式，reset

**Step 3: 写入布局样式**

```css
#app { display: flex; height: 100vh; overflow: hidden; }
#nav { width: 52px; /* ... */ }
#sidebar { width: 280px; /* ... */ }
#main { flex: 1; /* ... */ }
```

**Step 4: 写入组件样式**

导航图标、对话列表项、消息气泡、AI 卡片、回复框、客户面板、模式开关 — 每个组件的 8 态样式

**Step 5: 验证 CSS 变量存在**

```bash
grep -c '\-\-accent:' static/index.html
grep -c '\-\-shadow-border:' static/index.html
grep -c '\-\-font-sans:' static/index.html
```
期望: 每条 `>= 1`

**Step 6: Commit**

```bash
git add static/index.html
git commit -m "style: add 3A-grade CSS design system (Geist, shadow-as-border, 8-state coverage)"
```

---

### Task 3: 填充登录界面 DOM + 样式

**目标:** 登录遮罩层 — 品牌 Logo、用户名/密码输入框、登录按钮、错误提示、测试账号提示

**文件:**
- 修改: `static/index.html`

**验证:**

```bash
curl -s http://localhost:8001/static/index.html | grep -c 'login-overlay\|login-user\|login-pass\|doLogin'
```
期望: `>= 4`

---

### Task 4: 填充导航栏 DOM

**目标:** 52px 图标导航 — 品牌 Logo（渐变紫）、收件箱（active 态）、联系人、数据、设置

**验证:**

```bash
curl -s http://localhost:8001/static/index.html | grep -c 'nav-brand\|nav-icon'
```
期望: `>= 5`

---

### Task 5: 填充侧栏 DOM — 搜索 + 筛选 + 对话列表

**目标:** 搜索框 + 筛选 Tabs + 对话列表容器（动态渲染 by JS）

**验证:**

```bash
curl -s http://localhost:8001/static/index.html | grep -c 'search-input\|filter-tab\|conv-list'
```
期望: `>= 3`

---

### Task 6: 填充对话区 DOM

**目标:** 对话头部（头像 + 客户名 + 模式开关）+ 消息容器 + AI 建议卡片（隐藏）+ 回复框

**验证:**

```bash
curl -s http://localhost:8001/static/index.html | grep -c 'chat-header\|messages-wrap\|reply-input\|mode-switch'
```
期望: `>= 4`

---

### Task 7: 填充客户面板 DOM

**目标:** 客户信息区 + 线索属性 + 操作按钮 + 活动时间线

**验证:**

```bash
curl -s http://localhost:8001/static/index.html | grep -c 'customer-panel\|panel-section\|timeline'
```
期望: `>= 3`

---

### Task 8: 端到端静态 HTML 验证

**目标:** 确认无 JS 时页面结构完整、CSS 变量正确定义、所有区域可见

**验证:**

```bash
# 启动服务
cd /root/workspace/salesos-lite && .venv/bin/python -m uvicorn src.app:app --host 0.0.0.0 --port 8001 &
# 检查页面可访问
curl -s http://localhost:8001/static/index.html | head -c 100
# 检查 CSS token 存在
curl -s http://localhost:8001/static/index.html | grep -c -- '--accent'
# 检查 DOM 区域
curl -s http://localhost:8001/static/index.html | grep -c 'id="nav"\|id="sidebar"\|id="main"\|id="login-overlay"'
```
期望: 页面返回 HTML, token >= 1, DOM >= 4

---

## Phase 2: 认证逻辑

### Task 9: 写入 API 工具函数

**目标:** `api()` 封装 — 自动附加 JWT、401 处理、JSON 解析

```javascript
var _tk = '';
async function api(path, opts = {}) {
  var headers = opts.headers || {};
  if (_tk) headers['Authorization'] = 'Bearer ' + _tk;
  var r = await fetch(path, { headers: Object.assign({ 'Content-Type': 'application/json' }, headers), ...opts });
  if (r.status === 401) { doLogout(); throw new Error('Unauthorized'); }
  return r;
}
```

**验证:**

```bash
grep -c 'function api(' static/index.html
```
期望: `1`

---

### Task 10: 写入登录/登出逻辑

**目标:** `doLogin()` + `doLogout()` + `tryRestore()` — JWT 管理 + localStorage 持久化 + 会话恢复

```javascript
async function doLogin() {
  var u = document.getElementById('login-user').value;
  var p = document.getElementById('login-pass').value;
  var r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: u, password: p })
  });
  var d = await r.json();
  if (r.status !== 200) {
    document.getElementById('login-error').textContent = d.detail || '登录失败';
    document.getElementById('login-error').style.display = 'block';
    return;
  }
  _tk = d.access_token;
  localStorage.setItem('salesos_lite_sess', JSON.stringify({ tk: _tk }));
  document.getElementById('login-overlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  await loadLeads();
}
```

**验证:**

```bash
# 启动后测试登录
curl -s http://localhost:8001/api/auth/login -X POST -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}'
```
期望: 返回 `{"access_token":"...","token_type":"bearer"}`

---

## Phase 3: 线索列表

### Task 11: 线索列表加载 + 渲染

**目标:** `loadLeads()` — 调用 `GET /api/inbox/leads`，渲染带渠道图标、AI 标记、未读点的对话列表

```javascript
async function loadLeads() {
  var r = await api('/api/inbox/leads');
  var data = await r.json();
  _leads = data.leads || data || [];
  renderLeadList();
}
```

**验证:**

```bash
# 先创建测试数据
curl -s http://localhost:8001/api/inbox/incoming -X POST -H 'Content-Type: application/json' \
  -d '{"source":"web","customer_name":"Test User","customer_email":"test@test.com","content":"Hello"}'
# 登录并获取 leads
TOKEN=$(curl -s http://localhost:8001/api/auth/login -X POST -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s http://localhost:8001/api/inbox/leads -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('leads',d)))"
```
期望: `>= 1`（至少有一条线索）

---

### Task 12: 线索选择 + 详情加载

**目标:** `selectLead(id)` — 高亮选中项 + 加载消息 + 渲染对话

```javascript
async function selectLead(id) {
  _activeId = id;
  var r = await api('/api/inbox/leads/' + id);
  var lead = await r.json();
  renderChat(lead);
  renderCustomerPanel(lead);
  renderLeadList(); // 更新高亮
}
```

---

## Phase 4: 对话功能

### Task 13: 消息渲染

**目标:** `renderChat(lead)` — 渲染 in/out 气泡 + 时间分割线 + 自动滚动到底部

---

### Task 14: 发送回复

**目标:** `doReply()` — POST 消息 + 清空输入框 + 刷新对话

```javascript
async function doReply() {
  var inp = document.getElementById('reply-input');
  var content = inp.value.trim();
  if (!content || !_activeId) return;
  inp.value = '';
  await api('/api/inbox/leads/' + _activeId + '/reply', {
    method: 'POST',
    body: JSON.stringify({ content: content })
  });
  await selectLead(_activeId);
}
```

**验证:**

```bash
# 用 curl 模拟发送回复
TOKEN=$(curl -s http://localhost:8001/api/auth/login -X POST -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
LEAD_ID=$(curl -s http://localhost:8001/api/inbox/leads -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['leads'][0]['id'])")
curl -s http://localhost:8001/api/inbox/leads/$LEAD_ID/reply -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"content":"测试回复"}'
```
期望: 返回 200 或 201

---

### Task 15: AI 模式开关（UI only）

**目标:** 三段式开关切换 `人工 / AI 辅助 / 托管`，更新 UI 状态（模式横幅 + 回复框 AI 按钮 + AI 建议卡片显示/隐藏）

纯前端状态切换，不调后端 API。后续迭代对接 AI pipeline。

---

## Phase 5: 客户面板

### Task 16: 客户面板动态绑定

**目标:** `renderCustomerPanel(lead)` — 从 lead 数据渲染客户信息、线索属性、状态标签

---

## Phase 6: 集成 + 打磨

### Task 17: SSE 实时推送

**目标:** 连接 `GET /api/inbox/stream`，收到新消息时自动刷新当前对话或列表

---

### Task 18: 键盘快捷键

**目标:** `Ctrl+Enter` 发送、`Esc` 关闭面板、`Cmd+K` 聚焦搜索

---

### Task 19: 错误/空/加载状态覆盖

**目标:** 每个区域补充 loading spinner、empty state 文案、error toast

---

### Task 20: 端到端验收

**目标:** 登录 → 查看列表 → 选择对话 → 发消息 → AI 模式切换 → 完整流程通过

**验证:**

```bash
# 最终验证
curl -s http://localhost:8001/static/index.html | wc -c  # > 20000 bytes
curl -s http://localhost:8001/static/index.html | grep -c 'Geist'  # >= 1
curl -s http://localhost:8001/api/health  # {"status":"healthy"}
```

---

## 执行顺序

`1 → 2 → 3 → ... → 20`（顺序依赖，不可并行）

Phases 1-3（HTML/CSS/Auth）由主 Agent 执行（视觉判断关键）。Phases 4-6（JS 逻辑）可委托子 Agent。
