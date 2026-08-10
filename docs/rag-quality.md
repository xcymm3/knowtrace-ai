# RAG 质量验证

KnowTrace 采用可审阅的“黄金问题集”验证 RAG 主链路，而不是以主观的模型印象代替测试。每个用例声明问题、必须命中的资料文件，以及回答中必须覆盖的关键事实。

验证器会对每个用例计算：

- `retrieval_recall`：预期资料是否被检索并引用；目标为 100%。
- `citation_precision`：引用资料中有多少属于预期证据；目标不低于 50%，避免无关来源主导回答。
- `answer_term_coverage`：关键事实是否出现在最终回答中；目标为 100%。

任一用例未通过，命令以非零状态退出，适合接入 CI。它不会保存评估对话：每个临时对话会在评估结束后删除。

## 编写数据集

复制 [示例数据集](../backend/evals/fixtures/rag-quality-sample.json)，将文件名和关键事实替换为已完成索引的真实资料。不要把 API Key 或 Access Token 写入数据集或提交到 Git。

```json
[
  {
    "id": "meeting-decision",
    "question": "会议最终决定了什么？",
    "expected_sources": ["会议纪要.md"],
    "expected_answer_terms": ["继续推进", "张三"]
  }
]
```

## 运行

先从浏览器开发者工具或 Supabase 登录会话中临时取得当前用户的 Access Token；不要将它写入 Shell 历史。PowerShell 可先保存为临时环境变量：

```powershell
$env:KNOWTRACE_ACCESS_TOKEN = "<temporary-access-token>"
Set-Location backend
.\.venv-knowtrace\Scripts\python.exe -m evals.run_rag_quality `
  --api-base-url "http://localhost:8000" `
  --access-token $env:KNOWTRACE_ACCESS_TOKEN `
  --workspace-id "<knowledge-base-uuid>" `
  --dataset ".\evals\fixtures\rag-quality-sample.json"
```

可附加 `--output .\rag-quality-report.json` 保存报告；该报告应视为测试产物，不建议提交。
