# SalesOS Lite — 产品规格 v2.0

> 项目型外贸销售的 AI 决策引擎
>
> 基于：系统思考分析 + 六产品竞争分析 + 四轮跨视角审查
> 日期：2026-06-20

---

## 1. 产品定位

### 1.1 一句话

**不是 CRM——是外贸销售的 AI 副驾驶。CRM 记录「发生了什么」，SalesOS 告诉你「现在该做什么」。**

### 1.2 目标用户

中国出海制造企业，做项目型 B2B 销售：
- 客单价百万级以上
- 销售周期 3-18 个月
- 多决策人（技术+采购+老板）
- 跨平台沟通（WhatsApp + 邮件 + Facebook + 展会 + 出差）

### 1.3 核心差异化

| 维度 | 现有 CRM | SalesOS Lite |
|------|---------|-------------|
| 数据录入 | 手动填表 | 消息自动捕获 + 语音快速录入 |
| 客户沉默 | "该联系了"的闹钟 | AI 诊断原因 + 建议策略 + 起草消息 |
| AI 角色 | 辅助写邮件 | 诊断→建议→起草→等人审核→执行→追踪 |
| 知识 | 空白起步 | 三层知识库（外贸通用+行业+企业） |
| 与大脑关系 | 孤岛 | Lite(前线执行) ↔ B2BSaleOS(策略大脑) |

---

## 2. 核心功能

### 2.1 多渠收件箱 (P0 — 已有)

所有渠道消息汇聚一个界面。支持 WhatsApp、邮件、Facebook、Web widget。
消息 AI 自动评分意向（hot/warm/cold/dormant）。

### 2.2 跟进管道 (P0 — 新增)

收件箱的第二种视图——按商机阶段排列。两层：

- **管理者视图：** 商机管道表（客户、阶段、金额、概率、预计成交、竞品信号）
- **业务员视图：** 点击商机展开跟进项（四列：待跟进→处理中→待审核→已完成）

### 2.3 商机管理 (P0 — 新增)

三层销售结构：

```
线索 (Lead) — 未验证接触
  └→ 商机 (Opportunity) — 确认有预算/时限
       └→ 跟进项 (FollowupItem) × N
            └→ 审核门禁 (Review Gate)
                 └→ 发出
```

商机阶段：`线索验证 → 需求确认 → 技术交流 → 报价/谈判 → 合同 → 成交`

### 2.4 AI 沉默提醒 (P0 — 新增)

> ⚠️ Phase 1 定位修正：不做「诊断」，只做「监测 + 提醒」。诊断能力需要历史数据积累，
> Phase 1 先建立信任基础。

工作流程：
1. **监测** — 持续追踪所有活跃商机的客户回复状态
2. **提醒** — 超过阈值天数时，系统生成提醒。阈值按商机阶段分级：
   - 技术交流：14 天无回复 → 提醒
   - 报价/谈判：7 天无回复 → 提醒
   - 合同：5 天无回复 → 提醒
   - 以上默认值，租户可在设置中调整
3. **建议** — 结合知识库给出跟进话术建议（不分析原因，只提供可用的消息模板）
4. **起草** — 生成跟进消息，标注上下文来源
5. **审核** — Phase 1 **全部消息人审**。没有任何消息 AI 自动发出
6. **执行** — 跨渠道发出
7. **追踪** — 监测回复，客户回了自动唤醒

降级行为：LLM API 不可用时 → 纯时间监测 + 通用提醒模板（不依赖 AI）

提醒持久化：所有提醒结果写入 `followup_events` 表。用户登录时批量呈现离线期间的提醒。

### 2.5 快速捕获 (P0 — 新增)

出差拜访、电话会议、展会碰面后的语音/文字快速录入。
AI 转文字 → 提取行动项 → 关联客户 → 生成跟进项 → 入管道。

### 2.6 三层知识库 (P0 — 新增)

| 层级 | 内容 | 存储 | 实现 |
|------|------|------|------|
| Tier 1 | 外贸通用基础 | 代码内常量 | 系统内置 Prompt（2000 tokens） |
| Tier 2 | 行业细分知识 | PostgreSQL `knowledge_entries` | B2BSaleOS 维护，租户可只读查看 |
| Tier 3 | 企业专属知识 | PostgreSQL `knowledge_entries` | 租户编辑，使用中自动积累 |

### 2.7 AI 起草 + 审核门禁 (P0 — 新增)

- AI 起草跟进消息，附带上下文来源标注
- **Phase 1 全部消息人审后发出。** 没有任何消息 AI 自动发送
- 分级审核（`routine`/`commercial`/`critical`）在 Phase 2 引入——需积累真实数据后判断边界
- 用户修改消息后记录原始版本和最终版本
- **不做风格学习、不做多版本切换。** 每次只生成一个草稿

### 2.8 种子管道 (P0 — 新增)

新租户注册后预置演示商机（带模拟对话+跟进项），可一键清除。
让用户第一天就看到活的管道，不是空表格。

---

## 3. 数据模型（新增）

### 3.1 Opportunity（商机）

```python
class OpportunityStage(str, Enum):
    LEAD_VALIDATION = "lead_validation"      # 线索验证
    NEEDS_CONFIRMATION = "needs_confirmation" # 需求确认
    TECHNICAL_EXCHANGE = "technical_exchange" # 技术交流
    QUOTATION_NEGOTIATION = "quotation_negotiation" # 报价/谈判
    CONTRACT = "contract"                     # 合同
    WON = "won"                               # 成交
    LOST = "lost"                             # 流失
    SHELVED = "shelved"                       # 搁置

class Opportunity(Base):
    id, tenant_id, lead_id (可空),
    name, value, probability, stage,
    expected_close_date, assigned_to,
    decision_chain (JSON),      # [{role, name, concerns}]
    competitor_tracking (JSON), # [{name, mentioned_at, context, our_response}]
    created_at, updated_at
```

### 3.2 FollowupItem（跟进项）

```python
class FollowupStatus(str, Enum):
    TODO = "todo"                # 待跟进
    IN_PROGRESS = "in_progress"  # 处理中
    PENDING_REVIEW = "pending_review" # 待审核
    DONE = "done"                # 已完成

class ReviewLevel(str, Enum):
    ROUTINE = "routine"          # AI 自动发，事后通知
    COMMERCIAL = "commercial"    # 人审核后发出
    CRITICAL = "critical"        # 强制人工审核

class FollowupItem(Base):
    id, opportunity_id, tenant_id,
    title, body, status, priority,
    source_type (conversation/manual/quick_capture),
    source_id, channel,
    review_level, ai_draft (Text),
    assigned_to, created_by,
    created_at, started_at, completed_at
```

### 3.3 FollowupEvent（跟进事件日志）

```python
class FollowupEvent(Base):
    id, followup_id, kind, payload (JSON), created_at
    # kind: created/dispatched/draft_generated/reviewed/
    #        approved/rejected/sent/responded/done/
    #        silence_alert/offline_digest
    # silence_alert = 沉默提醒已生成，payload 含阈值天数和上下文
    # offline_digest = 用户登录时批量呈现离线期间的提醒
```

### 3.4 KnowledgeEntry（知识库条目）

```python
class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"  # PostgreSQL, 与主库同一连接
    id, tenant_id, tier (SMALLINT: 1/2/3),
    category, title, content (Text),
    source (manual/ai_extracted/brain_downlink),
    is_active, created_at, updated_at
    # 注意：Tier 2 为只读（brain_downlink），Tier 3 为可编辑
```

### 3.5 现有模型扩展

- **Lead** — 增加 `opportunity_id` 外键
- **Message** — 增加 `direction='system'` 枚举值，增加 `followup_id` 外键
- 总模型数：14 → 18

---

## 4. API 端点（新增）

### 4.1 商机

```
GET    /api/opportunities              # 列表（按阶段分组，支持筛选）
GET    /api/opportunities/:id          # 详情（含决策链、竞品、跟进项列表）
POST   /api/opportunities              # 创建
PATCH  /api/opportunities/:id          # 更新（阶段推进触发生效）
POST   /api/opportunities/:id/convert  # 从线索转化为商机
GET    /api/opportunities/pipeline     # 管道聚合视图（管理者）
```

### 4.2 跟进项

```
GET    /api/followups                  # 列表（支持 ?status=&opportunity_id=）
GET    /api/followups/:id              # 详情（含事件日志）
POST   /api/followups                  # 创建
PATCH  /api/followups/:id              # 更新
POST   /api/followups/:id/move         # 状态流转
POST   /api/followups/:id/draft        # AI 起草消息
POST   /api/followups/:id/review       # 审核（approve/reject）
POST   /api/followups/:id/send         # 发出
POST   /api/followups/from-message     # 从对话消息创建跟进项
```

### 4.3 知识库

```
GET    /api/knowledge                  # 知识库列表（按 tier 分组）
POST   /api/knowledge                  # 新增条目
PATCH  /api/knowledge/:id              # 编辑条目
DELETE /api/knowledge/:id              # 删除条目
POST   /api/knowledge/seed             # 初始化种子知识库
```

### 4.4 AI 功能

```
POST   /api/ai/silence-check           # 沉默检测（异步，结果 SSE 推送或持久化到 events）
POST   /api/ai/draft-message            # AI 起草消息（带上下文标注，全部人审后发出）
POST   /api/ai/extract-followup         # 从消息提取跟进需求
```

> ⚠️ 所有 AI 端点复用 `ai_pipeline.py` 的 `TIER_LIMITS` 限流机制（starter: 5/min, growth: 20/min, pro: 60/min）。
> Phase 1 不做沉默诊断——只做时间阈值检测 + 通用提醒模板。LLM 不可用时降级为纯时间检测。|

---

## 5. 与 B2BSaleOS 大脑的连接

### 5.1 连接模式

- **独立模式：** Lite 完整运行所有核心功能，不依赖大脑
- **增强模式：** 连接大脑后获得策略优化、知识更新、跨租户学习

### 5.2 通信协议

- **上行（Lite → 大脑）：** REST API 推送成交数据、沉默模式、回复率统计
- **下行（大脑 → Lite）：** REST API 拉取 Tier 2 知识更新、最佳模板、策略建议
- **异步、无阻塞、优雅降级：** 大脑不可用时 Lite 正常运作

### 5.3 数据飞轮

```
多家 Lite 租户的 Tier 3 数据
    → 上行到大脑 → 匿名化聚合
    → 大脑学习行业模式
    → 更新 Tier 2 知识库
    → 下行到所有 Lite 租户
    → 所有租户的 AI 更聪明
```

---

## 6. 设计约束（来自项目 Pitfall 经验 + 跨模型审查修正）

- **数据库：PostgreSQL 统一存储。** 知识库与主库同一连接，不建独立数据库
- **沉默阈值默认值：** 技术交流 14 天 / 报价谈判 7 天 / 合同 5 天。租户可调
- **AI 限流：** 复用 ai_pipeline.py TIER_LIMITS（starter 5/min, growth 20/min, pro 60/min）
- **Phase 1 无自动发出：** 所有 AI 起草消息人审后发出。分级审核延至 Phase 2
- **增量扩展现有 SPA：** 不新建 HTML 文件。管道面板集成到 index.html
- **字体：** system-ui，不用 Google Fonts
- **部署验证：** 每次写入后 curl 检查 `***` 计数 = 0
- **Token 变量命名：** 不用 `TOKEN`/`token`，用 `_tk`
- **静态文件路径：** `/admin/` 前缀（如适用）
- **SQLAlchemy create_all 不修改已有表：** 新列需手动 ALTER TABLE
- **LLM 优雅降级：** API 不可用时→纯时间检测（不依赖 AI 推理）
- **离线提醒不丢失：** 沉默提醒持久化到 `followup_events`，登录时批量呈现
- **后台任务：** 复用 ai_pipeline.py 的 SKIP LOCKED + stale recovery 模式

---

## 7. Phase 1 范围

| 功能 | 优先级 | 状态 |
|------|--------|------|
| 多渠收件箱 | P0 | ✅ 已有 |
| 商机 CRUD + 管道视图（含搜索/筛选） | P0 | 🆕 |
| 跟进项 CRUD + 四列面板 | P0 | 🆕 |
| AI 沉默提醒（时间阈值+通用模板） | P0 | 🆕 |
| AI 起草消息（全部人审） | P0 | 🆕 |
| 快速捕获（语音+文字） | P0 | 🆕 |
| 三层知识库（PostgreSQL 统一存储） | P0 | 🆕 |
| 种子管道（演示商机+模拟对话） | P0 | 🆕 |
| 收件箱→管道最短路径 | P0 | 🆕 |
| AI API 限流（复用 TIER_LIMITS） | P0 | 🆕 |
| 提醒离线持久化 + 登录批量呈现 | P0 | 🆕 |
| SSE 实时推送 | P0 | ✅ 已有 |
| 审批流 | P0 | ✅ 已有 |

---

## 8. Phase 2 规划

- 竞品信号自动提取（从对话中识别竞品提及）
- 决策链进度追踪（每个决策人当前的审批状态）
- 多轮报价关联（Quotation parent/child）
- 向量检索知识库（Tier 3 超过 500 条时启用）
- B2BSaleOS 大脑连接（上行+下行 API）
- 移动端适配

---

## 9. 竞争定位更新

| 竞品 | 定位 | SalesOS 优势 |
|------|------|------------|
| OKKI | 贸易型外贸 CRM（阿里生态） | 项目型 + AI 决策引擎 + 独立部署 |
| Pipedrive | 通用销售管道 | 外贸专业 + 多渠收件箱 + AI 诊断 |
| HubSpot | 营销自动化 | 价格 + 中国可用 + 三层知识库 |
| 无竞品覆盖 | 语音快速捕获 | 出差/电话/展会场景的信息录入 |

---

## 10. 规格自检

- [x] 无 TODO/待定/占位符
- [x] 内部一致性：数据模型 ↔ API ↔ 功能描述 对应
- [x] 范围聚焦：Phase 1 可通过一个实现计划覆盖
- [x] 无歧义术语——所有术语见 CONTEXT.md
- [x] 设计约束明确列举了已知 Pitfall
