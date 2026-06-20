# SalesOS Lite — 领域语言

> 本文件是项目术语的单一事实来源。所有模块名、函数名、变量名、API 端点、Issue 标题
> 必须使用本文定义的术语。发现术语混淆或缺失时，更新本文档。
>
> 版本：v2.0 — 引入三层销售结构、AI决策引擎、跟进管道

---

## 核心术语

### 租户 (Tenant)

一个使用 SalesOS Lite 的外贸企业。每个租户拥有自己的数据、用户和配置，
与其他租户完全隔离。

**关系：** 包含 User, Lead, Opportunity, Project

### 用户 (User)

隶属于某个租户的系统使用者。拥有角色和权限。

**角色：**
- **admin** — 租户管理员。看所有数据，管理用户
- **manager** — 销售经理。看团队所有数据，审批，分配
- **rep** — 一线业务员。看自己负责的数据，回复，提交审批

**关系：** 属于 Tenant

### 渠道 (Channel)

客户消息的来源平台。

- **whatsapp** — WhatsApp Business API
- **email** — 邮件
- **facebook** — Facebook Messenger
- **web** — 官网嵌入的聊天 widget
- **offline** — 线下渠道（展会碰面、出差拜访、电话、视频会议）

**关系：** Lead 有一个来源 Channel

### 多渠收件箱 (Unified Inbox)

所有渠道的客户消息汇聚在同一个界面中。业务员在一个地方
读消息、回复、标记跟进。不需要在 WhatsApp / 邮件 / FB 之间切换。

**别名：** inbox, 统一收件箱

**关系：** 聚合所有 Channel 的 Message

### 消息 (Message)

客户或业务员发送的单条消息。方向：

- **inbound** — 客户 → 系统
- **outbound** — 业务员 → 客户
- **system** — 系统自动生成的通知（任务创建、状态变更等）

**关系：** 属于 Lead，可触发跟进项创建

---

## 三层销售结构

### 线索 (Lead)

未经验证的潜在客户联系。来源可能是展会名片、Facebook 询价、
TikTok 评论、官网表单。线索还不确定能否成交——可能只是随便问问。

**线索状态：** new → following → quoted → sampled → negotiating → closed

**关系：** 可升级为 Opportunity，包含 Message 历史，有 Intent 标签

### 商机 (Opportunity)

经过验证、确认有成交可能的销售机会。商机有明确的：
- 预估金额 (value)
- 成交概率 (probability)
- 预计成交日期 (expected_close_date)
- 竞争对手 (competitor)
- 决策人 (decision_maker)
- 阶段 (stage)

**商机阶段：** 线索验证 → 需求确认 → 报价/谈判 → 合同 → 成交

**关系：** 从 Lead 升级，包含 FollowupItem，成交后转为 Project

**别名：** deal, 销售机会

**⚠ 注意：** 旧版 CONTEXT.md 把「线索」和「商机」混为一谈。现已分离——
Lead 是未验证的接触，Opportunity 是确认有预算和时限的销售机会。

### 项目 (Project)

已成交的商机进入交付阶段。项目有：
- 交付里程碑 (milestones)
- 交付物 (deliverables)
- 时间线 (timeline)

**关系：** 从 Opportunity 转化，属于 Client

### 跟进项 (FollowupItem)

商机下的具体行动任务。一个商机可以包含多个跟进项。跟进项推动商机
在阶段间推进——所有跟进项完成后，商机阶段自动流转。

**跟进项状态：** 待跟进 → 处理中 → 待审核 → 已完成

**跟进项来源：**
- 从消息中自动提取（AI 识别需要跟进的对话）
- 通过快速捕获手动创建（出差/电话后语音录入）
- 业务员手动创建

**关系：** 属于 Opportunity，可关联 Message

### 客户信任存量 (Trust Stock)

每个客户关系中积累的信任度。不是显式评分，而是系统的隐含状态——
通过历史成交、回复速度、沟通质量等因素反映在 AI 的决策建议中。
信任积累慢、流失快、换人后可能归零。

**别名：** 客户关系深度

---

## 跟进管道 (Pipeline)

### 跟进管道 (Follow-up Pipeline)

商机和跟进项的统一可视化视图。不是独立的「看板页面」，而是
收件箱的第二种视图——同一份数据（对话+商机+跟进项），按状态维度排列。

**两层视图：**
- **管理层视图：** 商机按阶段排列，显示金额和预测
- **业务员视图：** 点击商机展开其下的跟进项

**关系：** 属于 Tenant，聚合 Opportunity 和 FollowupItem

### 沉默客户 (Silent Customer)

曾经活跃但超过 N 天未回复的客户。沉默不等于流失——客户可能
在内部审批、在比价、或者只是忘了回复。沉默客户池是系统
最大的价值洼地——AI 的核心工作就是诊断和激活这个池子。

**别名：** 静默客户, dormant lead

### 沉默诊断 (Silence Diagnosis)

AI 分析客户沉默原因的过程。基于最近对话内容、客户历史行为、
商机阶段等上下文，判断沉默原因属于：

- **正常流程** — 客户在内部审批，预计 X 天后回复
- **竞品威胁** — 客户可能在比价，需要主动提供差异化价值
- **遗忘** — 客户只是忘了，温和提醒即可
- **流失风险** — 超过临界天数无回复，需要升级策略

诊断结果带有置信度，业务员可以确认或修正。

### 温和触达 (Gentle Reach-out)

AI 基于沉默诊断结果，自动起草一条跟进消息。消息风格温和、不催促、
带具体价值信息。起草后进入审核门禁，业务员审核/修改后发出。

**别名：** AI唤醒, 自动跟进

---

## AI 决策引擎

### AI 决策引擎 (AI Decision Engine)

SalesOS 的核心差异——不是被动记录，而是主动告诉业务员「现在该做什么」。
决策引擎的工作流程：
1. **监测** — 持续监测所有客户的状态变化
2. **诊断** — 发现异常（沉默/意向变化/竞品信号）时分析原因
3. **建议** — 给出具体行动方案
4. **起草** — 自动生成跟进消息/报价草稿/方案大纲
5. **等待审核** — 业务员审核、修改、批准
6. **执行** — 跨渠道发出
7. **复盘** — 追踪结果，反馈给大脑学习

**别名：** AI副驾驶

**关系：** 驱动所有 AI 功能：沉默诊断、温和触达、意向评分、报价起草

### 审核门禁 (Review Gate)

任何 AI 生成的内容在对外发出前，必须经过人工审核。审核门禁
是不可跳过的——这建立业务员对 AI 的信任。

**审核状态：** pending → approved → executed | rejected → draft

**别名：** 人工审批, human-in-the-loop

### 意向评分 (Intent Scoring)

AI 从对话内容中自动评估客户的购买意向：
- **hot** — 问了价格或要了 PI
- **warm** — 问了具体规格、数量、交期
- **cold** — 初次询盘或超 N 天未回复
- **dormant** — 超过 90 天无互动

意向标签由 AI 自动推断，不允许人工标记——避免乐观偏差。

**关系：** Lead 有一个 Intent

### 客户画像 (Customer Profile)

AI 从对话中异步提取的结构化客户信息：目标价、询价产品、规格要求、
目的地、联系人类别、决策链、竞品信息、时区、来源渠道等。

**关系：** 属于 Lead

---

## 快速捕获

### 快速捕获 (Quick Capture)

业务员在非消息场景（出差拜访、电话会议、视频会议、展会碰面）后，
快速录入跟进事项的入口。支持：
- **语音录入** — 说出要点，AI 转文字 + 结构化
- **文字录入** — 打几个字描述

录入后 AI 自动提取行动项、关联客户、建议优先级、生成跟进项。

**别名：** 语音速记, quick note

### 业务员心力容量 (Rep Capacity)

每个业务员能同时有效管理的活跃商机数量的上限。自然上限约 15-25 个。
超过上限时，跟进质量下降，沉默率上升。系统应在接近上限时预警，
建议重新分配或降级低优先级商机。

**别名：** 工作量上限, WIP limit

---

## 消息与协作

### 回复模板 (Canned Response)

预设消息文本，按外贸场景分类。支持变量占位符（如 `{{customer_name}}`）。
AI 可根据上下文推荐合适的模板。

### 分配 (Assignment)

将线索或商机的责任人指定为某个 User。manager 可手动分配。

**关系：** Lead/Opportunity → User

### 审批 (Approval)

rep 发起的消息或行动需经理确认的流程。流程：`提交 → 待审批 → 通过/驳回`。

**关系：** 属于 Tenant，关联 FollowupItem，由 User 操作

---

## 定价

### 套餐 (Plan)

租户的付费等级：Starter / Growth / Pro。定义席位上限和功能开关。

### 订阅 (Subscription)

租户与套餐的关联，包含起止时间、续费状态、支付记录。

---

## SalesOS Lite ↔ B2BSaleOS 大脑

### 数据上行 (Uplink)

SalesOS Lite 将前线数据（成交记录、沉默模式、回复率、最佳跟进节奏）
回传给 B2BSaleOS 大脑用于模式学习和策略优化。

### 策略下行 (Downlink)

B2BSaleOS 大脑将学习成果（最佳模板、最优跟进节奏、高转化话术）
下发给 SalesOS Lite 执行。

### 资讯打通 (Brain Bridge)

两个系统共享同一套领域语言和数据模型。Lite 是前线执行者，
B2BSaleOS 是后方策略大脑。Lite 可以独立运行，接入大脑后获得
策略优化能力。

---

## 标记的歧义

### 术语中英代码名对照

| 中文术语 | 代码/API 名 | 数据库表（规划） |
|----------|------------|-----------------|
| 租户 | `tenant` | `tenants` |
| 用户 | `user` | `users` |
| 线索 | `lead` | `leads` |
| 商机 | `opportunity` | `opportunities` |
| 项目 | `project` | `projects` |
| 跟进项 | `followup_item` | `followup_items` |
| 消息 | `message` | `messages` |
| 渠道 | `channel` | —（枚举） |
| 报价 | `quotation` | `quotations` |
| 跟进管道 | `pipeline` | —（聚合查询） |
| 沉默诊断 | `silence_diagnosis` | —（AI推理） |
| 温和触达 | `gentle_reachout` | —（AI生成） |
| 快速捕获 | `quick_capture` | —（语音转文字） |
| 审核门禁 | `review_gate` | —（审批流） |
| 意向评分 | `intent_score` | —（AI推断） |
| 客户画像 | `customer_profile` | —（AI提取） |
| 业务员心力 | `rep_capacity` | —（系统监测） |
| 审批 | `approval` | `approvals` |
| 模板 | `canned_response` | `canned_responses` |
| 套餐 | `plan` | `plans` |
| 订阅 | `subscription` | `subscriptions` |

### 已解决的歧义

#### 线索 vs 商机（已解决 2026-06-20）

旧版将 Lead 和 Opportunity 混为一谈（别名为「商机」）。
现分离为两层：Lead = 未验证接触，Opportunity = 确认有预算/时限的销售机会。
Lead 可升级为 Opportunity，但不是所有 Lead 都值得升级。

#### 跟进 vs 跟进项（已解决 2026-06-20）

旧版「跟进」定义太宽泛。现拆分为：
- **跟进项 (FollowupItem)** — 商机下的具体行动任务
- **跟进管道 (Pipeline)** — 商机和跟进项的聚合视图
- **温和触达 (Gentle Reach-out)** — AI 自动起草的跟进消息

#### 看板 vs 跟进管道（已解决 2026-06-20）

不再使用「看板」这个词——它携带了软件开发 Kanban 的心智模型。
改用「跟进管道」——销售团队的自然语言。
