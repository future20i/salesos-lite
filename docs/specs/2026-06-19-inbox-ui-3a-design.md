# SalesOS Lite 收件箱 UI 设计规格

> ⚠️ **已废弃（2026-06-20）。** 本文件已被 `2026-06-20-spa-ai-environment-design.md` 取代。
> 布局已从旧四栏改为新设计：60px 图标导航 + AI 环境侧栏 + 管道看板。

**日期:** 2026-06-19  
**版本:** v3.0 (3A Grade)  
**状态:** superseded

---

## 设计哲学

融合三家顶级设计系统：
- **Vercel** — shadow-as-border 技术、Geist 字体、多层阴影堆叠
- **Linear** — 精确字距、半透明表面层级、510 weight 签名
- **Intercom** — 暖底色基调、scale 交互反馈、锋利几何

核心原则：**减法默认** — 每条边框、每个阴影、每像素间距必须有存在理由。

---

## 布局结构

```
┌──────┬────────────┬──────────────────────────┬──────────┐
│ Nav  │  Sidebar   │      Chat (主角)         │ Customer │
│ 52px │  280px     │     flex: 1              │  210px   │
│      │            │                          │ 可收起   │
│ 🏠   │ 搜索       │  [对话头部 + 模式开关]    │ 客户信息  │
│ 📥   │ 筛选 Tab  │                          │ 线索属性  │
│ 👤   │ 对话列表   │  [消息气泡 · AI 建议卡]   │ 操作按钮  │
│ 📊   │            │                          │ 活动时间线 │
│ ⚙️   │            │  [回复框 · AI 按钮]      │          │
└──────┴────────────┴──────────────────────────┴──────────┘
```

---

## 颜色 Token

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg-root` | `#fafafa` | 页面底色 |
| `--bg-surface` | `#ffffff` | 卡片/面板 |
| `--bg-subtle` | `#f5f5f5` | 输入框背景 |
| `--bg-hover` | `rgba(0,0,0,0.03)` | 悬停态 |
| `--bg-active` | `rgba(0,0,0,0.05)` | 按下态 |
| `--text-primary` | `#171717` | 正文 |
| `--text-secondary` | `#4d4d4d` | 辅助文字 |
| `--text-tertiary` | `#808080` | 弱化文字 |
| `--text-quaternary` | `#a3a3a3` | 占位/时间戳 |
| `--text-disabled` | `#d4d4d4` | 禁用态 |
| `--accent` | `#6c5ce7` | 品牌紫 |
| `--accent-hover` | `#5a4bd1` | 悬停加深 |
| `--accent-soft` | `rgba(108,92,231,0.06)` | 淡紫底色 |
| `--whatsapp` | `#25D366` | WhatsApp 官方绿 |
| `--email` | `#5B9CF5` | 邮件蓝 |
| `--success` | `#10b981` | 成功/在线 |
| `--warning` | `#f59e0b` | 警告/待跟进 |
| `--danger` | `#ef4444` | 危险/错误 |

---

## 阴影体系（Vercel shadow-as-border）

| 级别 | 值 | 用途 |
|------|-----|------|
| border | `0 0 0 1px rgba(0,0,0,0.06)` | 替代传统边框 |
| card | border + `0 1px 2px rgba(0,0,0,0.04)` | 标准卡片 |
| elevated | border + `0 2px 8px rgba(0,0,0,0.06)` + `inset 0 0 0 1px #fafafa` | 浮层/AI 卡片 |
| focus | `0 0 0 2px rgba(108,92,231,0.4)` | 键盘聚焦 |

**原则：** 绝不使用传统 CSS `border`，全部改为 box-shadow 实现。

---

## 字体体系

| 角色 | 字体 | 大小 | 字重 | 字距 |
|------|------|------|------|------|
| 页面标题 | Geist | 18px | 600 | -0.36px |
| 对话标题 | Geist | 15px | 600 | -0.2px |
| 列表名称 | Geist | 13px | 500 | -0.13px |
| 消息正文 | Geist | 13px | 400 | 0 |
| 辅助文字 | Geist | 12px | 400 | 0 |
| 标签/按钮 | Geist | 11-12px | 500 | 0 |
| 时间戳 | Geist | 11px | 400 | `tnum` |
| 面板标签 | Geist | 10px | 600 | 0.6px uppercase |

**CDN:** `fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Geist+Mono`

---

## 间距量表

`4 / 8 / 12 / 16 / 24 / 32 / 48`

---

## 圆角量表

`6px (sm) / 8px (md) / 12px (lg) / 16px (xl) / 9999px (pill)`

---

## 动效规范

| 属性 | 值 |
|------|-----|
| 缓动函数 | `cubic-bezier(0.16, 1, 0.3, 1)` |
| 快速 | `150ms` (hover, focus) |
| 标准 | `200ms` (切换, 展开) |
| 慢速 | `300ms` (页面过渡) |

**按钮反馈：** hover `scale(1.05)`, active `scale(0.95)`, disabled `opacity:0.4`

---

## 交互状态覆盖（每组件 8 态）

每个可交互元素必须覆盖：
- [x] Default
- [x] Hover
- [x] Active/Pressed
- [x] Focus (键盘可见)
- [x] Disabled
- [ ] Loading
- [ ] Empty
- [ ] Error

---

## 渠道图标系统

| 渠道 | 图标 | 颜色 | 标签 |
|------|------|------|------|
| WhatsApp | SVG 官方 logo (填充) | `#25D366` | 绿色头像渐变 |
| 邮件 | SVG 信封 (描边) | `#5B9CF5` | 蓝色头像渐变 |
| Web Widget | SVG 地球仪 (描边) | `#a3a3a3` | 灰色头像渐变 |

---

## AI Slop 防护

- [x] 禁止无理由卡片网格
- [x] 禁止装饰性渐变（仅头像使用功能性渐变）
- [x] 禁止 emoji 图标（统一 SVG Feather 风格）
- [x] 禁止纯黑 `#000` / 纯白 `#fff` 大篇幅
- [x] 禁止零动效（所有交互有过渡）
- [x] 禁止均等间距（使用系统化间距量表）

---

## 参考

- Vercel Design System (`templates/vercel.md`)
- Linear Design System (`templates/linear.app.md`)
- Intercom Design System (`templates/intercom.md`)
- SalesOS Lite CONTEXT.md
