# 跟进管道 + AI 决策引擎 — 实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 在 SalesOS Lite 中新增商机管道、跟进项管理、AI 沉默提醒、三层知识库，扩展 SPA 增加管道面板。

**Architecture:** 新增 4 个 PostgreSQL 模型 + 3 个 API 路由 + 1 个后台循环 + 前端管道面板。全部遵循现有模式（UUID PK、tenant_id RLS、SAEnum、FastAPI router、ai_pipeline 后台任务）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL + DeepSeek LLM + 单文件 SPA (vanilla JS)

**新增文件:**
- `src/models/opportunity.py`, `src/models/followup.py`, `src/models/knowledge.py`
- `src/api/opportunity_routes.py`, `src/api/followup_routes.py`, `src/api/knowledge_routes.py`
- `src/pipeline/silence_check.py`
- `docs/migrations/m6_pipeline.sql`

**修改文件:**
- `src/models/__init__.py`, `src/models/lead.py`, `src/models/message.py`
- `src/app.py`
- `src/llm_client.py`
- `static/index.html`

---

## Phase A: 数据模型（5 tasks）

### Task A1: Opportunity 模型

**Objective:** 创建商机模型，含状态枚举、决策链JSON、竞品追踪JSON

**Files:**
- Create: `src/models/opportunity.py`
- Modify: `src/models/__init__.py`

**Step 1: 写模型文件**

```python
# src/models/opportunity.py
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Enum as SAEnum, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base
import enum

class OpportunityStage(str, enum.Enum):
    LEAD_VALIDATION = "lead_validation"
    NEEDS_CONFIRMATION = "needs_confirmation"
    TECHNICAL_EXCHANGE = "technical_exchange"
    QUOTATION_NEGOTIATION = "quotation_negotiation"
    CONTRACT = "contract"
    WON = "won"
    LOST = "lost"
    SHELVED = "shelved"

class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    stage: Mapped[OpportunityStage] = mapped_column(
        SAEnum(OpportunityStage), nullable=False, default=OpportunityStage.LEAD_VALIDATION
    )
    expected_close_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    decision_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    competitor_tracking: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="opportunities")
    lead: Mapped["Lead | None"] = relationship(back_populates="opportunity")
    followups: Mapped[list["FollowupItem"]] = relationship(
        back_populates="opportunity", order_by="FollowupItem.created_at"
    )
```

**Step 2: 注册模型**

```python
# 在 src/models/__init__.py 末尾加:
from src.models.opportunity import Opportunity, OpportunityStage

# __all__ 加: "Opportunity", "OpportunityStage"
```

**Verification:**
```bash
cd /root/workspace/salesos-lite && .venv/bin/python -c "from src.models.opportunity import Opportunity, OpportunityStage; print('OK')"
# Expected: OK
```

---

### Task A2: FollowupItem + FollowupEvent 模型

**Objective:** 创建跟进项和跟进事件模型

**Files:**
- Create: `src/models/followup.py`
- Modify: `src/models/__init__.py`

**Step 1: 写模型文件**

```python
# src/models/followup.py
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base
import enum

class FollowupStatus(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    DONE = "done"

class ReviewLevel(str, enum.Enum):
    ROUTINE = "routine"
    COMMERCIAL = "commercial"
    CRITICAL = "critical"

class FollowupItem(Base):
    __tablename__ = "followup_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FollowupStatus] = mapped_column(
        SAEnum(FollowupStatus), nullable=False, default=FollowupStatus.TODO
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 0/1/5/10
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    # source_type: conversation | manual | quick_capture
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True  # points to message.id if conversation source
    )
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_level: Mapped[ReviewLevel] = mapped_column(
        SAEnum(ReviewLevel), nullable=False, default=ReviewLevel.COMMERCIAL
    )
    ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    opportunity: Mapped["Opportunity"] = relationship(back_populates="followups")
    events: Mapped[list["FollowupEvent"]] = relationship(
        back_populates="followup", order_by="FollowupEvent.created_at"
    )


class FollowupEvent(Base):
    __tablename__ = "followup_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    followup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("followup_items.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # kind: created | dispatched | draft_generated | reviewed |
    #        approved | rejected | sent | responded | done |
    #        silence_alert | offline_digest
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    followup: Mapped["FollowupItem"] = relationship(back_populates="events")
```

**Step 2: 注册模型**

```python
# 在 src/models/__init__.py 加:
from src.models.followup import FollowupItem, FollowupStatus, FollowupEvent, ReviewLevel
# __all__ 加: "FollowupItem", "FollowupStatus", "FollowupEvent", "ReviewLevel"
```

**Verification:**
```bash
cd /root/workspace/salesos-lite && .venv/bin/python -c "from src.models.followup import FollowupItem, FollowupEvent; print('OK')"
```

---

### Task A3: KnowledgeEntry 模型

**Objective:** 创建三层知识库模型

**Files:**
- Create: `src/models/knowledge.py`
- Modify: `src/models/__init__.py`

```python
# src/models/knowledge.py
import uuid
from datetime import datetime
from sqlalchemy import String, SmallInteger, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base

class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1/2/3
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    # source: manual | ai_extracted | brain_downlink
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

**Verification:** `python -c "from src.models.knowledge import KnowledgeEntry; print('OK')"`

---

### Task A4: 扩展现有模型（Lead + Message）

**Objective:** Lead 加 opportunity_id 外键，Message 加 system 方向 + followup_id

**Files:**
- Modify: `src/models/lead.py`
- Modify: `src/models/message.py`

**Lead 修改:**

```python
# 在 Lead 类中加:
opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True, index=True
)
opportunity: Mapped["Opportunity | None"] = relationship(
    back_populates="lead", foreign_keys=[opportunity_id]
)
```

**Message 修改:**

```python
# MessageDirection 枚举加:
SYSTEM = "system"

# Message 类加:
followup_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("followup_items.id"), nullable=True, index=True
)
```

**Verification:** `python -c "from src.models import Lead, Message; print('OK')"`

---

### Task A5: 数据库迁移（手动 ALTER TABLE）

**Objective:** 在生产数据库上执行新表创建和列新增

**Files:**
- Create: `docs/migrations/m6_pipeline.sql`

```sql
-- docs/migrations/m6_pipeline.sql

-- 新枚举类型
DO $$ BEGIN
    CREATE TYPE opportunitystage AS ENUM (
        'lead_validation','needs_confirmation','technical_exchange',
        'quotation_negotiation','contract','won','lost','shelved'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE followupstatus AS ENUM ('todo','in_progress','pending_review','done');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE reviewlevel AS ENUM ('routine','commercial','critical');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 新表（Base.metadata.create_all 会在启动时建，此 SQL 用于手动场景）
-- 列扩展
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opportunity_id UUID REFERENCES opportunities(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS followup_id UUID REFERENCES followup_items(id);
```

**Execution:**
```bash
docker exec b2bsaleos-db psql -U b2bsaleos -d salesos_lite -f docs/migrations/m6_pipeline.sql
```

> ⚠️ `Base.metadata.create_all` 会在 app 启动时自动建新表。此 SQL 仅用于已有数据库的列扩展。

---

## Phase B: API 路由（5 tasks）

### Task B1: 商机 CRUD API

**Objective:** 商机列表/详情/创建/更新/转化端点

**Files:**
- Create: `src/api/opportunity_routes.py`
- Modify: `src/app.py`

**端点:**
```
GET    /api/opportunities             # 列表，支持 ?stage=&assigned_to=&q=(搜索名称+客户名)
GET    /api/opportunities/:id         # 详情（含 lead, followups 计数）
POST   /api/opportunities             # 创建
PATCH  /api/opportunities/:id         # 更新（含阶段推进校验）
POST   /api/opportunities/:id/convert # 从线索转化
DELETE /api/opportunities/:id         # 删除（仅 stage=shelved/lost 且无活跃 followup）
```

**关键逻辑：** 阶段推进时，如果推进到 won，将关联 lead 的 status 改为 closed。阶段推进记录为 FollowupEvent。

**Step 3: 注册路由**

```python
# src/app.py 加:
from src.api.opportunity_routes import router as opportunity_router
app.include_router(opportunity_router)
```

**Verification:**
```bash
# 获取 token 后测试
curl -s http://localhost:8000/api/opportunities -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -5
```

---

### Task B2: 跟进项 CRUD API

**Objective:** 跟进项列表/详情/创建/更新/状态流转端点

**Files:**
- Create: `src/api/followup_routes.py`
- Modify: `src/app.py`

**端点:**
```
GET    /api/followups                        # 列表，支持 ?status=&opportunity_id=&assigned_to=
GET    /api/followups/:id                    # 详情（含 events）
POST   /api/followups                        # 创建
PATCH  /api/followups/:id                    # 更新
POST   /api/followups/:id/move               # 状态流转 {to: "in_progress|pending_review|done"}
POST   /api/followups/:id/draft              # AI 起草消息（调用 llm_client）
POST   /api/followups/:id/review             # 审核 {action: "approve"|"reject"}
POST   /api/followups/from-message           # 从消息创建跟进项 {message_id, opportunity_id?}
```

**关键逻辑：**
- `move` 到 done 时设置 completed_at
- `move` 到 in_progress 时设置 started_at
- 每次状态变更记录 FollowupEvent
- `draft` 调用 `llm_client.generate_followup_draft()`，结果存 ai_draft
- `review` approve 后进入 done，reject 后回到 in_progress

**Verification:**
```bash
curl -s -X POST http://localhost:8000/api/followups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"opportunity_id":"...","title":"测试跟进"}' | python3 -m json.tool
```

---

### Task B3: 知识库 CRUD API + 种子数据

**Objective:** 知识库列表/创建/编辑/删除 + 新租户种子数据

**Files:**
- Create: `src/api/knowledge_routes.py`
- Modify: `src/app.py`

**端点:**
```
GET    /api/knowledge              # 列表，支持 ?tier=&category=
POST   /api/knowledge              # 新增（Tier 2 brain_downlink 禁止用户创建）
PATCH  /api/knowledge/:id          # 编辑（Tier 2 不可编辑）
DELETE /api/knowledge/:id          # 删除（Tier 2 不可删除）
POST   /api/knowledge/seed         # 初始化种子知识库（Tier 1 + Tier 2 基础条目）
```

**种子数据示例（约 15 条）：**

Tier 1（通用外贸）:
- 贸易术语速查（FOB/CIF/T/T/L/C 等）
- 跨时区沟通礼仪
- 客户异议处理模式
- 报价单/PI 标准结构
- 展会跟进最佳实践

Tier 2（行业示例 — 飞轮UPS）:
- 飞轮 vs 蓄电池 vs 超级电容技术对比
- 关键参数含义与客户关注点
- 竞品对比速查
- 典型项目周期与阶段

---

### Task B4: AI 沉默检测后台循环

**Objective:** 周期性扫描活跃商机，超阈值生成提醒事件

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/silence_check.py`
- Modify: `src/app.py`

```python
# src/pipeline/silence_check.py
# 核心逻辑:

SILENCE_THRESHOLDS = {
    "technical_exchange": 14,      # 天
    "quotation_negotiation": 7,
    "contract": 5,
}
DEFAULT_THRESHOLD = 14

async def check_silent_opportunities():
    """扫描所有活跃商机 (not won/lost/shelved)，检查最后一条 inbound 消息距今多少天。
    超过阈值 → 在 followup_events 中插入 silence_alert 记录。"""
    
async def silence_check_loop(interval_seconds: float = 3600):
    """每小时运行一次沉默检查。"""
    while True:
        try:
            await check_silent_opportunities()
        except Exception:
            logger.exception("Silence check failed")
        await asyncio.sleep(interval_seconds)
```

**在 app.py lifespan 中启动:**
```python
# 加在 startup 部分:
_silence_task = asyncio.create_task(silence_check_loop(interval_seconds=3600))
```

---

### Task B5: AI 起草消息 LLM 函数

**Objective:** 在 llm_client.py 中新增跟进消息起草函数

**Files:**
- Modify: `src/llm_client.py`

```python
FOLLOWUP_DRAFT_PROMPT = """You are a sales assistant for a Chinese foreign trade company. 
Based on the opportunity context below, draft a professional follow-up message.

Opportunity: {opportunity_name}
Customer: {customer_name}
Stage: {stage}
Last interaction: {last_context}
Knowledge context: {knowledge_context}

Write a CONCISE, natural follow-up message in Chinese (2-3 sentences). 
Be warm but not pushy. Include specific value (not just "checking in").

Reply with ONLY the message text, no explanation."""

async def generate_followup_draft(
    opportunity: dict,
    customer_name: str,
    last_context: str,
    knowledge_context: str = "",
) -> str:
    """Generate a follow-up message draft using LLM.
    Falls back to a generic template if API unavailable."""
```

**Verification:**
```bash
.venv/bin/python -c "
import asyncio
from src.llm_client import generate_followup_draft
msg = asyncio.run(generate_followup_draft(
    {'name':'测试商机','stage':'technical_exchange'},
    '张总', '上次讨论了交期问题', ''
))
print(msg[:100])
"
```

---

## Phase C: 前端管道面板（5 tasks）

### Task C1: 管道面板 HTML 结构 + CSS

**Objective:** 在现有 SPA 中新增管道面板的 HTML + CSS

**Files:**
- Modify: `static/index.html`

**Step 1: 在 `#app` 中加面板容器**

```html
<!-- 管道面板 -->
<div id="pipeline-panel" class="hidden">
  <!-- 顶部工具栏 -->
  <div class="pipeline-toolbar">...</div>
  
  <!-- 商机表格（管理者视图） -->
  <div id="pipeline-table"></div>
  
  <!-- 商机详情 + 跟进项面板（业务员视图） -->
  <div id="opportunity-detail" class="hidden">
    <div id="followup-columns" class="followup-grid">...</div>
  </div>
</div>
```

**Step 2: CSS 变量和样式**

复用现有 design token（`--accent`, `--bg-surface`, `--radius-md` 等），新增管道专用变量：

```css
--col-todo: #71717a; --col-progress: #6c5ce7;
--col-review: #f97316; --col-done: #22c55e;
```

---

### Task C2: 管道面板 JS — 数据获取 + 渲染

**Objective:** 实现商机列表获取和表格渲染

**Files:**
- Modify: `static/index.html`（JS 部分）

**核心函数:**
```javascript
// 获取商机列表
async function loadPipeline() { ... }
// 渲染商机表格行
function renderOpportunityRow(opp) { ... }
// 计算管道统计
function calcPipelineStats(opps) { ... }
// SSE 事件处理 — 管道更新
function handlePipelineSSE(event) { ... }
```

---

### Task C3: 管道面板 JS — 商机详情 + 跟进项

**Objective:** 点击商机行展开跟进项四列面板

**核心函数:**
```javascript
// 加载商机详情（含跟进项）
async function loadOpportunityDetail(oppId) { ... }
// 渲染四列跟进项
function renderFollowupColumns(followups) { ... }
// 拖拽跟进项到不同列
function moveFollowup(followupId, newStatus) { ... }
```

---

### Task C4: 管道面板 JS — AI 起草 + 审核

**Objective:** 跟进项的 AI 起草和审核交互

**核心函数:**
```javascript
// 触发 AI 起草
async function draftFollowupMessage(followupId) { ... }
// 审核：批准/驳回
async function reviewFollowup(followupId, action) { ... }
// 发送消息
async function sendFollowupMessage(followupId) { ... }
```

---

### Task C5: 面板切换 + 收件箱→管道联动

**Objective:** 收件箱和管道面板之间的切换 + "加入跟进"按钮

**核心函数:**
```javascript
// 面板切换
function showPanel(panelName) { ... }  // inbox | pipeline | approvals
// 从消息创建跟进项
async function createFollowupFromMessage(messageId) { ... }
```

**在收件箱每条消息旁加按钮:**
```html
<button onclick="createFollowupFromMessage('msg_xxx')" class="btn-sm">+ 跟进</button>
```

---

## Phase D: 种子数据 + 部署验证（3 tasks）

### Task D1: 种子知识库初始化

**Objective:** 新租户注册或手动触发时填充 Tier 1 + Tier 2 基础知识

**Files:**
- Modify: `src/api/knowledge_routes.py`

```python
# POST /api/knowledge/seed 调用时:
# 1. 检查租户是否已有 Tier 1 知识（幂等）
# 2. 插入 ~15 条基础条目
```

---

### Task D2: 种子商机 + 模拟对话

**Objective:** 新租户首次打开管道面板时看到演示数据

**Files:**
- Modify: `src/api/opportunity_routes.py`

```python
# GET /api/opportunities?seed=true 或首次访问触发:
# 创建 3 个演示商机，含模拟消息和跟进项
# 每个演示商机标记 is_demo=True
# 用户点"转为真实数据"→ is_demo=False
```

---

### Task D3: 部署 + 全链路验证

**Objective:** 部署到 Docker 容器并验证全部功能

**Commands:**
```bash
# 1. 重启服务
cd /root/workspace/salesos-lite
.venv/bin/python -m uvicorn src.app:app --host 0.0.0.0 --port 8000 &

# 2. 验证 SPA
curl -s http://localhost:8000/ | grep -c 'pipeline-panel'
# Expected: > 0

# 3. 验证 API
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/opportunities -H "Authorization: Bearer $TOKEN"
# Expected: [] or seed data

curl -s http://localhost:8000/api/knowledge -H "Authorization: Bearer $TOKEN"
# Expected: [] or seed data

# 4. 检查 *** 注入
curl -s http://localhost:8000/ | grep -c '\*\*\*'
# Expected: 0

# 5. 验证模型
.venv/bin/python -c "from src.models import Opportunity, FollowupItem, FollowupEvent, KnowledgeEntry; print('All models OK')"
```

---

## 总 Task 数: 18

| Phase | Tasks | 预估时间 |
|-------|-------|---------|
| A — 数据模型 | 5 | 30 min |
| B — API 路由 | 5 | 45 min |
| C — 前端面板 | 5 | 60 min |
| D — 种子+部署 | 3 | 20 min |
| **合计** | **18** | **~2.5 h** |
