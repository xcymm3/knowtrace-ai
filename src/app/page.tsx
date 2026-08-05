import { workspaceDemo } from "@/features/workspace/demo-workspace";
import styles from "./page.module.css";

export const dynamic = "force-static";

export default function Home() {
  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#main-content">
        跳至工作台
      </a>

      <nav className={styles.nav} aria-label="工作台导航">
        <a className={styles.brand} href="#overview">
          CommerceLens <span>AI</span>
        </a>
        <div className={styles.navLinks}>
          <a href="#products">商品池</a>
          <a href="#materials">资料库</a>
          <a href="#report">报告</a>
        </div>
        <span className={styles.demoFlag}>演示模式</span>
      </nav>

      <main className={styles.shell} id="main-content">
        <header className={styles.intro} id="overview">
          <div>
            <p className={styles.kicker}>电商选品与竞品调研</p>
            <h1>把选品依据放在一起</h1>
          </div>
          <p className={styles.introCopy}>
            统一查看候选商品、竞品资料、检索状态与待审核结论。资料进入索引后，报告中的每一条判断都可回到来源片段。
          </p>
        </header>

        <section className={styles.projectFrame} aria-labelledby="project-title">
          <div className={styles.projectIdentity}>
            <div className={styles.projectTopline}>
              <span className={styles.statusDot} aria-hidden="true" />
              <span>{workspaceDemo.project.status}</span>
              <span className={styles.mono}>项目 #{workspaceDemo.project.code}</span>
            </div>
            <h2 id="project-title">{workspaceDemo.project.name}</h2>
            <p>{workspaceDemo.project.description}</p>
            <dl className={styles.projectMeta}>
              <div>
                <dt>目标平台</dt>
                <dd>{workspaceDemo.project.platform}</dd>
              </div>
              <div>
                <dt>目标人群</dt>
                <dd>{workspaceDemo.project.audience}</dd>
              </div>
              <div>
                <dt>资料状态</dt>
                <dd>{workspaceDemo.project.materialState}</dd>
              </div>
            </dl>
          </div>

          <aside className={styles.runPanel} aria-labelledby="run-title">
            <div className={styles.panelHeading}>
              <div>
                <p className={styles.kicker}>当前任务</p>
                <h2 id="run-title">资料处理进度</h2>
              </div>
              <span className={styles.taskState}>运行中</span>
            </div>
            <ol className={styles.taskList}>
              {workspaceDemo.taskStages.map((stage) => (
                <li className={styles[`stage${stage.state}`]} key={stage.label}>
                  <span className={styles.stageMarker} aria-hidden="true" />
                  <div>
                    <strong>{stage.label}</strong>
                    <span>{stage.detail}</span>
                  </div>
                </li>
              ))}
            </ol>
            <p className={styles.runNote}>进度将通过 FastAPI 的 SSE 接口实时更新。</p>
          </aside>
        </section>

        <section className={styles.section} id="products" aria-labelledby="products-title">
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.kicker}>候选商品与竞品</p>
              <h2 id="products-title">商品池</h2>
            </div>
            <span className={styles.sectionHint}>价格与资料覆盖度并列展示</span>
          </div>

          <div className={styles.productGrid}>
            {workspaceDemo.products.map((product) => (
              <article className={styles.productCard} key={product.name}>
                <div className={styles.cardTopline}>
                  <span className={product.role === "自有候选" ? styles.ownTag : styles.competitorTag}>
                    {product.role}
                  </span>
                  <span className={styles.mono}>{product.coverage}</span>
                </div>
                <h3>{product.name}</h3>
                <p>{product.brand}</p>
                <dl className={styles.productData}>
                  <div>
                    <dt>登记价格</dt>
                    <dd>{product.price}</dd>
                  </div>
                  <div>
                    <dt>已识别属性</dt>
                    <dd>{product.attribute}</dd>
                  </div>
                </dl>
                <div className={styles.chipRow} aria-label={`${product.name}标签`}>
                  {product.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.splitSection} id="materials" aria-labelledby="materials-title">
          <div className={styles.materialsPane}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.kicker}>可检索资料</p>
                <h2 id="materials-title">资料库</h2>
              </div>
              <a className={styles.textLink} href="#report">查看报告</a>
            </div>
            <ul className={styles.materialList}>
              {workspaceDemo.materials.map((material) => (
                <li key={material.name}>
                  <div className={styles.fileBadge} aria-hidden="true">
                    {material.format}
                  </div>
                  <div className={styles.materialCopy}>
                    <strong>{material.name}</strong>
                    <span>{material.detail}</span>
                  </div>
                  <span className={material.state === "已索引" ? styles.readyState : styles.pendingState}>
                    {material.state}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <aside className={styles.evidencePane} aria-labelledby="evidence-title">
            <p className={styles.kicker}>本次检索引用</p>
            <h2 id="evidence-title">证据不是附注</h2>
            <blockquote>{workspaceDemo.evidence.excerpt}</blockquote>
            <div className={styles.evidenceSource}>
              <span>{workspaceDemo.evidence.source}</span>
              <span className={styles.mono}>{workspaceDemo.evidence.location}</span>
            </div>
          </aside>
        </section>

        <section className={styles.reportFrame} id="report" aria-labelledby="report-title">
          <div className={styles.reportHeader}>
            <div>
              <p className={styles.kicker}>待审核报告</p>
              <h2 id="report-title">{workspaceDemo.report.title}</h2>
            </div>
            <span className={styles.reviewTag}>{workspaceDemo.report.status}</span>
          </div>
          <p className={styles.reportSummary}>{workspaceDemo.report.summary}</p>
          <div className={styles.findingGrid}>
            {workspaceDemo.report.findings.map((finding) => (
              <article className={styles.finding} key={finding.title}>
                <p className={styles.findingType}>{finding.type}</p>
                <h3>{finding.title}</h3>
                <p>{finding.content}</p>
                <span className={styles.citation}>{finding.citation}</span>
              </article>
            ))}
          </div>
          <div className={styles.reportFoot}>
            <span>当前页面为界面演示数据，连接 API 后将读取实际项目与报告。</span>
            <a className={styles.textLink} href="#overview">回到项目概览</a>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>CommerceLens AI · 选品结论应可回溯至已授权资料</p>
      </footer>
    </div>
  );
}
