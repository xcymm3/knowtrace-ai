# KnowTrace AI

> 面向个人资料的可追溯知识工作台：上传文件、异步建立索引、在限定资料范围内进行带引用的流式问答。

KnowTrace 的目标不是泛用聊天，而是让每次回答都能回到具体文件和片段。它适合会议纪要、产品资料、研究笔记、规范文档和表格数据等需要复核的团队知识。

## 已实现的 MVP

1. **个人知识库隔离**：使用用户名与密码登录后，每个用户仅能访问自己创建的知识库、资料、任务和对话。
2. **文件入库**：支持 TXT、Markdown、CSV、XLSX、DOCX 与 PDF；原文件存入 Supabase Storage。
3. **异步处理**：FastAPI 创建任务，Redis + ARQ Worker 负责解析、切片、Embedding、失败重试和进度记录。
4. **混合检索**：PostgreSQL + pgvector 结合向量相似度与全文关键词检索，只查询当前工作区已索引资料。
5. **引用式 RAG 对话**：LangChain 调用 OpenAI-compatible 模型；回答通过 SSE 流式返回，并保留文件名、片段位置和摘录。
6. **本地一键编排**：Docker Compose 启动 Next.js、FastAPI、Worker 和 Redis；Supabase 继续提供托管 PostgreSQL、pgvector 与 Storage。

当前不包含团队协作与角色权限、多模型切换、联网搜索、OCR、Agent 工具调用或本地模型管理。这些是明确的 MVP 边界，不是未声明的承诺。

## 架构

```text
Next.js Workbench
        │ /api/v1 proxy
        ▼
FastAPI ─── Supabase (PostgreSQL + pgvector + Storage)
   │
   └── Redis ─── ARQ Worker (解析 / 切片 / Embedding)
        │
        └── OpenAI-compatible Embedding / Chat API
```

| 服务 | 职责 |
| --- | --- |
| Next.js | 用户名密码登录、个人工作区、资料、任务状态、会话与引用展示 |
| FastAPI | 验证 Supabase JWT，并执行工作区、文件、检索、会话与 SSE API |
| Supabase | Auth、PostgreSQL 业务数据、pgvector 检索、私有文件 Storage |
| Redis + ARQ | 后台解析、向量化、重试与进度队列 |
| LangChain | 将检索上下文连接到 OpenAI-compatible 对话模型 |

## 快速开始

前置条件：Node.js 22+、pnpm 11、Python 3.12+、Docker Desktop，以及一个 Supabase 项目。

```powershell
pnpm install
Copy-Item .env.example .env
```

然后按 [Supabase 初始化](docs/supabase-setup.md) 执行 Migration，并填写 `.env`。完整容器启动方式见 [Docker Compose 运行说明](docs/run-with-docker.md)。

## 常用命令

```powershell
# 前端
pnpm dev
pnpm lint
pnpm build

# 后端（在 backend 目录执行）
$env:UV_PROJECT_ENVIRONMENT='.venv-knowtrace'
uv sync --group dev
uv run pytest
uv run ruff check app tests

# 全栈
docker compose up --build
```

## 部署边界

完整 MVP 需要一个可持续运行的 FastAPI 服务、一个 Worker 和 Redis。推荐使用 Docker Compose 或把这三个服务分别部署到支持容器/进程的运行平台；Supabase 作为托管依赖。

Vercel 适合部署 Next.js 前端，但不能单独承载持续消费 Redis 队列的 Worker。若使用 Vercel，仍需单独部署 API、Worker 和 Redis，并配置前端的 `API_PROXY_TARGET` 指向 API 服务。详见 [部署说明](docs/deployment.md)。

## 文档

- [MVP 范围](docs/mvp-scope.md)
- [数据模型](docs/data-model.md)
- [API 契约](docs/api-contract.md)
- [RAG 质量验证](docs/rag-quality.md)
- [前端端到端测试](docs/end-to-end-testing.md)
- [Supabase 初始化](docs/supabase-setup.md)
- [Docker Compose 运行](docs/run-with-docker.md)
- [部署说明](docs/deployment.md)
