import Link from "next/link";

import styles from "./recovery-page.module.css";

export default function NotFound() {
  return (
    <main className={styles.page}>
      <section className={styles.panel} aria-labelledby="not-found-heading">
        <p className={styles.eyebrow}>404 · 页面未找到</p>
        <h1 className={styles.title} id="not-found-heading">
          请求的页面不存在
        </h1>
        <p className={styles.copy}>请返回 KnowTrace 工作台，选择项目后继续处理资料或对话。</p>
        <div className={styles.actions}>
          <Link className={styles.primaryAction} href="/">
            返回工作台
          </Link>
        </div>
      </section>
    </main>
  );
}
