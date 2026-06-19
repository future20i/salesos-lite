# SalesOS Lite — 产品规格

**版本：** 1.0  
**日期：** 2026-06-19  
**状态：** proposed

---

## 问题陈述

中小外贸企业（3-50 人）的客户沟通分散在 WhatsApp、邮件、网站等多个渠道，数据散落在业务员个人设备中。业务员离职带走客户，管理者看不到销售过程，询盘转化率不可衡量。现有 SaaS（星谷云、OKKI）价格高、生态绑定深；开源方案（Chatwoot）没有外贸垂直能力。

## 解决方案

SalesOS Lite 是一个极轻的 SaaS 统一收件箱，专为中小外贸企业设计。聚合 Web Chat、邮件、WhatsApp 三个核心渠道，用 AI 自动提取客户画像和意向分级，按月按席位收费（¥199/月/席起）。核心差异化：**外贸垂直领域语言 + 极简部署 + 老板实时看板 + 数据不出租户**。

---

## 用户故事

1. 作为外贸老板，我注册后 5 分钟内完成渠道配置，看到第一个客户询盘出现在收件箱中，确认系统"能用"。
2. 作为外贸老板，我打开看板看到所有业务员正在跟进的线索及其阶段，知道"没有客户被遗漏"。
3. 作为外贸老板，我导出全部客户数据，确认"我的数据随时可以带走"。
4. 作为业务员，我打开收件箱看到所有渠道的消息汇聚在一个列表里，不需要来回切换 WhatsApp/邮件/网站。
5. 作为业务员，我回复客户时一键插入外贸场景模板（初次回复、报价跟进、样品跟进），提升回复效率。
6. 作为业务员，我看到 AI 自动从对话中提取的客户画像（目标价、港口、询价产品、决策链），不用手动记笔记。
7. 作为业务员，我提交敏感回复给经理审批，确认后再发送。
8. 作为销售经理，我将新线索分配给最合适的业务员。
9. 作为销售经理，我看到每位业务员的人效数据（线索数、响应时间、转化率）。
10. 作为试用用户，我 14 天内体验全部功能，零摩擦决定是否付费。

---

## 架构决策

### 部署拓扑

```
单台 VPS
├── FastAPI 单体进程（所有业务逻辑 + SSE 推送 + 静态文件）
└── PostgreSQL（数据 + RLS 租户隔离 + ai_jobs 队列 + LISTEN/NOTIFY）
```

**原则：** 一个进程 + 一个外部依赖。不做独立 Worker 进程，不做 Redis，不做 Nginx。

### 模块

| 模块 | 职责 | 关键接口 |
|------|------|---------|
| **Channel Adapter** | 接收 Web/邮件/WhatsApp 消息，统一为 Message | Webhook 回调 + Mailgun Inbound Parse |
| **Inbox Core** | 收件箱 CRUD、消息发送、SSE 推送 | REST + SSE |
| **Auth** | 注册、登录、JWT、RBAC | Bearer Token |
| **AI Pipeline** | 异步提取画像 + 意向分级 | 内部 `ai_jobs` 表驱动 |
| **Approval** | 提交 → 待审批 → 通过/驳回 | REST |
| **Dashboard** | 线索概览、转化漏斗、人效 | REST（聚合查询） |
| **Billing** | 套餐选择、微信支付、订阅管理 | PayJs 回调 |

### 租户隔离

PostgreSQL Row-Level Security — 一条策略管控所有表：

```sql
CREATE POLICY tenant_isolation ON leads
  USING (tenant_id = current_setting('app.current_tenant_id'));
```

应用层在请求中间件设置 `app.current_tenant_id`。数据库层兜底——即使应用漏了 WHERE 条件，RLS 拒绝访问。

### AI 异步流水线

```
消息写入 → ai_jobs 表 (status=pending)
  ↓
后台轮询 SELECT ... FOR UPDATE SKIP LOCKED
  ↓
status=processing, locked_at=now()
  ↓
调 LLM → 写入 Lead 画像字段 + 意向标签
  ↓
status=done
  ↓
SSE 推送前端刷新
```

容错：扫描 `locked_at > 5 分钟` 的 job → 重置为 pending。

---

## 数据概念

见 `CONTEXT.md` 完整术语定义。核心实体关系：

```
Tenant ──< User ──< Assignment >── Lead
Tenant ──< Lead ──< Message
Lead ──< Quotation
Lead ──< Follow-up
Tenant ──< CannedResponse
Tenant ──< Plan
Tenant ──< Subscription
```

---

## 套餐定义

| | Starter | Growth | Pro |
|---|:--:|:--:|:--:|
| 月费 | ¥199 | ¥499 | ¥999 |
| 席位 | 3 | 10 | 30 |
| 渠道 | Web + 邮件 | + WhatsApp | + WhatsApp 蓝 V 协助 |
| AI 画像 | 意向分级 | 完整画像 + 跟进建议 | 完整 + 自定义 |
| 看板 | 基础 | 团队 + 人效 | 自定义报表 |
| 导出 | CSV | CSV + JSON | API |
| 支持 | 邮件 | 微信群 | 客户成功经理 |

---

## 上线路线

| 里程碑 | 内容 | 验收 |
|:--:|------|------|
| **M1** (2周) | 核心收件箱 + Web(HTTP API,无Widget)/邮件渠道 + 线索列表看板 + PG | 单人可收发消息、看线索状态 |
| **M2** (+1周) | 注册/试用/支付/导出 + 转化漏斗看板(效果指标) + Web Chat Widget | 陌生人可注册付钱使用 |
| **M3** (+2周) | AI 画像提取/意向分级 + WhatsApp 接入 | Growth 套餐完整可卖 |

---

## 测试决策

- **单元测试：** Auth、RBAC、意向分级逻辑、RLS 策略
- **集成测试：** 完整的"客户发消息 → 收件箱出现 → 业务员回复 → 客户收到"端到端流
- **手动 QA：** 微信支付回调、WhatsApp Webhook、Mailgun 邮件接收
- **边界条件：** 租户隔离验证（租户 A 不能看到租户 B 数据）、并发 RLS、SSE 断线重连

---

## 外部依赖

| 依赖 | 用途 | 免费层 |
|------|------|:--:|
| PostgreSQL | 数据库 | 自建 |
| Mailgun | 接收邮件 + 发验证码/通知 | 1000 封/月 |
| PayJs | 微信/支付宝支付 | 0 |
| LLM API | AI 画像提取 | 按量 |
| SMTP (Resend) | 发送事务邮件 | 100/天 |

---

## 不在范围

- WhatsApp 蓝 V 认证协助（M4）
- 移动端 App（M4+）
- OAuth 邮件接入（M4）
- 自动跟进规则引擎（M5）
- 报价结构化自动提取（M5）
- 多币种支付 / PayPal
- 优惠券 / 年付折扣
- 自定义报表生成器
- 品牌白标
