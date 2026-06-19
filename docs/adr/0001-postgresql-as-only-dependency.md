# 使用 PostgreSQL 作为唯一外部依赖：不做 Redis / 独立 Worker / 消息队列

**状态：** accepted

## 上下文

SalesOS Lite 定位为极轻 SaaS 统一收件箱，目标部署复杂度为"一个进程 + 一个数据库"。但同时需要：异步 AI 任务队列、租户隔离、实时推送（SSE）、多用户并发。

独立组件方案（Redis + Celery/RQ + Nginx）会带来运维负担，对 MVP 阶段的中小外贸团队（<50 并发用户）是过度设计。

## 决定

PostgreSQL 承担全部基础设施角色：

1. **队列** — `ai_jobs` 表 + `SELECT ... FOR UPDATE SKIP LOCKED` 替代 Redis/RabbitMQ
2. **租户隔离** — Row-Level Security 替代应用层 WHERE tenant_id
3. **实时推送** — `LISTEN/NOTIFY` 替代 Redis Pub/Sub，FastAPI 转发为 SSE
4. **数据存储** — 主数据库

不做：Redis、Celery、RQ、Nginx、独立 AI Worker 进程。

## 后果

**更容易：**
- 部署：`docker-compose up` 启动两个容器
- 调试：一个数据库里能看到所有状态（数据 + 队列 + 通知）
- 备份：`pg_dump` 一条命令带走一切
- 安全：RLS 在数据库层兜底，不依赖应用层不遗漏 WHERE

**更难：**
- 扩展：单 PG 实例是瓶颈。>50 并发用户时需要评估读写分离或连接池（pgbouncer）
- 队列积压：超过单进程处理能力时需要独立 Worker（届时已有收入支撑）
- 不是标准做法：后来者会问"为什么不用 Redis"
