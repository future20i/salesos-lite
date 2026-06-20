# Final Architecture Review — SalesOS Lite v2.0

> **Reviewer:** Senior Product Architect (fresh eyes)
> **Date:** 2026-06-20
> **Documents reviewed:** CONTEXT.md, Pipeline Spec v2.0, ADR-0001–0006, ADR-0001-postgresql, DESIGN.md
> **Posture:** Critical. Not nice. Finding what the original team missed.

---

## 1. INTERNAL CONTRADICTIONS

### 🔴 CRITICAL: SQLite vs PostgreSQL — Conflicting Database Decisions

**ADR-0001-postgresql** states: PostgreSQL is the **only** infrastructure dependency. No Redis, no Celery, no separate worker. One database for everything.

**ADR-0004** states: "Phase 1 使用 SQLite 表存知识库条目" (use SQLite tables for knowledge base).

**Spec Section 6** lists: `SQLite check_same_thread=False` as a design constraint.

**Spec Section 2.6** says: Tier 3 knowledge lives in "SQLite 表".

**These cannot all be true.** Either:
- (a) The app runs PostgreSQL but has a parallel SQLite database for knowledge — which violates ADR-0001-postgresql's "only dependency" claim and means two databases to manage, backup, and migrate.
- (b) The entire app uses SQLite under the hood — in which case ADR-0001-postgresql is actively misleading and its scaling claims (LISTEN/NOTIFY, pgbouncer, RLS) don't apply.
- (c) The SQLite references are stale copy-paste — in which case the knowledge base has no defined storage.

**Impact:** A developer building this today would not know which database to use. If both are started, they have two separate connection pools, two migration paths, and cross-database queries become impossible (e.g., joining knowledge entries to tenant data).

### 🟡 DESIGN.md Fonts vs Spec Design Constraint

**DESIGN.md Section "Typography"** specifies: Primary font = Geist (Google Fonts CDN), Mono = Geist Mono.

**Spec Section 6** mandates: "字体：system-ui，不用 Google Fonts" (use system-ui, no Google Fonts).

This is a direct contradiction. The DESIGN.md was presumably written first; the spec constraint was added after the Pitfall experience. But the DESIGN.md was never updated.

**Impact:** If a frontend developer follows DESIGN.md, they'll import Google Fonts and trigger the `***` injection pitfall. If they follow the spec, the design system is wrong.

### 🟡 CONTEXT.md Defines "Project" — ADR-0003 Explicitly Rejects It

**CONTEXT.md lines 93-101** define `Project` as a first-class domain concept with milestones, deliverables, and timeline.

**ADR-0003** decides: "签约后的 Project 不建独立表——仅作为 Opportunity.stage = 'won' 的状态标记" (no standalone Project table — just a status marker).

This means the domain language document defines a concept the architecture explicitly decided NOT to implement. Every new team member who reads CONTEXT.md will expect a projects table. The spec's Section 2.3 diagram also shows the chain ending at 跟进项 without Project, but CONTEXT.md hasn't been updated.

### 🟡 OpportunityStage Enum Contains Unreachable States

**Spec Section 3.1** defines the flow: `线索验证 → 需求确认 → 技术交流 → 报价/谈判 → 合同 → 成交`

But the `OpportunityStage` enum includes `LOST` and `SHELVED` — terminal states not in the flow. There's no API endpoint for marking an opportunity as lost or shelved (`PATCH /api/opportunities/:id` with `stage=lost` would work, but no dedicated endpoint or validation logic is defined). There's also no definition of what happens to followup items when an opportunity goes LOST/SHELVED.

### 🟡 Tier 2: Tenant Editable vs Brain-Managed Conflict

**Spec Section 2.6** says Tier 2 is "B2BSaleOS 维护，租户可编辑" (maintained by B2BSaleOS, tenant-editable).

**ADR-0005** says: "下行知识更新有本地副本，大脑不可用时使用最后同步版本" (brain pushes knowledge updates to local copies).

**What happens when:** The tenant edits a Tier 2 entry, and then the brain pushes an updated version that overwrites the tenant's edit? There is no conflict resolution mechanism, no merge strategy, and no versioning on knowledge entries. This is a guaranteed data loss scenario.

---

## 2. MISSING EDGE CASES

### 🔴 No "N" Defined for Silence Detection

The spec says "超 N 天无回复" (exceed N days without reply) — but N is never defined. Is it 3 days? 7? 14? Configurable per tenant? Per opportunity stage? Different N for different customer tiers? Without defining N, the entire silence diagnosis feature is vapor.

### 🔴 No Error Handling for AI Failures

The LLM API will fail. It will return malformed JSON. It will hallucinate. It will time out. It will hit rate limits. The spec's Section 6 says "LLM 优雅降级：API 不可用时退回规则引擎" — but **no rule engine is defined anywhere in any of these documents**. There is no fallback behavior specified for:

- What happens when silence diagnosis returns garbage?
- What happens when AI drafting generates a message that makes no sense?
- What happens when the AI classifies a `routine` message as `critical` (or vice versa)?
- What happens when DeepSeek API returns a 429 rate limit?

The "rule engine" is a phantom — it's invoked as a safety net but doesn't exist.

### 🔴 No Notification Delivery Mechanism

The spec says silence diagnosis results are pushed via SSE (Section 4.4). But:

1. What if the user is logged out? Is there an email/webhook/push notification fallback?
2. What if the SSE connection drops mid-push?
3. Are diagnosis results persisted so they survive browser refresh?
4. How does the rep know a diagnosis has been made without actively watching?

The AI could diagnose a critical churn risk at 2am, and the rep might not see it until they log in at 9am. By then the customer has signed with a competitor.

### 🟡 Quick Capture: No Error Recovery for Voice

The voice → text → structured followup pipeline has compounding error rates:

1. Acoustic errors (background noise in trade show / factory floor)
2. Transcription errors (Chinese-accented English, mixed Chinese-English speech, technical terms like "飞轮UPS")
3. AI extraction errors (misidentifying action items, wrong customer association)

There's no defined: review step before the followup item enters the pipeline, correction flow for wrong transcription, or fallback to manual text input when voice fails.

### 🟡 Duplicate Customer Detection Across Channels

A lead might reach out via WhatsApp, then email, then a trade show meeting. The spec has no deduplication logic. Three separate Lead records get created. The rep now manages three "different" customers who are the same person.

### 🟡 Concurrent Editing / Assignment Conflicts

No mechanism for: two reps claiming the same lead, a rep updating an opportunity while the manager reassigns it, the AI drafting a message while the rep manually edits the same followup item.

### 🟡 Timezone Blindness in Silence Detection

Chinese manufacturers dealing with US/European clients: "3 days without reply" means very different things when one party is asleep for 8 of those hours. No timezone field exists in the data model. A Friday evening message from a US client shouldn't trigger a silence alert by Monday morning China time.

### 🟡 Seed Pipeline: No Restore After Clear

Section 2.8 says the seed pipeline can be "一键清除" (one-click clear). What if the admin accidentally clears it? No undo or restore. The spec says it's "演示商机" (demo opportunities) but doesn't flag them as demo vs real data, meaning a cleared seed pipeline is gone forever.

---

## 3. OVER-ENGINEERED FEATURES (should be cut from Phase 1)

### 🔴 Multi-Version AI Message Tones (简练/详细/催促)

Section 2.7: "多版本切换（简练/详细/催促）" — generating three tone variants per message and letting the rep switch between them.

**Why cut:** This triples the AI API calls per message draft. It adds UI complexity (tone selector, preview switching). It assumes the AI can reliably produce meaningfully different tones for the same content in Chinese business context. And the rep will almost always pick the first version anyway.

**Recommendation:** Ship one tone per draft in Phase 1. Add variants in Phase 2 only if user feedback demands it.

### 🟡 Competitor Tracking JSON (competitor_tracking)

Section 3.1: Structured JSON array `[{name, mentioned_at, context, our_response}]` for tracking competitor mentions.

**Why cut:** Phase 2 already lists "竞品信号自动提取（从对话中识别竞品提及）" as a planned feature. Building the data structure in Phase 1 without the automatic extraction means this field will be empty or manually populated. Manual competitor tracking in a JSON blob is worse than a text note — it creates structured data that's wrong.

**Recommendation:** Either ship the auto-extraction in Phase 1 (if it's critical), or defer the entire competitor_tracking field to Phase 2.

### 🟡 Decision Chain JSON (decision_chain)

Same issue as competitor_tracking. Phase 2 lists "决策链进度追踪". Don't build the data structure without the intelligence to populate it.

### 🟡 KnowledgeEntry.embedding Field in Phase 1 Model

Section 3.4: `embedding (可空, Phase 2)` — the field exists in the Phase 1 schema but is only used in Phase 2. This is premature schema design. Add the column via migration in Phase 2 when it's actually needed.

### 🟡 AI Auto-Judging review_level

ADR-0002 says "AI 自动判断 review_level" (AI automatically judges the review level). This requires the AI to classify every message as routine/commercial/critical. But:

1. The AI has no concept of the financial stakes involved
2. A message that looks "routine" might mention a price in a way the AI doesn't catch
3. The consequences of misclassification are severe: a `commercial` message auto-sent as `routine` could lose a deal

**Recommendation:** Start with everything as `commercial` (human-reviewed). After collecting real-world data, use simple keyword-based rules for `routine` classification. Don't rely on AI for this gatekeeping decision in Phase 1.

---

## 4. MISSING FEATURES THAT WILL CAUSE REAL PROBLEMS

### 🔴 Phase 1 Needs: Search/Filter Across Opportunities

The pipeline API has `GET /api/opportunities` but defines no query parameters. A sales manager with 50+ active opportunities needs to filter by: assigned rep, stage, value range, expected close date, customer name. Without filtering, the pipeline view is a dump of all data — useless for management.

### 🔴 Phase 1 Needs: Basic Metrics Dashboard

The spec says "管理者视图" (manager view) — but this is just the pipeline table. A manager needs:

- How many opportunities at each stage? (funnel)
- Which reps have opportunities stuck in one stage too long?
- Conversion rate from stage to stage
- Average time in each stage

Without even basic metrics, the "manager view" is just a sorted list. A manager will export to Excel day one and never use the pipeline view again.

### 🟡 Phase 1 Needs: Duplicate Lead Detection

With 5+ channels (WhatsApp, email, Facebook, web, offline), the same person WILL appear in multiple channels. Without deduplication, reps will send conflicting messages to the same customer thinking they're different leads. This is embarrassing and erodes trust.

**Minimum viable:** Phone number or email matching across leads. Flag potential duplicates for manual merge.

### 🟡 Phase 1 Needs: Bulk Operations

A rep returning from a trade show has 30 new leads. They need to: assign all to themselves, set all to "following" status, add a bulk note. Without bulk operations, this is 30 × N clicks of manual data entry — exactly the friction the product was designed to eliminate.

### 🟡 Phase 1 Needs: Opportunity Deletion/Archival

The API has POST/PATCH/GET for opportunities but no DELETE. What happens to test data, duplicate entries, or opportunities that were created by mistake? The `SHELVED` status exists but there's no way to actually remove data.

### 🟡 Phase 1 Needs: Data Export

A Chinese factory manager will demand: "给我导出一份这个月的商机报表" (export this month's opportunity report). Without CSV/Excel export, they'll abandon the system for their existing Excel workflow.

---

## 5. UNREALISTIC ASSUMPTIONS

### 🔴 Assumption: AI Can Reliably Diagnose Silence Causes

The spec says AI will diagnose silence as: normal process → competitor threat → forgotten → churn risk. This is a **mind-reading problem**, not a classification problem.

Real silence reasons the AI cannot detect:
- Customer's boss vetoed the project (never mentioned in chat)
- Customer's company got acquired / reorganized
- Customer had a personal emergency
- Customer is testing your responsiveness by staying silent (a real procurement tactic)
- Customer is waiting for their own customer's decision

The AI only has the chat history. It will confidently classify "internal approval delay" when the real reason is "they chose a competitor last week and didn't tell us." The confidence scores will train reps to trust wrong diagnoses.

### 🔴 Assumption: "Trust Stock" Is Meaningful Without Measurement

CONTEXT.md defines "客户信任存量" as "隐含状态" (implicit state) that "通过历史成交、回复速度、沟通质量等因素反映在 AI 的决策建议中." This is a dangerous abstraction:

1. It's not measured — it's "implicit"
2. It affects AI decisions without being inspectable
3. The AI's interpretation of trust is a black box
4. "换人后可能归零" (resets when the rep changes) — but how does the AI know the rep changed?

If trust stock influences message drafting (more casual/formal tone, different escalation urgency), and it's not measurable, then **the AI's behavior is non-deterministic and non-debuggable**.

### 🟡 Assumption: Voice Quick Capture Works for Mixed-Language Speech

Chinese foreign trade conversations are notoriously mixed: "客户说了lead time太长了，我们需要给他们一个revised quotation，然后follow up一下他们的technical team." Voice-to-text systems (even good ones) struggle with code-switching between Chinese and English, especially with domain terms like "PI", "B/L", "ETD", "T/T".

### 🟡 Assumption: Seed Pipeline Is Meaningful Across Industries

A seed pipeline for "飞轮UPS" (flywheel UPS systems) looks nothing like one for "工业缝纫机" (industrial sewing machines) or "LED显示屏" (LED displays). A generic demo pipeline risks looking irrelevant and causing the exact "empty table" feeling it was designed to prevent.

### 🟡 Assumption: "风格学习" from Edit History

Section 2.7: "用户修改记录 → 风格学习" (user edit history → style learning). This assumes the AI can learn writing style from a few message edits. In practice:
- Edits are inconsistent (different contexts demand different styles)
- Reps have different writing abilities (learning from bad writing makes AI worse)
- "Style" in Chinese business communication is highly context-dependent (formal for first contact, casual after 6 months)

This is a Phase 3 feature being hand-waved into Phase 1 scope.

### 🟡 Assumption: Single-File SPA Won't Become Unmaintainable

ADR-0006 says the SPA will grow to ~2500 lines. At 2500 lines of vanilla JS in a single file, **every merge conflict touches the same file**, every bug investigation starts by reading 2500 lines, and the cognitive load of understanding component interactions is unbounded. The ADR acknowledges this risk ("需要拆分 JS/CSS") but defers it — which means Phase 1 ships with the problem.

---

## 6. WHAT WILL CAUSE A PRODUCTION INCIDENT IN THE FIRST WEEK

### 🔴 INCIDENT: Database Confusion (SQLite vs PostgreSQL)

If a developer deploys with PostgreSQL (per ADR-0001-postgresql) but the code has SQLite connection strings (per spec/ADR-0004), the app will fail to connect to the knowledge base on startup. If the code uses SQLite everywhere but deployment expects PostgreSQL, `LISTEN/NOTIFY` and RLS won't work. **This is a launch-blocker.**

### 🔴 INCIDENT: AI API Overwhelm (No Rate Limiting)

The spec defines `/api/ai/*` endpoints with no rate limiting. A single rep clicking "draft message" rapidly, or the silence diagnosis running across all opportunities simultaneously, will exhaust the DeepSeek API quota within hours. One tenant's noisy behavior can degrade AI for all tenants.

### 🔴 INCIDENT: Routine Messages Auto-Sent Incorrectly

ADR-0002 says `routine` messages are auto-sent with "事后通知" (post-notification). If the AI misclassifies a message containing: a price number, a delivery date commitment, a technical specification promise — the message goes out WITHOUT human review. The rep learns about it "after the fact." By then, the customer has already seen the mistake.

**Specific scenario:** A "routine" followup draft includes "as we discussed, the price is $48,000" but the actual agreed price was $52,000. The AI hallucinated the number. Message goes out. Rep gets a notification. Rep panics. Customer is confused or angry. Trust damaged.

### 🔴 INCIDENT: SSE Connection Exhaustion on 1GB VPS

ADR-0001-postgresql's scaling roadmap says >50 concurrent users triggers pgbouncer, but the spec plans for SSE connections per user (Section 4.4). Each SSE connection holds a database connection. With 10 users per tenant and 5 tenants = 50 concurrent connections. On a 1GB VPS, PostgreSQL defaults to 100 connections — but each connection + AI processing + the SPA serving + the Python process = memory exhaustion. The 1GB VPS mentioned in ADR-0005 will OOM-kill.

### 🟡 INCIDENT: No Database Migration Strategy

Spec Section 6: "SQLAlchemy create_all 不修改已有表：新列需手动 ALTER TABLE." This means every schema change requires manual SQL on the production database. One forgotten column, one typo in an ALTER TABLE, and the app breaks in production with no rollback mechanism.

### 🟡 INCIDENT: Knowledge Base Tier 2 Overwrite During Brain Sync

ADR-0005 says brain pushes knowledge updates. If a tenant has edited Tier 2 entries and the brain pushes fresh copies, tenant edits are silently destroyed. If the tenant's edit corrected a factual error in the brain's version, the error is re-introduced.

### 🟡 INCIDENT: Voice File Storage Without Retention Policy

Quick Capture accepts voice files. Where are they stored? Local disk? S3? Are they deleted after transcription? If stored locally on a 1GB VPS, 50 voice recordings at 2MB each = 100MB. After a month of active use = 3GB — the VPS runs out of disk space.

---

## SUMMARY: PRIORITY MATRIX

| Priority | Finding | Category |
|----------|---------|----------|
| 🔥 P0 | SQLite vs PostgreSQL contradiction | Contradiction |
| 🔥 P0 | No "N" defined for silence detection | Missing edge case |
| 🔥 P0 | Phantom "rule engine" for LLM degradation | Missing feature |
| 🔥 P0 | AI auto-send of routine messages without review | Production incident |
| 🔥 P0 | No rate limiting on AI endpoints | Production incident |
| 🔥 P0 | No notification delivery when user is offline | Missing edge case |
| P1 | DESIGN.md fonts vs spec constraint | Contradiction |
| P1 | Multi-version tone switching over-engineered | Over-engineered |
| P1 | AI auto-judging review_level too dangerous | Unrealistic assumption |
| P1 | No search/filter on opportunities API | Missing feature |
| P1 | No basic metrics/dashboard for managers | Missing feature |
| P1 | Duplicate lead detection missing | Missing feature |
| P1 | Voice storage without retention policy | Production incident |
| P2 | competitor_tracking & decision_chain premature | Over-engineered |
| P2 | Trust Stock is undefined/immeasurable | Unrealistic assumption |
| P2 | Silence diagnosis assumes mind-reading AI | Unrealistic assumption |
| P2 | Timezone blindness in silence detection | Missing edge case |
| P2 | Single-file SPA maintainability | Unrealistic assumption |

---

## BOTTOM LINE

These documents describe a compelling product vision for a real market. But they are **not ready for development**. The database contradiction alone means the first engineer to touch this will ask "PostgreSQL or SQLite?" and get no answer from the documents.

The AI functionality is described in aspirational terms ("风格学习," "自动判断review_level," "沉默诊断") without specifying the failure modes, fallback behaviors, or operational boundaries that turn aspirational features into working software.

**Recommendation:** Resolve the P0 items before writing any code. Resolve P1 items before shipping to a real customer. P2 items can be deferred but should be tracked.
