# KnowTrace AI

> 面向团队资料的可追溯知识工作台。用户在项目中上传资料，并获得带来源引用的 AI 问答与结构化结论。

## MVP 定位

KnowTrace AI 以“项目文件夹 + 文件 + 对话”为核心交互：

1. 创建一个项目，用作独立的资料与对话范围。
2. 上传项目资料；原文件保存到 Supabase Storage。
3. 后台异步解析、切分并向量化文本资料。
4. 在项目内提问、生成摘要或对比资料。
5. 每个回答均可回看其引用的文件原文与位置。

第一版只聚焦可追溯的文档 RAG 闭环，不提供本地模型管理、多模型切换、Agent、联网搜索、OCR 或多模态能力。

## 目标架构

| 服务 | 职责 |
| --- | --- |
| Next.js | 项目列表、文件上传、对话和引用展示工作台 |
| FastAPI | 项目、资料、检索与对话 API；SSE 流式推送 |
| Supabase | PostgreSQL 业务数据、pgvector 检索、Storage 文件存储 |
| Redis + Worker | 资料解析、Embedding 与重试任务 |
| Docker Compose | 本地启动 Web、API、Worker 和 Redis，并连接 Supabase |

## 本地开发

```powershell
pnpm install
Copy-Item .env.example .env
pnpm dev
```

## Docker Compose

项目提供 `web + api + worker + redis` 的 Compose 配置，Supabase 继续承载托管数据库、pgvector 与 Storage。

```powershell
docker compose up --build
```

详细环境变量和运行说明将在后续改造步骤中同步更新。
