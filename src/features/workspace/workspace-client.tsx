"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  commerceLensApi,
  type ProductComparison,
  type ResearchProject,
  type ResearchTask,
  type SelectionReport,
  type SourceDocument,
} from "@/lib/commercelens-api";

import styles from "@/app/page.module.css";

type WorkspaceData = {
  comparison: ProductComparison;
  documents: SourceDocument[];
  tasks: ResearchTask[];
  reports: SelectionReport[];
};

const emptyWorkspace: WorkspaceData = {
  comparison: { project_id: "", own_product_count: 0, competitor_product_count: 0, products: [] },
  documents: [],
  tasks: [],
  reports: [],
};

const documentLabels: Record<string, string> = {
  PRODUCT_SHEET: "商品参数",
  COMPETITOR_SHEET: "竞品资料",
  BRAND_GUIDE: "品牌手册",
  PLATFORM_RULE: "平台规则",
  REVIEW_EXPORT: "用户评价",
  PRODUCT_IMAGE: "商品图片",
  COMPETITOR_SCREENSHOT: "竞品截图",
  OTHER: "其他资料",
};

function readableError(error: unknown) {
  return error instanceof ApiError || error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function projectStatus(status: ResearchProject["status"]) {
  return { ACTIVE: "进行中", DRAFT: "草稿", ARCHIVED: "已归档" }[status];
}

function documentStatus(status: string) {
  return { READY: "已索引", PROCESSING: "处理中", PENDING: "等待处理", FAILED: "处理失败" }[status] ?? status;
}

function formatPrice(price: number | null, currency: string | null) {
  if (price === null) return "暂未登记";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: currency ?? "CNY",
    maximumFractionDigits: 2,
  }).format(price);
}

function taskDetail(task: ResearchTask) {
  if (task.status === "FAILED") return task.error_message ?? "任务执行失败";
  if (task.status === "SUCCEEDED") return task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引已完成" : "资料解析已完成";
  return `${task.progress}% · ${task.task_type === "GENERATE_EMBEDDINGS" ? "正在建立向量索引" : "正在解析资料"}`;
}

export function WorkspaceClient() {
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceData>(emptyWorkspace);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeProject = projects.find((project) => project.id === projectId) ?? null;
  const activeReport = workspace.reports[0] ?? null;

  const loadWorkspace = useCallback(async (nextProjectId: string) => {
    const [comparison, documents, tasks, reports] = await Promise.all([
      commerceLensApi.getComparison(nextProjectId),
      commerceLensApi.listDocuments(nextProjectId),
      commerceLensApi.listTasks(nextProjectId),
      commerceLensApi.listReports(nextProjectId),
    ]);
    setWorkspace({ comparison, documents, tasks, reports });
  }, []);

  const refreshProjects = useCallback(async () => {
    const nextProjects = await commerceLensApi.listProjects();
    setProjects(nextProjects);
    return nextProjects;
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const nextProjects = await refreshProjects();
        if (nextProjects[0]) setProjectId(nextProjects[0].id);
      } catch (caughtError) {
        setError(readableError(caughtError));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [refreshProjects]);

  useEffect(() => {
    if (!projectId) {
      return;
    }
    void (async () => {
      setIsLoading(true);
      setError(null);
      try {
        await loadWorkspace(projectId);
      } catch (caughtError) {
        setError(readableError(caughtError));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [loadWorkspace, projectId]);

  const watchTask = useCallback(
    (taskId: string) => {
      const source = commerceLensApi.taskEvents(taskId);
      const updateTask = (event: Event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as ResearchTask;
        setWorkspace((current) => ({
          ...current,
          tasks: [payload, ...current.tasks.filter((task) => task.id !== payload.id)],
        }));
      };
      const complete = () => {
        source.close();
        if (projectId) void loadWorkspace(projectId);
      };
      source.addEventListener("progress", updateTask);
      source.addEventListener("complete", (event) => {
        updateTask(event);
        complete();
      });
      source.addEventListener("timeout", complete);
      source.onerror = complete;
    },
    [loadWorkspace, projectId],
  );

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setIsSubmitting(true);
    setError(null);
    try {
      const project = await commerceLensApi.createProject({
        name: String(form.get("name") ?? ""),
        category: String(form.get("category") ?? "") || null,
        target_platform: "快手电商",
        target_audience: String(form.get("audience") ?? "") || null,
      });
      setProjects((current) => [project, ...current]);
      setProjectId(project.id);
      event.currentTarget.reset();
      setNotice("快手选品调研项目已创建。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleAddProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    const rawPrice = String(form.get("price") ?? "").trim();
    setIsSubmitting(true);
    setError(null);
    try {
      await commerceLensApi.createProduct(projectId, {
        role: String(form.get("role")) === "COMPETITOR" ? "COMPETITOR" : "OWN",
        name: String(form.get("name") ?? ""),
        brand_name: String(form.get("brand") ?? "") || null,
        price: rawPrice ? Number(rawPrice) : null,
        currency: "CNY",
        description: String(form.get("description") ?? "") || null,
        attributes: {},
      });
      event.currentTarget.reset();
      await loadWorkspace(projectId);
      setNotice("商品已加入候选池。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("请选择需要入库的资料文件。");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await commerceLensApi.uploadDocument(projectId, form);
      event.currentTarget.reset();
      await loadWorkspace(projectId);
      watchTask(response.task_id);
      setNotice("资料已入库，正在解析与建立索引。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateReport() {
    if (!projectId) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await commerceLensApi.createReport(projectId);
      await loadWorkspace(projectId);
      setNotice("已生成可审核的证据化选品报告。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleFeedback(decision: "APPROVED" | "REJECTED") {
    if (!projectId || !activeReport) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await commerceLensApi.submitFeedback(projectId, activeReport.id, decision);
      await loadWorkspace(projectId);
      setNotice(decision === "APPROVED" ? "报告已确认。" : "报告已驳回，等待补充证据。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  const evidence = useMemo(() => activeReport?.findings.flatMap((finding) => finding.citations)[0] ?? null, [activeReport]);
  const activeTasks = workspace.tasks.filter((task) => ["QUEUED", "RUNNING"].includes(task.status));

  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#main-content">跳至工作台</a>
      <nav className={styles.nav} aria-label="工作台导航">
        <a className={styles.brand} href="#overview">CommerceLens <span>AI</span></a>
        <div className={styles.navLinks}>
          <a href="#products">商品池</a><a href="#materials">资料库</a><a href="#report">报告</a>
        </div>
        <span className={styles.demoFlag}>快手 MVP</span>
      </nav>

      <main className={styles.shell} id="main-content">
        <header className={styles.intro} id="overview">
          <div><p className={styles.kicker}>快手直播选品与竞品调研</p><h1>把选品依据放在一起</h1></div>
          <p className={styles.introCopy}>统一管理候选商品、竞品资料、用户评价与平台规范。报告中的每一条判断都会保留可复核的来源片段。</p>
        </header>

        {error ? <p className={styles.feedbackError} role="alert">{error}</p> : null}
        {notice ? <p className={styles.feedbackNotice}>{notice}</p> : null}

        {!activeProject && !isLoading ? (
          <section className={styles.emptyState} aria-labelledby="create-project-title">
            <p className={styles.kicker}>从真实资料开始</p><h2 id="create-project-title">创建第一个快手选品项目</h2>
            <form className={styles.inlineForm} onSubmit={handleCreateProject}>
              <label>项目名称<input name="name" required placeholder="例如：通勤保温杯直播选品" /></label>
              <label>品类<input name="category" placeholder="例如：家居百货" /></label>
              <label>目标人群<input name="audience" placeholder="例如：城市通勤人群" /></label>
              <button type="submit" disabled={isSubmitting}>创建项目</button>
            </form>
          </section>
        ) : null}

        {activeProject ? <>
          <section className={styles.projectFrame} aria-labelledby="project-title">
            <div className={styles.projectIdentity}>
              <div className={styles.projectTopline}>
                <span className={styles.statusDot} aria-hidden="true" /><span>{projectStatus(activeProject.status)}</span>
                <span className={styles.mono}>项目 #{activeProject.id.slice(0, 8)}</span>
              </div>
              <h2 id="project-title">{activeProject.name}</h2>
              <p>{activeProject.category ? `${activeProject.category} · ` : ""}围绕快手直播场景沉淀可验证的卖点、价格与信任证据。</p>
              <dl className={styles.projectMeta}>
                <div><dt>目标平台</dt><dd>{activeProject.target_platform ?? "快手电商"}</dd></div>
                <div><dt>目标人群</dt><dd>{activeProject.target_audience ?? "暂未填写"}</dd></div>
                <div><dt>资料状态</dt><dd>{workspace.documents.filter((document) => document.status === "READY").length} 份已索引 · {workspace.documents.length} 份资料</dd></div>
              </dl>
              <label className={styles.projectPicker}>切换项目
                <select value={projectId ?? ""} onChange={(event) => setProjectId(event.target.value)}>
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                </select>
              </label>
            </div>
            <aside className={styles.runPanel} aria-labelledby="run-title">
              <div className={styles.panelHeading}><div><p className={styles.kicker}>当前任务</p><h2 id="run-title">资料处理进度</h2></div><span className={styles.taskState}>{activeTasks.length ? "运行中" : "已就绪"}</span></div>
              <ol className={styles.taskList}>
                {(workspace.tasks.slice(0, 4)).map((task) => <li className={styles[`stage${task.status === "SUCCEEDED" ? "done" : task.status === "RUNNING" ? "active" : "waiting"}`]} key={task.id}><span className={styles.stageMarker} aria-hidden="true" /><div><strong>{task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引" : "资料解析"}</strong><span>{taskDetail(task)}</span></div></li>)}
                {!workspace.tasks.length ? <li className={styles.stagewaiting}><span className={styles.stageMarker} aria-hidden="true" /><div><strong>等待资料入库</strong><span>上传竞品资料、用户评价或平台规则后，任务会在这里显示。</span></div></li> : null}
              </ol>
              <p className={styles.runNote}>任务状态通过 FastAPI SSE 实时更新。</p>
            </aside>
          </section>

          <section className={styles.section} id="products" aria-labelledby="products-title">
            <div className={styles.sectionHeading}><div><p className={styles.kicker}>候选商品与竞品</p><h2 id="products-title">商品池</h2></div><span className={styles.sectionHint}>真实价格与资料覆盖度</span></div>
            <form className={styles.actionForm} onSubmit={handleAddProduct}>
              <select name="role" defaultValue="OWN" aria-label="商品角色"><option value="OWN">自有候选</option><option value="COMPETITOR">竞品</option></select>
              <input name="name" required placeholder="商品名称" aria-label="商品名称" />
              <input name="brand" placeholder="品牌" aria-label="品牌" />
              <input name="price" type="number" min="0" step="0.01" placeholder="价格" aria-label="价格" />
              <input name="description" placeholder="核心参数或直播卖点" aria-label="核心参数或直播卖点" />
              <button type="submit" disabled={isSubmitting}>加入商品池</button>
            </form>
            <div className={styles.productGrid}>
              {workspace.comparison.products.map(({ product, document_count, indexed_document_count }) => <article className={styles.productCard} key={product.id}><div className={styles.cardTopline}><span className={product.role === "OWN" ? styles.ownTag : styles.competitorTag}>{product.role === "OWN" ? "自有候选" : "竞品"}</span><span className={styles.mono}>{indexed_document_count} / {document_count} 资料就绪</span></div><h3>{product.name}</h3><p>{product.brand_name ?? "未填写品牌"}</p><dl className={styles.productData}><div><dt>登记价格</dt><dd>{formatPrice(product.price, product.currency)}</dd></div><div><dt>已识别属性</dt><dd>{product.description ?? "待补充"}</dd></div></dl></article>)}
              {!workspace.comparison.products.length ? <p className={styles.emptyCopy}>还没有商品。先录入自有 SKU 和竞品，才能生成横向对比。</p> : null}
            </div>
          </section>

          <section className={styles.splitSection} id="materials" aria-labelledby="materials-title">
            <div className={styles.materialsPane}>
              <div className={styles.sectionHeading}><div><p className={styles.kicker}>可检索资料</p><h2 id="materials-title">资料库</h2></div><span className={styles.sectionHint}>文件直接进入 RAG</span></div>
              <form className={styles.uploadForm} onSubmit={handleUpload}>
                <input name="file" type="file" required accept=".txt,.csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp" />
                <select name="kind" defaultValue="REVIEW_EXPORT"><option value="PRODUCT_SHEET">商品参数</option><option value="COMPETITOR_SHEET">竞品资料</option><option value="REVIEW_EXPORT">用户评价</option><option value="BRAND_GUIDE">品牌手册</option><option value="PLATFORM_RULE">快手平台规则</option><option value="COMPETITOR_SCREENSHOT">竞品截图</option></select>
                <button type="submit" disabled={isSubmitting}>上传并解析</button>
              </form>
              <ul className={styles.materialList}>
                {workspace.documents.map((document) => <li key={document.id}><div className={styles.fileBadge} aria-hidden="true">{document.file_name.split(".").pop()?.toUpperCase() ?? "FILE"}</div><div className={styles.materialCopy}><strong>{document.file_name}</strong><span>{documentLabels[document.kind] ?? document.kind} · {Math.max(1, Math.ceil(document.size_bytes / 1024))} KB</span></div><span className={document.status === "READY" ? styles.readyState : styles.pendingState}>{documentStatus(document.status)}</span></li>)}
                {!workspace.documents.length ? <li><div className={styles.materialCopy}><strong>尚未上传资料</strong><span>可上传 SKU 表、竞品资料、用户评价、品牌手册或快手规则。</span></div></li> : null}
              </ul>
            </div>
            <aside className={styles.evidencePane} aria-labelledby="evidence-title"><p className={styles.kicker}>报告引用</p><h2 id="evidence-title">证据不是附注</h2><blockquote>{evidence?.excerpt ?? "先完成资料索引并生成报告，这里会展示每条结论所依据的原始片段。"}</blockquote><div className={styles.evidenceSource}><span>{evidence?.file_name ?? "暂无引用资料"}</span><span className={styles.mono}>{evidence ? `引用 ${evidence.position}` : "等待检索"}</span></div></aside>
          </section>

          <section className={styles.reportFrame} id="report" aria-labelledby="report-title">
            <div className={styles.reportHeader}><div><p className={styles.kicker}>待审核报告</p><h2 id="report-title">{activeReport?.title ?? "尚未生成选品报告"}</h2></div><span className={styles.reviewTag}>{activeReport?.status ?? "等待资料"}</span></div>
            <p className={styles.reportSummary}>{activeReport?.summary ?? "完成至少一份文字资料的索引后，即可根据候选商品、竞品与证据片段生成可复核报告。"}</p>
            <div className={styles.findingGrid}>{activeReport?.findings.map((finding) => <article className={styles.finding} key={finding.id}><p className={styles.findingType}>{finding.type}</p><h3>{finding.title}</h3><p>{finding.content}</p><span className={styles.citation}>{finding.citations[0] ? `引用 · ${finding.citations[0].file_name} / 引用 ${finding.citations[0].position}` : "暂无引用"}</span></article>)}</div>
            <div className={styles.reportFoot}><span>{activeReport ? "结论已保留来源片段，可由运营人员确认或驳回。" : "报告不会使用未索引资料生成结论。"}</span><div className={styles.buttonRow}><button type="button" onClick={handleCreateReport} disabled={isSubmitting}>生成报告</button>{activeReport ? <><button type="button" className={styles.secondaryButton} onClick={() => handleFeedback("APPROVED")} disabled={isSubmitting}>确认</button><button type="button" className={styles.secondaryButton} onClick={() => handleFeedback("REJECTED")} disabled={isSubmitting}>驳回</button></> : null}</div></div>
          </section>
        </> : null}
      </main>
      <footer className={styles.footer}><p>CommerceLens AI · 快手直播选品结论应可回溯至已授权资料</p></footer>
    </div>
  );
}
