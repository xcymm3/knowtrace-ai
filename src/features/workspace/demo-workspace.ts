export const workspaceDemo = {
  project: {
    code: "KT-001",
    status: "进行中",
    name: "产品设计规范",
    description: "集中整理设计规范、产品资料与历史决策，作为后续可追溯对话的资料范围。",
    platform: "团队工作空间",
    audience: "产品与设计团队",
    materialState: "2 份已索引 · 1 份处理中",
  },
  taskStages: [
    { label: "资料入库", detail: "规范文档与项目记录已保存", state: "done" },
    { label: "文本解析", detail: "PDF 和表格文本已提取", state: "done" },
    { label: "向量索引", detail: "正在为设计决策记录建立检索片段", state: "active" },
    { label: "引用式对话", detail: "等待全部资料进入 READY 状态", state: "waiting" },
  ],
  materials: [
    { format: "XLSX", name: "组件规范清单.xlsx", detail: "组件状态 · 交互约束 · 维护记录", state: "已索引" },
    { format: "PDF", name: "品牌视觉规范.pdf", detail: "字体 · 色彩 · 版式原则", state: "已索引" },
    { format: "MD", name: "历史设计决策.md", detail: "决策背景 · 结论 · 原始链接", state: "处理中" },
  ],
  evidence: {
    excerpt: "在移动端输入区域必须保持可见焦点，主要操作只使用蓝色强调，避免用颜色作为唯一状态提示。",
    source: "品牌视觉规范.pdf · 可访问性原则",
    location: "片段 03 · 字符 286–332",
  },
  answer: {
    title: "主操作的视觉约束",
    summary: "结论仅基于当前已索引资料。待历史设计决策处理完成后，可补充更多项目上下文。",
    citations: ["引用 · 品牌视觉规范.pdf / 片段 03", "引用 · 组件规范清单.xlsx / 工作表 1"],
  },
} as const;
