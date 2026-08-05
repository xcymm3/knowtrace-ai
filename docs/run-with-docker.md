# 使用 Docker Compose 运行 CommerceLens AI

Compose 运行 Web、FastAPI、Redis Worker 和 Redis 四个本地服务；Supabase 继续作为托管 PostgreSQL、pgvector 和 Storage，不会被重复部署到本机。

## 前置条件

1. 安装 Docker Desktop，并确认 `docker compose version` 可执行。
2. 按 [Supabase 配置说明](./supabase-setup.md) 在远程项目依次执行三个 Migration：
   - `20260805000000_initial_commercelens_schema.sql`
   - `20260805000001_create_research_assets_bucket.sql`
   - `20260805000002_add_hybrid_retrieval.sql`
3. 复制 `.env.example` 为 `.env`，填入 `DATABASE_URL`、Supabase Service Role、Embedding 服务配置。

`SUPABASE_SERVICE_ROLE_KEY` 与 `EMBEDDING_API_KEY` 只会注入 API 和 Worker；Compose 不会把它们传给浏览器容器。

## 启动

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 Supabase 与 Embedding 配置
docker compose up --build
```

启动后访问：

| 地址 | 服务 |
| --- | --- |
| `http://localhost:3000` | Next.js 选品调研工作台 |
| `http://localhost:8000/docs` | FastAPI OpenAPI 文档 |
| `http://localhost:8000/api/v1/health` | API 存活检查 |

停止服务并保留 Redis 队列数据：

```powershell
docker compose down
```

如需清空本地 Redis 队列数据，再执行：

```powershell
docker compose down --volumes
```

## 导入演示项目

在 Supabase SQL Editor 执行 [demo_commercelens.sql](../supabase/seed/demo_commercelens.sql)，会创建一个项目和三个商品/竞品记录。该脚本不伪造品牌资料、图片、评论或 Embedding；请通过 API 上传实际或已授权的调研材料。

## 验收路径

1. 打开工作台，确认页面显示“演示模式”。
2. 在 `/docs` 创建项目或使用演示项目 ID 上传一份 TXT、CSV、XLSX 或 PDF 资料。
3. 通过 `/api/v1/tasks/{task_id}/events` 观察解析与向量化任务进度。
4. 在资料索引完成后调用 `POST /api/v1/projects/{project_id}/search`，确认结果带有文件名和片段位置。
5. 调用 `POST /api/v1/projects/{project_id}/reports`，确认每一条报告结论都含引用。
