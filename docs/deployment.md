# KnowTrace 部署说明

完整的容器部署由五类资源构成：Next.js、FastAPI、ARQ Worker、Redis 和 Supabase。前四者的职责不能互相替代。

| 资源 | 持续运行需求 | 关键配置 |
| --- | --- | --- |
| Next.js | HTTP 服务 | `API_PROXY_TARGET` 指向 FastAPI 地址。 |
| FastAPI | HTTP 服务 | Supabase、Redis、Embedding、LLM 配置。 |
| ARQ Worker | 持续消费队列 | 与 API 相同的 Supabase、Redis、Embedding 配置。 |
| Redis | 持续服务 | API/Worker 共同使用的 `REDIS_URL`。 |
| Supabase | 托管服务 | PostgreSQL、pgvector、私有 Storage。 |

## 推荐方式：Docker Compose

小型演示或自托管环境直接使用根目录 `docker-compose.yml`。部署前执行 Supabase Migration，填好 `.env`，然后运行：

```powershell
docker compose up --build -d
docker compose ps
```

为公网部署设置：

- `CORS_ORIGINS`：前端公网域名，例如 `https://app.example.com`。
- `API_PROXY_TARGET`：Next.js 服务到 FastAPI 服务的内部或公网地址。
- `NEXT_PUBLIC_APP_URL`：前端公网地址。
- `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`REDIS_URL`、`EMBEDDING_*`、`LLM_*`：仅部署环境变量，不进入代码库。当前后端通过 Supabase REST API 访问业务数据，`DATABASE_URL` 仅在 Docker Compose 配置中保留，不是 Vercel API 的运行时前提。

## 使用 Vercel 的边界

Vercel 适合承载 Next.js 前端和短生命周期的 FastAPI 路由，但不适合作为持续消费 Redis 队列的 Worker 运行环境。KnowTrace 在 `TASK_EXECUTION_MODE=auto` 时会识别 Vercel 环境，并使用与 Worker 共用的处理函数在上传请求内完成短文件的解析与索引。

1. Vercel 可承载登录、知识库读写、提问和短文件解析；需配置 `SUPABASE_*`、`EMBEDDING_*` 与 `LLM_*`，不必为内联模式配置 Redis。
2. 对大文件、批量导入或需要稳定吞吐的场景，仍应在容器平台运行 ARQ Worker，并提供托管 Redis；此时设置 `TASK_EXECUTION_MODE=queue`。
3. 如 FastAPI 部署在 Vercel 之外，将 Vercel 的 `API_PROXY_TARGET` 设置为该服务 HTTPS 地址，并在 FastAPI 的 `CORS_ORIGINS` 添加前端域名。
4. 不要把任何 `SUPABASE_SERVICE_ROLE_KEY`、Embedding Key 或 LLM Key 配置为 `NEXT_PUBLIC_*`。

现有 `vercel.json` 描述前端与 API 路由关系；容器模式仍是完整异步处理与横向扩展的推荐方案。
