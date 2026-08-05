# Supabase 配置说明

CommerceLens AI MVP 使用一个 Supabase 项目承载三类能力：

| 能力 | 用途 |
| --- | --- |
| PostgreSQL | 调研项目、商品、报告、任务与人工反馈 |
| pgvector | 品牌资料、商品描述与竞品材料的向量检索 |
| Storage | Excel、PDF、文本、商品图与竞品截图 |

## 远程项目初始化

1. 在 Supabase Dashboard 创建一个新的空项目。
2. 打开 **SQL Editor**，按文件名顺序执行：
   - `supabase/migrations/20260805000000_initial_commercelens_schema.sql`
   - `supabase/migrations/20260805000001_create_research_assets_bucket.sql`
   - `supabase/migrations/20260805000002_add_hybrid_retrieval.sql`
3. 在 Project Settings → Database 复制连接字符串，写入本地 `.env` 的 `DATABASE_URL`。
4. 在 Project Settings → API 获取 Project URL 和 **service_role** key，分别写入 `SUPABASE_URL` 与 `SUPABASE_SERVICE_ROLE_KEY`。
5. 保持 `SUPABASE_STORAGE_BUCKET=research-assets`。

## 访问边界

- `public` 业务表与 `research-assets` Bucket 均不向浏览器直连开放。
- MVP 只允许 FastAPI 使用 Service Role 访问 Supabase。
- 前端通过 FastAPI 上传文件、查询调研数据和获取短时签名下载链接。
- 数据表已启用 RLS；未建立浏览器侧 policy，因此匿名和普通登录请求默认拒绝。
- `service_role` key 只能存放在 API/Worker 环境变量中，绝不能写入 `NEXT_PUBLIC_*` 配置或提交到 Git。

## Storage 对象路径

上传文件遵循以下路径，确保资料不会跨调研项目混用：

```text
{project_id}/{document_id}/original/{sanitized_file_name}
```

数据库中的 `source_documents.storage_path` 会记录相同路径，并通过约束要求它以对应的 `project_id/` 开头。

## 本地环境变量模板

```dotenv
DATABASE_URL="postgresql://..."
SUPABASE_URL="https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="..."
SUPABASE_STORAGE_BUCKET="research-assets"
```

## 验证清单

- SQL Editor 可看到 `research_projects`、`products`、`source_documents` 等表。
- `knowledge_chunks.embedding` 类型为 `vector(1536)`。
- Storage 中存在私有的 `research-assets` Bucket。
- 使用 anon key 读取 `storage.objects` 或业务表时被拒绝。
- 使用仅在服务端运行的 Service Role 客户端能够创建资料记录与上传文件。
