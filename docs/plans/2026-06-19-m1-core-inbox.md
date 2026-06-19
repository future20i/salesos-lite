# M1 核心收件箱 — 实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 构建基于 PostgreSQL 的 SaaS 统一收件箱核心——单租户可收发 Web/邮件渠道消息，看线索列表。

**Architecture:** FastAPI 单体 + PostgreSQL（asyncpg）+ RLS 租户隔离 + SSE 实时推送 + ai_jobs 异步队列。

**Tech Stack:** Python 3.11, FastAPI, asyncpg, SQLAlchemy 2.0 (async), pytest-asyncio, Mailgun Inbound Parse

---

## Phase 0: 基础设施

### Task 0.1: PostgreSQL 部署 + asyncpg 连接池

**Objective:** 安装 PostgreSQL，创建数据库，配置 asyncpg 连接池

**Files:**
- Create: `src/config.py`
- Modify: `requirements.txt`

**Step 1: 安装依赖**

```bash
cd /root/workspace/salesos-lite
.venv/bin/pip install asyncpg sqlalchemy[asyncio] pytest-asyncio httpx
```

**Step 2: 创建数据库**

```bash
sudo -u postgres psql -c "CREATE USER salesos WITH PASSWORD 'salesos_dev';"
sudo -u postgres psql -c "CREATE DATABASE salesos_lite OWNER salesos;"
sudo -u postgres psql -c "ALTER USER salesos CREATEDB;"  # for test DB creation
```

**Step 3: 写 config.py**

`src/config.py`:
```python
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://salesos:salesos_dev@localhost:5432/salesos_lite"
)
TEST_DATABASE_URL = DATABASE_URL.replace("salesos_lite", "salesos_lite_test")

# Connection pool settings
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "20"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
DB_POOL_HEALTH_THRESHOLD = 0.8  # 80% → degrade AI
DB_POOL_CRITICAL_THRESHOLD = 0.95  # 95% → 503
```

**Step 4: 验证连接**

```python
# verify_db.py — delete after running
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from src.config import DATABASE_URL

async def main():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        print("✅ PostgreSQL connected:", result.scalar())
    await engine.dispose()

asyncio.run(main())
```

Run: `.venv/bin/python verify_db.py`
Expected: `✅ PostgreSQL connected: 1`

### Task 0.2: 数据库会话工厂 + RLS 基础

**Objective:** 创建异步会话工厂，设置 tenant_id 的 PG 运行时参数

**Files:**
- Create: `src/database.py`
- Create: `tests/conftest.py`

**Step 1: 写 database.py**

`src/database.py`:
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import DATABASE_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW

engine = create_async_engine(
    DATABASE_URL,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

### Task 0.3: 测试基础设施

**Objective:** 创建异步测试 fixture（创建/销毁测试数据库）

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`

**Step 1: 写 conftest.py**

`tests/conftest.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from src.config import DATABASE_URL, TEST_DATABASE_URL
from src.models import Base

@pytest_asyncio.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh test DB with all tables for each test."""
    # Create test database
    engine = create_async_engine(
        DATABASE_URL.replace("salesos_lite", "postgres"),
        isolation_level="AUTOCOMMIT"
    )
    async with engine.connect() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS salesos_lite_test"))
        await conn.execute(text("CREATE DATABASE salesos_lite_test"))
    await engine.dispose()

    # Create tables
    test_engine = create_async_engine(TEST_DATABASE_URL)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await test_engine.dispose()
```

Run: `.venv/bin/pytest tests/ -v --tb=short`
Expected: 0 collected (no tests yet, but no import errors)

Commit:
```bash
git add src/ requirements.txt tests/
git commit -m "infra: PostgreSQL + asyncpg + async test fixtures"
```

---

## Phase 1: 数据模型（领域语言 v2）

### Task 1.1: Tenant + User 模型

**Objective:** 创建 Tenant 和 User 表，含密码哈希 + 角色

**Files:**
- Create: `src/models/__init__.py`
- Create: `src/models/tenant.py`
- Create: `src/models/user.py`

**Step 1: 写 Tenant 模型**

`src/models/tenant.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
```

**Step 2: 写 User 模型**

`src/models/user.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    REP = "rep"

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False, default=UserRole.REP)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
```

**Step 3: 验证表创建**

```bash
.venv/bin/python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from src.models.base import Base
from src.models.tenant import Tenant
from src.models.user import User
from src.config import TEST_DATABASE_URL

async def test():
    e = create_async_engine(TEST_DATABASE_URL)
    async with e.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    print('Tenant + User tables created')
    await e.dispose()
asyncio.run(test())
"
```
Expected: `Tenant + User tables created`

### Task 1.2: Lead + Message + Inquiry 模型

**Objective:** 创建线索、消息、询盘表

**Files:**
- Create: `src/models/lead.py`
- Create: `src/models/message.py`

`src/models/lead.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class LeadStatus(str, enum.Enum):
    NEW = "new"
    FOLLOWING = "following"
    QUOTED = "quoted"
    SAMPLED = "sampled"
    NEGOTIATING = "negotiating"
    CLOSED = "closed"

class Intent(str, enum.Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    DORMANT = "dormant"

class Channel(str, enum.Enum):
    WEB = "web"
    EMAIL = "email"
    WHATSAPP = "whatsapp"

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel), nullable=False, default=Channel.WEB)
    status: Mapped[LeadStatus] = mapped_column(SAEnum(LeadStatus), nullable=False, default=LeadStatus.NEW)
    intent: Mapped[Intent] = mapped_column(SAEnum(Intent), nullable=True)
    # Customer profile (AI-extracted)
    target_price: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inquired_sku: Mapped[str | None] = mapped_column(String(256), nullable=True)
    port: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    competitor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unread: Mapped[bool] = mapped_column(default=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])
    messages: Mapped[list["Message"]] = relationship(back_populates="lead", order_by="Message.created_at")
```

`src/models/message.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[MessageDirection] = mapped_column(
        SAEnum(MessageDirection), nullable=False, default=MessageDirection.INBOUND
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    lead: Mapped["Lead"] = relationship(back_populates="messages")
```

### Task 1.3: AI Jobs + Approval + Canned Response 模型

**Objective:** 创建剩余业务表

**Files:**
- Create: `src/models/ai_job.py`
- Create: `src/models/approval.py`
- Create: `src/models/canned_response.py`

`src/models/ai_job.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class AIJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"

class AIJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)  # "profile_extract", "intent_classify"
    status: Mapped[AIJobStatus] = mapped_column(
        SAEnum(AIJobStatus), nullable=False, default=AIJobStatus.PENDING
    )
    llm_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_tier: Mapped[str] = mapped_column(String(16), default="starter")
    result: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

`src/models/approval.py` (保留现有逻辑，加 tenant_id):
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
```

`src/models/canned_response.py`:
```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum

class ResponseCategory(str, enum.Enum):
    INQUIRY_REPLY = "inquiry_reply"
    QUOTATION_FOLLOWUP = "quotation_followup"
    SAMPLE_FOLLOWUP = "sample_followup"
    HOLIDAY_GREETING = "holiday_greeting"
    ORDER_NUDGE = "order_nudge"
    REVIVAL = "revival"

class CannedResponse(Base):
    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    category: Mapped[ResponseCategory] = mapped_column(
        SAEnum(ResponseCategory), nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

### Task 1.4: Base 模型 + models/__init__.py

**Objective:** 创建 SQLAlchemy DeclarativeBase + 统一导出

**Files:**
- Create: `src/models/base.py`
- Modify: `src/models/__init__.py`

`src/models/base.py`:
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

`src/models/__init__.py`:
```python
from src.models.base import Base
from src.models.tenant import Tenant
from src.models.user import User, UserRole
from src.models.lead import Lead, LeadStatus, Intent, Channel
from src.models.message import Message, MessageDirection
from src.models.ai_job import AIJob, AIJobStatus
from src.models.approval import Approval, ApprovalStatus
from src.models.canned_response import CannedResponse, ResponseCategory

__all__ = [
    "Base",
    "Tenant", "User", "UserRole",
    "Lead", "LeadStatus", "Intent", "Channel",
    "Message", "MessageDirection",
    "AIJob", "AIJobStatus",
    "Approval", "ApprovalStatus",
    "CannedResponse", "ResponseCategory",
]
```

**Step 2: 验证所有表创建**

```bash
.venv/bin/pytest tests/test_models.py -v
```

### Task 1.5: 写模型创建测试

**Objective:** TDD — 验证所有表可创建

**Files:**
- Create: `tests/test_models.py`

```python
import pytest
from sqlalchemy import text

@pytest.mark.asyncio
async def test_all_tables_created(db_session):
    """Verify all expected tables exist."""
    result = await db_session.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ))
    tables = [row[0] for row in result]
    expected = ["ai_jobs", "approvals", "canned_responses", "leads", "messages", "tenants", "users"]
    for t in expected:
        assert t in tables, f"Table {t} not found"

@pytest.mark.asyncio
async def test_tenant_creation(db_session):
    from src.models import Tenant
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.commit()
    assert tenant.id is not None
    assert tenant.name == "Test Corp"

@pytest.mark.asyncio
async def test_user_creation(db_session):
    from src.models import Tenant, User, UserRole
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        username="admin",
        email="admin@test.com",
        password_hash="hash123",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    assert user.tenant_id == tenant.id
    assert user.role == UserRole.ADMIN

@pytest.mark.asyncio
async def test_lead_creation(db_session):
    from src.models import Tenant, Lead, Channel, LeadStatus
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    lead = Lead(
        tenant_id=tenant.id,
        customer_name="Acme Inc",
        channel=Channel.EMAIL,
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    await db_session.commit()
    assert lead.customer_name == "Acme Inc"

@pytest.mark.asyncio
async def test_message_creation(db_session):
    from src.models import Tenant, Lead, Message, Channel, MessageDirection
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    lead = Lead(tenant_id=tenant.id, customer_name="Acme Inc", channel=Channel.WEB)
    db_session.add(lead)
    await db_session.flush()

    msg = Message(
        tenant_id=tenant.id,
        lead_id=lead.id,
        sender="customer@acme.com",
        content="Hi, I need a quote for 500 units.",
        direction=MessageDirection.INBOUND,
        channel="email",
    )
    db_session.add(msg)
    await db_session.commit()
    assert msg.lead_id == lead.id
```

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: 5 passed

Commit:
```bash
git add src/models/ tests/test_models.py
git commit -m "feat: PostgreSQL models — Tenant, User, Lead, Message, AIJob, Approval, CannedResponse"
```

---

## Phase 2: RLS 租户隔离

### Task 2.1: RLS 策略 + 审计脚本

**Objective:** 所有业务表启用 RLS，CI 审计脚本

**Files:**
- Create: `src/rls.py`
- Create: `scripts/audit_rls.py`

**Step 1: 写 RLS 策略函数**

`src/rls.py`:
```python
"""Row-Level Security — every business table must enable RLS."""

AUDIT_QUERY = """
SELECT relname FROM pg_class
WHERE relkind = 'r'
  AND relrowsecurity = false
  AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
  AND relname NOT LIKE 'pg_%'
  AND relname NOT LIKE 'alembic_%';
"""

POLICY_SQL = """
CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
"""

BUSINESS_TABLES = [
    "users", "leads", "messages", "ai_jobs",
    "approvals", "canned_responses",
]

async def enable_rls_for_all(conn):
    """Enable RLS + create policies on all business tables."""
    for table in BUSINESS_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        # Drop existing policy first (idempotent)
        try:
            await conn.execute(text(f"DROP POLICY tenant_isolation ON {table}"))
        except Exception:
            pass
        await conn.execute(text(POLICY_SQL.format(table=table)))

async def verify_rls(conn) -> list[str]:
    """Return list of tables WITHOUT RLS. Empty = pass."""
    result = await conn.execute(text(AUDIT_QUERY))
    return [row[0] for row in result]
```

**Step 2: 写审计脚本**

`scripts/audit_rls.py`:
```python
#!/usr/bin/env python
"""CI audit: check all business tables have RLS enabled. Non-zero exit on failure."""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from src.rls import verify_rls
from src.config import DATABASE_URL

async def main():
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        missing = await verify_rls(conn)
        if missing:
            print(f"❌ RLS not enabled on: {missing}")
            sys.exit(1)
        print("✅ All business tables have RLS enabled")
    await engine.dispose()

asyncio.run(main())
```

### Task 2.2: 中间件强制 tenant_id

**Objective:** FastAPI 中间件从 JWT 提取 tenant_id，设置为 PG 运行时参数

**Files:**
- Create: `src/middleware.py`

`src/middleware.py`:
```python
import uuid
from fastapi import Request, HTTPException
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def tenant_context_middleware(request: Request, call_next):
    """Extract tenant_id from JWT claims, set PG runtime parameter."""
    # Public endpoints skip tenant context
    if request.url.path in ["/api/health", "/api/auth/register", "/api/auth/login"]:
        return await call_next(request)

    tenant_id = request.state.tenant_id if hasattr(request.state, "tenant_id") else None
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Tenant context required")

    # Set PG runtime parameter for RLS
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        await session.commit()

    response = await call_next(request)
    return response
```

### Task 2.3: RLS 集成测试

**Objective:** TDD — 验证租户 A 不能看到租户 B 的数据

**Files:**
- Create: `tests/test_rls.py`

```python
import pytest
from sqlalchemy import text

@pytest.mark.asyncio
async def test_rls_all_tables_enabled(db_session):
    """After init, all business tables must have RLS."""
    from src.rls import verify_rls
    missing = await verify_rls(db_session)
    assert missing == [], f"Missing RLS on: {missing}"

@pytest.mark.asyncio
async def test_tenant_isolation_leads(db_session):
    """Tenant A's leads are invisible to Tenant B via RLS."""
    from src.models import Tenant, Lead, Channel
    from src.rls import enable_rls_for_all

    # Create two tenants
    ta = Tenant(name="A Corp")
    tb = Tenant(name="B Corp")
    db_session.add_all([ta, tb])
    await db_session.flush()
    await enable_rls_for_all(db_session)

    # Create lead for tenant A
    lead_a = Lead(tenant_id=ta.id, customer_name="A Customer", channel=Channel.WEB)
    db_session.add(lead_a)
    await db_session.commit()

    # Set context to tenant B — should see 0 leads
    await db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(tb.id)},
    )
    result = await db_session.execute(text("SELECT count(*) FROM leads"))
    count = result.scalar()
    assert count == 0, f"Tenant B should see 0 leads, got {count}"

    # Set context to tenant A — should see 1
    await db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(ta.id)},
    )
    result = await db_session.execute(text("SELECT count(*) FROM leads"))
    count = result.scalar()
    assert count == 1, f"Tenant A should see 1 lead, got {count}"
```

Run: `.venv/bin/pytest tests/test_rls.py -v`
Expected: 2 passed

Commit:
```bash
git add src/rls.py src/middleware.py scripts/ tests/test_rls.py
git commit -m "feat: RLS tenant isolation + middleware + audit script"
```

---

## Phase 3: Auth

### Task 3.1: 密码哈希 + JWT

**Objective:** hashlib 密码哈希 + PyJWT token 生成/验证

**Files:**
- Create: `src/auth.py`
- Create: `tests/test_auth.py`

`src/auth.py`:
```python
import hashlib, os, jwt, uuid
from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models import User, UserRole

SECRET = os.environ.get("JWT_SECRET", hashlib.sha256(os.urandom(64)).hexdigest())
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer()

def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return salt.hex() + ":" + key.hex()

def verify_password(password: str, stored: str) -> bool:
    salt_hex, key_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    key = bytes.fromhex(key_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000) == key

def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(
    request: Request,
    credentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    request.state.tenant_id = user.tenant_id
    return user

def require_role(*roles: UserRole):
    async def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker
```

### Task 3.2: Auth API 端点 + 刷新 SSE token

**Objective:** 注册、登录、获取当前用户

**Files:**
- Create: `src/api/__init__.py`
- Create: `src/api/auth_routes.py`

`src/api/auth_routes.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from src.database import get_db
from src.models import Tenant, User, UserRole
from src.auth import hash_password, verify_password, create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    company_name: str
    username: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    token: str
    user: dict

@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Create tenant
    tenant = Tenant(name=req.company_name)
    db.add(tenant)
    await db.flush()
    # Create admin user
    try:
        user = User(
            tenant_id=tenant.id,
            username=req.username,
            email=req.email,
            password_hash=hash_password(req.password),
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")

    token = create_token(user)
    return TokenResponse(token=token, user={"id": str(user.id), "username": user.username, "role": user.role.value})

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user)
    return TokenResponse(token=token, user={"id": str(user.id), "username": user.username, "role": user.role.value})

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "username": user.username, "role": user.role.value, "tenant_id": str(user.tenant_id)}
```

### Task 3.3: Auth 集成测试

**Objective:** TDD — 注册 → 登录 → 获取当前用户

**Files:**
- Create: `tests/test_auth_api.py`

```python
import pytest
from httpx import AsyncClient, ASGITransport
from src.app import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_register_and_login(client, db_session):
    # Register
    resp = await client.post("/api/auth/register", json={
        "company_name": "Test Corp",
        "username": "admin",
        "email": "admin@test.com",
        "password": "secret123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["role"] == "admin"

    # Login
    resp = await client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "secret123",
    })
    assert resp.status_code == 200

    # Me
    token = resp.json()["token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"

@pytest.mark.asyncio
async def test_duplicate_email_rejected(client, db_session):
    await client.post("/api/auth/register", json={
        "company_name": "A", "username": "a", "email": "dup@test.com", "password": "x",
    })
    resp = await client.post("/api/auth/register", json={
        "company_name": "B", "username": "b", "email": "dup@test.com", "password": "y",
    })
    assert resp.status_code == 409

@pytest.mark.asyncio
async def test_wrong_password_rejected(client, db_session):
    await client.post("/api/auth/register", json={
        "company_name": "X", "username": "x", "email": "x@test.com", "password": "correct",
    })
    resp = await client.post("/api/auth/login", json={
        "email": "x@test.com", "password": "wrong",
    })
    assert resp.status_code == 401
```

Run: `.venv/bin/pytest tests/test_auth_api.py -v`
Expected: 3 passed

Commit:
```bash
git add src/auth.py src/api/ tests/test_auth_api.py
git commit -m "feat: JWT auth — register, login, me, role-based access"
```

---

## Phase 4: 渠道适配器

### Task 4.1: Web 渠道（HTTP API 接收消息）

**Objective:** 匿名客户通过 POST 发消息 → 自动创建 Lead + Message

**Files:**
- Create: `src/api/inbox_routes.py`
- Create: `tests/test_inbox_api.py`

`src/api/inbox_routes.py`:
```python
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.models import Lead, Message, LeadStatus, Intent, Channel, MessageDirection, AIJob
from src.auth import get_current_user, require_role
from src.models.user import User, UserRole

router = APIRouter(prefix="/api/inbox", tags=["inbox"])

class InboundMessage(BaseModel):
    customer_name: str
    content: str
    channel: str = "web"
    channel_message_id: str | None = None

@router.post("/incoming")
async def receive_inbound(msg: InboundMessage, db: AsyncSession = Depends(get_db)):
    """Public endpoint — customer sends a message. Creates Lead if new."""
    # Find or create lead by customer_name (simplified — real impl would match by email/phone)
    result = await db.execute(
        select(Lead).where(Lead.customer_name == msg.customer_name).order_by(Lead.created_at.desc()).limit(1)
    )
    lead = result.scalar_one_or_none()

    if lead is None:
        lead = Lead(
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # FIXME: resolve tenant from channel config
            customer_name=msg.customer_name,
            channel=Channel(msg.channel),
            status=LeadStatus.NEW,
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(lead)
        await db.flush()
    else:
        lead.last_activity_at = datetime.now(timezone.utc)
        lead.unread = True

    message = Message(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        sender=msg.customer_name,
        content=msg.content,
        direction=MessageDirection.INBOUND,
        channel=msg.channel,
        channel_message_id=msg.channel_message_id,
    )
    db.add(message)
    await db.flush()

    # Enqueue AI extraction job
    ai_job = AIJob(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        message_id=message.id,
        job_type="profile_extract",
        status="pending",
    )
    db.add(ai_job)
    await db.commit()

    # Trigger SSE (phase 4.3)
    # await sse_broadcast(lead.tenant_id, {"type": "new_message", "lead_id": str(lead.id)})

    return {"lead_id": str(lead.id), "message_id": str(message.id)}

@router.get("/leads")
async def list_leads(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List leads visible to current user."""
    query = select(Lead).order_by(Lead.last_activity_at.desc())
    if user.role == UserRole.REP:
        query = query.where(Lead.assigned_to == user.id)
    result = await db.execute(query)
    leads = result.scalars().all()
    return [
        {
            "id": str(l.id),
            "customer_name": l.customer_name,
            "channel": l.channel.value,
            "status": l.status.value,
            "intent": l.intent.value if l.intent else None,
            "unread": l.unread,
            "last_activity_at": l.last_activity_at.isoformat(),
        }
        for l in leads
    ]

@router.get("/leads/{lead_id}")
async def get_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404)
    # Mark as read
    lead.unread = False
    await db.commit()
    return {
        "id": str(lead.id),
        "customer_name": lead.customer_name,
        "channel": lead.channel.value,
        "status": lead.status.value,
        "intent": lead.intent.value if lead.intent else None,
        "target_price": lead.target_price,
        "inquired_sku": lead.inquired_sku,
        "port": lead.port,
        "messages": [
            {"id": str(m.id), "sender": m.sender, "content": m.content, "direction": m.direction.value, "created_at": m.created_at.isoformat()}
            for m in lead.messages
        ],
    }
```

**Step 2: 写测试**

```python
@pytest.mark.asyncio
async def test_receive_inbound_creates_lead(client, db_session):
    resp = await client.post("/api/inbox/incoming", json={
        "customer_name": "John Doe",
        "content": "Hi, interested in your product.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "lead_id" in data
    # Verify lead created
    from src.models import Lead
    result = await db_session.execute(select(Lead).where(Lead.id == data["lead_id"]))
    lead = result.scalar_one()
    assert lead.customer_name == "John Doe"
    assert len(lead.messages) == 1
```

Run: `.venv/bin/pytest tests/test_inbox_api.py -v`
Expected: 1+ passed

### Task 4.2: Mailgun Inbound Parse 适配器

**Objective:** 接收 Mailgun webhook → 解析邮件 → 创建 Message

**Files:**
- Create: `src/api/channel_routes.py`

`src/api/channel_routes.py`:
```python
from fastapi import APIRouter, Request, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.api.inbox_routes import receive_inbound

router = APIRouter(prefix="/api/channels", tags=["channels"])

@router.post("/mailgun/inbound")
async def mailgun_inbound(
    request: Request,
    sender: str = Form(...),
    subject: str = Form(""),
    body_plain: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Mailgun inbound parse webhook."""
    # Extract customer name from sender email
    customer_name = sender.split("@")[0] if "@" in sender else sender
    content = f"Subject: {subject}\n\n{body_plain}" if subject else body_plain

    return await receive_inbound(
        msg=type('obj', (object,), {
            "customer_name": customer_name,
            "content": content[:5000],  # Truncate long emails
            "channel": "email",
            "channel_message_id": request.headers.get("X-Mailgun-Message-Id", ""),
        }),
        db=db,
    )
```

### Task 4.3: SSE 实时推送

**Objective:** Server-Sent Events 推送新消息给前端

**Files:**
- Modify: `src/api/inbox_routes.py` — 加 SSE endpoint
- Create: `src/sse.py`

`src/sse.py`:
```python
import asyncio, json, uuid
from collections import defaultdict
from fastapi.responses import StreamingResponse

# In-memory per-tenant event queues (prod: use PG LISTEN/NOTIFY)
_queues: dict[uuid.UUID, asyncio.Queue] = defaultdict(asyncio.Queue)

async def sse_broadcast(tenant_id: uuid.UUID, event: dict):
    """Push event to all SSE listeners for this tenant."""
    await _queues[tenant_id].put(json.dumps(event))

async def sse_endpoint(tenant_id: uuid.UUID, request):
    """SSE stream for a tenant."""
    queue = _queues[tenant_id]
    async def event_generator():
        # Send heartbeat every 30s
        heartbeat_task = None
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            pass
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Add to `src/api/inbox_routes.py`:
```python
@router.get("/stream")
async def stream(user: User = Depends(get_current_user), request: Request = None):
    from src.sse import sse_endpoint
    return await sse_endpoint(user.tenant_id, request)
```

---

## Phase 5: AI Pipeline

### Task 5.1: AI Job 轮询 + 脱敏 + 幂等

**Objective:** 后台任务轮询 ai_jobs → 脱敏 → 调 LLM → 写画像

**Files:**
- Create: `src/ai_pipeline.py`
- Create: `src/sanitize.py`

`src/sanitize.py`:
```python
import re
from typing import Dict

PLACEHOLDERS = {
    "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    "phone": r'\+?[\d\s\-()]{7,}',
    "url": r'https?://[^\s]+',
}

def sanitize(text: str, rules: Dict[str, str] | None = None) -> tuple[str, dict]:
    """Replace sensitive fields with placeholders. Returns (sanitized, mapping)."""
    mapping = {}
    rules = rules or PLACEHOLDERS
    idx = 0
    for field_type, pattern in rules.items():
        for match in re.finditer(pattern, text):
            placeholder = f"[{field_type.upper()}_{idx}]"
            mapping[placeholder] = match.group()
            idx += 1
        text = re.sub(pattern, lambda m, ft=field_type: f"[{ft.upper()}_{sum(1 for _ in re.finditer(pattern, text[:m.start()]))}]", text)
    # Simpler approach:
    result = text
    mapping = {}
    for field_type, pattern in rules.items():
        matches = list(re.finditer(pattern, result))
        for i, match in enumerate(reversed(matches)):  # reversed to preserve indices
            placeholder = f"[{field_type.upper()}_{i}]"
            mapping[placeholder] = match.group()
            result = result[:match.start()] + placeholder + result[match.end():]
    return result, mapping

def desanitize(text: str, mapping: dict) -> str:
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text
```

`src/ai_pipeline.py`:
```python
import asyncio, uuid
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import AsyncSessionLocal
from src.models import AIJob, AIJobStatus, Lead, Message
from src.sanitize import sanitize, desanitize

# Per-tier rate limits (jobs per minute)
RATE_LIMITS = {"starter": 5, "growth": 20, "pro": 60}

async def poll_and_process():
    """Background loop — poll ai_jobs, process with LLM."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                # Claim next job (SKIP LOCKED)
                result = await db.execute(
                    select(AIJob)
                    .where(AIJob.status == AIJobStatus.PENDING)
                    .order_by(AIJob.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                job = result.scalar_one_or_none()
                if job is None:
                    await db.commit()
                    await asyncio.sleep(1)
                    continue

                # Check rate limit
                # (simplified — prod would tally per-tenant consumption)
                # Mark processing
                job.status = AIJobStatus.PROCESSING
                job.locked_at = datetime.now(timezone.utc)
                await db.commit()

                try:
                    # Fetch message
                    msg_result = await db.execute(select(Message).where(Message.id == job.message_id))
                    message = msg_result.scalar_one()

                    # Sanitize
                    clean_text, mapping = sanitize(message.content)

                    # Call LLM (placeholder — real implementation deferred to M3)
                    # For M1, just mark done so the pipeline is wired
                    profile_data = {"intent": "cold", "note": "LLM integration deferred to M3"}

                    # Desanitize result
                    result_text = desanitize(str(profile_data), mapping)

                    # Write to lead
                    await db.execute(
                        update(Lead)
                        .where(Lead.id == job.lead_id)
                        .values(
                            intent=profile_data.get("intent"),
                        )
                    )

                    job.status = AIJobStatus.DONE
                    job.result = result_text
                    await db.commit()

                except Exception as e:
                    job.retry_count += 1
                    job.status = AIJobStatus.PENDING if job.retry_count < 3 else AIJobStatus.FAILED
                    job.result = str(e)[:1000]
                    await db.commit()

        except Exception as e:
            print(f"AI pipeline error: {e}")
            await asyncio.sleep(5)

async def recover_stale_jobs():
    """Reset jobs locked > 5 minutes back to pending."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                cutoff = datetime.now(timezone.utc).replace(minute=datetime.now(timezone.utc).minute - 5)
                await db.execute(
                    update(AIJob)
                    .where(AIJob.status == AIJobStatus.PROCESSING, AIJob.locked_at < cutoff)
                    .values(status=AIJobStatus.PENDING, locked_at=None)
                )
                await db.commit()
        except Exception as e:
            print(f"Stale job recovery error: {e}")
        await asyncio.sleep(60)
```

---

## Phase 6: 连接池健康检查

### Task 6.1: 连接池监控 + 降级

**Objective:** 每 30 秒检查连接池使用率，>80% 降级 AI，>95% 返回 503

**Files:**
- Create: `src/health.py`

`src/health.py`:
```python
from fastapi import HTTPException
from src.database import engine
from src.config import DB_POOL_HEALTH_THRESHOLD, DB_POOL_CRITICAL_THRESHOLD

# Global degradation flag
ai_degraded = False

async def check_pool_health():
    """Called by background task every 30s."""
    global ai_degraded
    pool = engine.pool
    if hasattr(pool, "size"):
        used = pool.size() - pool.freesize() if hasattr(pool, "freesize") else 0
        ratio = used / pool.size() if pool.size() > 0 else 0
        if ratio > DB_POOL_CRITICAL_THRESHOLD:
            raise HTTPException(status_code=503, detail="Database overloaded")
        ai_degraded = ratio > DB_POOL_HEALTH_THRESHOLD

async def health_endpoint():
    pool = engine.pool
    status = {"status": "healthy"}
    if hasattr(pool, "size") and hasattr(pool, "freesize"):
        status["pool_used"] = pool.size() - pool.freesize()
        status["pool_total"] = pool.size()
    return status
```

---

## Phase 7: App 组装 + 端到测试

### Task 7.1: 组装 FastAPI app

**Objective:** 替换现有 app.py，挂载所有路由 + 中间件 + 启动任务

**Files:**
- Replace: `src/app.py` (rename old to `app.py.bak`)

`src/app.py`:
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from src.database import engine, AsyncSessionLocal
from src.models.base import Base
from src.rls import enable_rls_for_all
from src.middleware import tenant_context_middleware
from src.api.auth_routes import router as auth_router
from src.api.inbox_routes import router as inbox_router
from src.api.channel_routes import router as channel_router
from src.health import health_endpoint
from src.ai_pipeline import poll_and_process, recover_stale_jobs

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables + enable RLS
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await enable_rls_for_all(conn)
    # Start background tasks
    asyncio.create_task(poll_and_process())
    asyncio.create_task(recover_stale_jobs())
    yield
    await engine.dispose()

app = FastAPI(title="SalesOS Lite", version="0.2.0", lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(tenant_context_middleware)

# Routes
app.include_router(auth_router)
app.include_router(inbox_router)
app.include_router(channel_router)
app.get("/api/health")(health_endpoint)
```

### Task 7.2: M1 验收测试（全量）

**Objective:** 运行 M1 验收清单中的 9 项检查

**Files:**
- Create: `tests/test_m1_acceptance.py`

```python
import pytest

@pytest.mark.asyncio
async def test_m1_smoke(client, db_session):
    """M1 acceptance test — full flow."""
    # 1. Register
    resp = await client.post("/api/auth/register", json={
        "company_name": "Acme", "username": "boss", "email": "boss@acme.com", "password": "x",
    })
    assert resp.status_code == 200
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Incoming message creates lead
    resp = await client.post("/api/inbox/incoming", json={
        "customer_name": "Buyer Inc", "content": "I need 1000 units FOB Shanghai.",
    })
    assert resp.status_code == 200

    # 3. Leads list
    resp = await client.get("/api/inbox/leads", headers=headers)
    assert resp.status_code == 200
    leads = resp.json()
    assert len(leads) > 0
    assert leads[0]["customer_name"] == "Buyer Inc"

    # 4. Health
    resp = await client.get("/api/health")
    assert resp.status_code == 200

    # 5. RLS audit (via test helpers)
    from src.rls import verify_rls
    missing = await verify_rls(db_session)
    assert missing == [], f"RLS not enabled on: {missing}"
```

Run: `.venv/bin/pytest tests/test_m1_acceptance.py -v`
Expected: 1 passed (smoke test covering channels 1-4)

---

## 验证命令

完成所有 Phase 后：

```bash
# Run all tests
.venv/bin/pytest tests/ -v --tb=short

# RLS audit
.venv/bin/python scripts/audit_rls.py

# Start server
.venv/bin/python -m uvicorn src.app:app --host 0.0.0.0 --port 8000

# Smoke test
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Test","username":"boss","email":"boss@test.com","password":"x"}'

curl -X POST http://localhost:8000/api/inbox/incoming \
  -H "Content-Type: application/json" \
  -d '{"customer_name":"Buyer","content":"Hello"}'
```

---

## M1 验收清单

- [ ] `POST /api/inbox/incoming` 写入数据库并返回 201
- [ ] Mailgun Inbound Parse → 自动创建 Lead + Message
- [ ] `GET /api/inbox/leads` 按租户过滤，返回线索列表含状态
- [ ] SSE `/api/inbox/stream` 推送新消息给同租户已认证用户
- [ ] 所有业务表启用 RLS（`scripts/audit_rls.py` 返回 0 行）
- [ ] 租户 A 的 API 请求无法访问租户 B 的数据（集成测试）
- [ ] `ai_jobs` 表轮询 + 脱敏 + 5 分钟超时重置 + 幂等保护
- [ ] 线索列表看板显示：总量、新询盘、意向分布
- [ ] PostgreSQL 连接池健康检查就绪（>80% →降级 AI）
