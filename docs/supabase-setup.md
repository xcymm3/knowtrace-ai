# Supabase 初始化

KnowTrace 使用一个 Supabase 项目提供 PostgreSQL、pgvector 和私有文件 Storage。新建项目时，只需要执行当前的 KnowTrace Migration；它会启用所需扩展、创建更新触发器和 `knowtrace-assets` Bucket。

## SQL Editor 初始化

1. 在 Supabase Dashboard 创建空项目。
2. 打开 **SQL Editor**，按顺序执行：
   - `supabase/migrations/20260807000000_create_knowtrace_core.sql`
   - `supabase/migrations/20260807001000_add_parsed_document_status.sql`
   - `supabase/migrations/20260808000000_add_personal_workspace_ownership.sql`
3. 在 **Project Settings → Database** 复制 PostgreSQL connection string，填写根目录 `.env` 的 `DATABASE_URL`。
4. 在 **Project Settings → API** 复制 Project URL、Publishable key 与 `service_role` key：
   - `SUPABASE_URL` 与 `NEXT_PUBLIC_SUPABASE_URL` 填同一个 Project URL。
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 填 Publishable key；它可公开给浏览器。
   - `SUPABASE_SERVICE_ROLE_KEY` 仅填写后端服务密钥。
5. 在 **Authentication → Providers → Email** 确认 Email Provider 已开启。开发阶段可关闭 **Confirm email**，或保持开启并完成邮件验证后登录。

## 必填环境变量

```dotenv
DATABASE_URL="postgresql://..."
SUPABASE_URL="https://<project-ref>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="..."
NEXT_PUBLIC_SUPABASE_URL="https://<project-ref>.supabase.co"
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="sb_publishable_..."
SUPABASE_STORAGE_BUCKET="knowtrace-assets"
```

`SUPABASE_SERVICE_ROLE_KEY` 只能进入 API 和 Worker 环境，绝不能改成 `NEXT_PUBLIC_*` 变量或提交到 Git。

`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 不是 service role key；它只用于浏览器发起登录并取得用户 JWT。FastAPI 会验证该 JWT，再按 `workspaces.owner_id` 检查个人资料归属。

## 旧 MVP 数据迁移

新增 `owner_id` 后，历史 MVP 工作区不会被自动分配给任意用户，以免错误泄露数据。创建并登录第一个账号后，如需保留旧数据，可在 SQL Editor 中将其明确归属给该账号：

```sql
update public.workspaces
set owner_id = '<Supabase Auth 用户 UUID>'
where owner_id is null;
```

用户 UUID 可在 **Authentication → Users** 页面查看。只应对本人创建的历史测试资料执行此操作。

## 验证清单

- Database 中存在 `workspaces`、`workspace_documents`、`document_chunks`、`processing_tasks`、`conversations`、`conversation_messages` 和 `message_citations`。
- `workspaces` 存在 `owner_id` 字段；注册两个测试账号时，双方不会看到对方的知识库。
- `document_chunks.embedding` 类型为 `vector(1536)`。
- Storage 中存在私有的 `knowtrace-assets` Bucket。
- 文件路径以 `{workspace_id}/` 开头。
- 浏览器匿名请求不能调用业务 API；后端会验证 Supabase 用户 JWT，Service Role 仅用于受控的服务端读写。
