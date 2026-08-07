# Supabase 初始化

KnowTrace 使用一个 Supabase 项目提供 PostgreSQL、pgvector 和私有文件 Storage。新建项目时，只需要执行当前的 KnowTrace Migration；它会启用所需扩展、创建更新触发器和 `knowtrace-assets` Bucket。

## SQL Editor 初始化

1. 在 Supabase Dashboard 创建空项目。
2. 打开 **SQL Editor**，按顺序执行：
   - `supabase/migrations/20260807000000_create_knowtrace_core.sql`
   - `supabase/migrations/20260807001000_add_parsed_document_status.sql`
3. 在 **Project Settings → Database** 复制 PostgreSQL connection string，填写根目录 `.env` 的 `DATABASE_URL`。
4. 在 **Project Settings → API** 复制 Project URL 与 `service_role` key，分别填写 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。

> 仓库中仍保留早期 CommerceLens Migration，供旧原型升级参考；新 KnowTrace 项目不需要手动执行它们。

## 必填环境变量

```dotenv
DATABASE_URL="postgresql://..."
SUPABASE_URL="https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="..."
SUPABASE_STORAGE_BUCKET="knowtrace-assets"
```

`SUPABASE_SERVICE_ROLE_KEY` 只能进入 API 和 Worker 环境，绝不能改成 `NEXT_PUBLIC_*` 变量或提交到 Git。

## 验证清单

- Database 中存在 `workspaces`、`workspace_documents`、`document_chunks`、`processing_tasks`、`conversations`、`conversation_messages` 和 `message_citations`。
- `document_chunks.embedding` 类型为 `vector(1536)`。
- Storage 中存在私有的 `knowtrace-assets` Bucket。
- 文件路径以 `{workspace_id}/` 开头。
- 浏览器匿名请求不能读取业务表或 Storage 对象；只有后端 Service Role 可访问。
