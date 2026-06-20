# DESIGN.md — SalesOS Lite 设计系统

## Brand
- **品牌调性:** 专业克制 · 精密工程感 · 暖白底色 · 呼吸留白
- **核心情感:** 可靠的工具——不炫技，不打扰，让外贸人专注于对话本身
- **一句话:** 像 Vercel 一样精确，像 Intercom 一样温暖，像 Linear 一样克制

## Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-root` | `#fafafa` | 页面底色 |
| `--bg-surface` | `#ffffff` | 卡片/面板/导航 |
| `--bg-subtle` | `#f5f5f5` | 输入框、次要区域 |
| `--bg-hover` | `rgba(0,0,0,0.03)` | 悬停态 |
| `--bg-active` | `rgba(0,0,0,0.05)` | 按下态 |
| `--text-primary` | `#171717` | 正文、标题 |
| `--text-secondary` | `#4d4d4d` | 辅助描述 |
| `--text-tertiary` | `#808080` | 弱化信息 |
| `--text-quaternary` | `#a3a3a3` | 占位符、时间戳 |
| `--text-disabled` | `#d4d4d4` | 禁用态文字 |
| `--accent` | `#6c5ce7` | 品牌主色 |
| `--accent-hover` | `#5a4bd1` | 悬停加深 |
| `--accent-soft` | `rgba(108,92,231,0.06)` | 淡紫底色 |
| `--whatsapp` | `#25D366` | WhatsApp 品牌绿 |
| `--email` | `#5B9CF5` | 邮件品牌蓝 |
| `--success` | `#10b981` | 成功/在线 |
| `--warning` | `#f59e0b` | 警告/待跟进 |
| `--danger` | `#ef4444` | 危险/错误 |

## Typography

**Primary:** Geist (self-host or Google Fonts CDN)  
**Mono:** Geist Mono  
**Features:** `font-feature-settings: 'liga' 1` 全局启用

> ⚠️ Google Fonts CDN 在国内被墙。国内部署必须自托管 Geist 字体文件。
> 开发阶段可用 CDN，生产环境切换自托管。

| Level | Size | Weight | Tracking | Usage |
|-------|------|--------|----------|-------|
| h1 | 18px | 600 | -0.36px | 页面标题 |
| h2 | 15px | 600 | -0.2px | 对话标题 |
| h3 | 13px | 500 | -0.13px | 列表名称 |
| body | 13px | 400 | 0 | 消息正文 |
| body-sm | 12px | 400 | 0 | 辅助文字 |
| label | 11-12px | 500 | 0 | 按钮/标签 |
| time | 11px | 400 | `tnum` | 时间戳 |
| caption | 10px | 600 | 0.6px uppercase | 面板标题 |

## Spacing

| Token | Value |
|-------|-------|
| xs | 4px |
| sm | 8px |
| md | 12px |
| lg | 16px |
| xl | 24px |
| 2xl | 32px |
| 3xl | 48px |

## Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| sm | 6px | 按钮、输入框 |
| md | 8px | 导航图标、标签 |
| lg | 12px | 对话列表项、卡片 |
| xl | 16px | 消息气泡 |
| pill | 9999px | 筛选标签、状态点 |

## Shadows (Vercel shadow-as-border technique)

| Level | Value | Usage |
|-------|-------|-------|
| border | `0 0 0 1px rgba(0,0,0,0.06)` | 替代 CSS border |
| card | border + `0 1px 2px rgba(0,0,0,0.04)` | 消息气泡、卡片 |
| elevated | border + `0 2px 8px rgba(0,0,0,0.06)` + `inset 0 0 0 1px #fafafa` | AI 卡片、浮层 |
| focus | `0 0 0 2px rgba(108,92,231,0.4)` | 键盘聚焦环 |

**绝不使用 CSS `border` 属性。所有分割线由 shadow-as-border 实现。**

## Motion

| Duration | Usage |
|----------|-------|
| 150ms | hover, focus, 微交互 |
| 200ms | 切换、展开/收起 |
| 300ms | 页面过渡 |

**Easing:** `cubic-bezier(0.16, 1, 0.3, 1)` — 所有过渡统一

**Button feedback:** hover `scale(1.05)`, active `scale(0.95)`, disabled `opacity: 0.4`

## Component States (per interactive element)

Each interactive element MUST cover:
1. Default — normal appearance
2. Hover — mouse over
3. Active — pressed/clicking
4. Focus — keyboard focus (MUST be visible)
5. Disabled — unavailable
6. Loading — in progress
7. Empty — no data
8. Error — failure state

## Layout

```
Icon Nav (60px) | Inbox List (320px) | Chat (flex:1) | AI Context Sidebar (300px, collapsible)
```

**Pipeline view (独立标签页):**
```
Icon Nav (60px) | Pipeline Board (4 columns, horizontal scroll)
```

- **Nav:** 60px icon-only sidebar, brand logo at top, active = accent-soft background
- **Inbox List:** search + conversation list with channel indicators and intent tags
- **Chat:** message bubbles + composer with AI draft / voice / pipeline quick actions
- **AI Context:** opportunity card, decision chain, last interaction, related docs, competitor, alerts
- **Pipeline:** 4 columns (需求确认/技术交流/报价谈判/合同), cards with hover lift + accent border

## Channel Icons

| Channel | Style | Color |
|---------|-------|-------|
| WhatsApp | SVG fill (official logo) | `#25D366` |
| Email | SVG stroke (envelope) | `#5B9CF5` |
| Web Widget | SVG stroke (globe) | `#a3a3a3` |

**Never use emoji for icons. Always SVG (Feather icon style).**

## AI Slop Prevention

- ❌ No decorative card grids — every card must earn its place
- ❌ No decorative gradients — gradient only on avatars and brand logo
- ❌ No emoji icons — SVG Feather style only
- ❌ No pure `#000` or `#fff` large surfaces
- ❌ No zero-transition interactions
- ❌ No uniform spacing — use defined spacing scale
- ❌ No `system-ui` fallback — Geist is the identity
