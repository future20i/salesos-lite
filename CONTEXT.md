# SalesOS Lite — 领域语言

> 本文件是项目术语的单一事实来源。所有模块名、函数名、变量名、API 端点、Issue 标题
> 必须使用本文定义的术语。发现术语混淆或缺失时，更新本文档。

---

## 核心术语

### 租户 (Tenant)

一个使用 SalesOS Lite SaaS 的独立企业。每个租户拥有自己的数据、用户和配置，
与其他租户完全隔离。

**关系：** 包含 User, Lead, Client, Conversation

### 用户 (User)

隶属于某个租户的系统使用者。拥有角色和权限。

**关系：** 属于 Tenant，处理 Lead

### 角色 (Role)

用户的权限级别。三个固定角色：

- **admin** — 租户管理员。看所有数据，管理用户，配置系统
- **manager** — 销售经理。看团队所有线索，审批，分配
- **rep** — 一线业务员。看自己负责的线索，回复，提交审批

**关系：** 授予 User

### 渠道 (Channel)

客户消息的来源平台。

- **web** — 官网嵌入的聊天 widget（M2）
- **email** — 邮件（Mailgun Inbound Parse）
- **whatsapp** — WhatsApp Business API（M3）

**关系：** Lead 有一个来源 Channel

### 询盘 (Inquiry)

客户通过任一渠道发起的首次联系。询盘可能转化为线索，也可能无响应。

**关系：** 来自 Channel，升级为 Lead

### 线索 (Lead)

经过初步筛选、确认有跟进价值的客户关系。线索有生命周期阶段：

`新线索 → 跟进中 → 已报价 → 样品寄出 → 议价中 → 已成交`

每个阶段对应不同的跟进策略和优先级。

**别名：** 商机 (Opportunity)

**关系：** 从 Inquiry 升级，包含 Message 历史，可转为 Client，有 Intent 标签，有 Quotation

### 客户 (Client)

已至少完成一次交易的 Lead。有交易记录、采购偏好、复购潜力。

**别名：** 老客 (Regular Customer)

**关系：** 从 Lead 升级

### 消息 (Message)

客户或业务员发送的单条消息。方向：

- **inbound** — 客户 → 系统
- **outbound** — 业务员 → 客户

**关系：** 属于 Lead

### 客户画像 (Customer Profile)

从消息中提取的结构化客户信息：

- **目标价 (Target Price)** — 客户提及的价格预期
- **询价产品 (Inquired SKU)** — 客户感兴趣的具体产品型号
- **规格要求 (Specs)** — 技术参数要求
- **港口 (Port)** — 起运港/目的港
- **联系人类别 (Contact Type)** — 采购/技术/老板
- **决策链 (Decision Chain)** — 客户内部采购决策结构
- **付款条件 (Payment Terms)** — T/T、L/C 等
- **竞争对标 (Competitor)** — 客户提及的竞争品牌
- **时区 (Timezone)** — 客户所在时区
- **客户来源 (Lead Source)** — 展会/阿里/Google/介绍

画像由 AI 从对话中异步提取。

**别名：** 客户标签 (Customer Tags)

### 意向 (Intent)

客户成交可能性的分级标签。由系统根据行为信号自动推断，
不允许人工标记：

- **hot** — 客户要了报价单/PI/样品
- **warm** — 客户问了具体规格/数量/交期
- **cold** — 仅初次询盘，或超过 N 天未回复
- **dormant** — 超过 90 天无互动
- **closed** — 已成交

**关系：** Lead 有一个 Intent 标签

### 报价 (Quotation)

向客户发出的结构化报价。包含：产品型号、规格、价格条款 (FOB/CIF)、
数量、交期、有效期、付款条件。报价是里程碑，AI 从对话中提取。

**关系：** 属于 Lead

### 跟进 (Follow-up)

对线索或客户的主动触达动作。类型包括：报价跟进、样品跟进、
节日关怀、催单、唤醒。可手动设定或系统自动触发（M5）。

**关系：** 属于 Lead 或 Client

### 回复模板 (Canned Response)

预设消息文本，按外贸场景分类：

- **inquiry_reply** — 初次回复
- **quotation_followup** — 报价跟进
- **sample_followup** — 样品跟进
- **holiday_greeting** — 节日关怀
- **order_nudge** — 催单
- **revival** — 失联唤醒

支持变量占位符（如 `{{customer_name}}`）。

**关系：** 属于 Tenant

### 分配 (Assignment)

将线索的责任人指定为某个 User。manager 可手动分配，
或被分配规则自动触发（M5）。

**关系：** Lead → User

### 审批 (Approval)

rep 发起的消息需经理确认后发送的场景。流程：`提交 → 待审批 → 通过/驳回`。

**关系：** 属于 Tenant，关联 Lead，由 User 操作

### 看板 (Dashboard)

manager/admin 视角的数据面板。展示：
- 团队线索概览（总量/新询盘/未分配）
- 每位业务员的线索数和响应时间
- 意向分布（hot/warm/cold/dormant）
- 转化漏斗（询盘→线索→报价→成交）
- 人效对比
- 待审批数量

**关系：** 属于 Tenant

### 套餐 (Plan)

租户的付费等级：Starter / Growth / Pro。
定义席位上限和功能开关。

### 订阅 (Subscription)

租户与套餐的关联，包含起止时间、续费状态、支付记录。

---

## 标记的歧义

（项目初期，尚未产生术语混淆。）
