# 前端端到端测试

KnowTrace 使用 Playwright 验证浏览器中的关键业务闭环。测试启动独立的 Next.js 开发服务器，并模拟 Supabase 登录状态和 FastAPI 响应；不会访问真实 Supabase、Redis、模型服务或用户资料。

覆盖路径：

1. 已登录用户创建知识库。
2. 上传一份资料并显示“已索引”。
3. 基于资料提问，接收 SSE 流式回答与引用。
4. 删除对话并显示确认结果。
5. 未登录用户进入注册页，检查用户名、确认密码和非阻断密码强度反馈。

## 运行

首次执行需要下载 Chromium：

```powershell
pnpm exec playwright install chromium
pnpm test:e2e
```

失败时 Playwright 会保留 Trace，可运行以下命令查看：

```powershell
pnpm exec playwright show-trace test-results\<failed-test>\trace.zip
```
