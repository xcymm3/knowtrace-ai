# 使用 Docker Compose 运行 KnowTrace AI

Compose 会运行四个本地服务：Next.js `web`、FastAPI `api`、ARQ `worker` 和 `redis`。Supabase 仍作为外部托管的 PostgreSQL、pgvector 与 Storage，不会在本机重复启动。

## 前置条件

1. 安装 Docker Desktop，确认 `docker compose version` 可执行。
2. 依照 [Supabase 初始化](./supabase-setup.md) 创建项目，并按顺序执行三份 KnowTrace Migration：
   - `20260807000000_create_knowtrace_core.sql`
   - `20260807001000_add_parsed_document_status.sql`
   - `20260808000000_add_personal_workspace_ownership.sql`
3. 复制 `.env.example` 为 `.env`，填写 Supabase、Embedding 与 LLM 配置。

```powershell
Copy-Item .env.example .env
docker compose up --build
```

服务启动后：

| 地址 | 服务 |
| --- | --- |
| `http://localhost:3001` | KnowTrace 工作台（Compose 默认端口） |
| `http://localhost:8000/docs` | FastAPI OpenAPI 文档 |
| `http://localhost:8000/api/v1/health` | API 存活检查 |

## 验收路径

1. 打开 `http://localhost:3001`，注册或登录一个 Supabase 邮箱账号。
2. 创建个人知识库并上传 TXT、Markdown、CSV、XLSX、DOCX 或 PDF 文件。
3. 在右侧处理状态中等待文件解析与向量索引完成。
4. 在主面板提问，确认回答逐步出现，并可展开“本次引用”的文件片段。
5. 退出并登录另一个测试账号，确认其无法查看第一个账号的资料。

## 停止与排错

```powershell
# 停止容器，保留 Redis 队列数据
docker compose down

# 同时移除本地 Redis 卷（会丢弃队列数据）
docker compose down --volumes

# 查看服务状态与日志
docker compose ps
docker compose logs -f api worker
```

如页面提示无法连接后端，先检查 `docker compose ps` 中 `api` 是否健康，并确认 `.env` 中的 `DATABASE_URL`、`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`EMBEDDING_*` 与 `LLM_*` 已填写。

如需让 Compose 工作台使用 3000 端口，先停止 `pnpm dev`，再在 `.env` 中设置 `WEB_PORT="3000"`。
