"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import controls from "@/app/page.module.css";
import { AgentRunConfig, AgentRunSnapshot, AgentRunStatus, AgentRunSummary, knowTraceApi } from "@/lib/knowtrace-api";

import styles from "./agent-panel.module.css";

const statusText: Record<AgentRunStatus, string> = {
  QUEUED: "已排队",
  RUNNING: "执行中",
  WAITING_APPROVAL: "等待审批",
  APPLYING: "正在写入",
  SUCCEEDED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};
const terminal = new Set<AgentRunStatus>(["SUCCEEDED", "FAILED", "CANCELLED"]);
const eventText = {
  tool_start: "调用", tool_end: "完成", tool_error: "工具错误", message: "Agent", error: "任务错误",
};
const approvalText = {
  pending: "待确认", approved: "已确认，等待执行器", rejected: "已拒绝",
  applying: "正在写入", applied: "已写入", failed: "写入失败", cancelled: "已取消",
};
const uuidPattern = "[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}";

function message(error: unknown) {
  return error instanceof Error ? error.message : "Agent 请求失败，请重试。";
}

export function AgentPanel({ workspaceId }: { workspaceId: string }) {
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [runId, setRunId] = useState("");
  const [snapshot, setSnapshot] = useState<AgentRunSnapshot | null>(null);
  const [executor, setExecutor] = useState("");
  const [config, setConfig] = useState<AgentRunConfig | null>(null);
  const [task, setTask] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState("");
  const selected = useRef("");
  const pending = useRef<{ id: string; executor: string | null; task: string } | null>(null);

  const selectRun = useCallback((id: string) => {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("run", id);
    else url.searchParams.delete("run");
    window.history.replaceState(null, "", url);
    selected.current = id;
    setRunId(id);
    setSnapshot(null);
    setError("");
    setReconnecting(false);
  }, []);

  const applySnapshot = useCallback((next: AgentRunSnapshot) => {
    if (next.id !== selected.current) return;
    setSnapshot((old) => old?.id === next.id && old.revision > next.revision ? old : next);
    setRuns((old) => old.map((run) =>
      run.id === next.id && run.revision <= next.revision
        ? { ...run, revision: next.revision, status: next.status }
        : run,
    ));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const execution = await knowTraceApi.getAgentRunConfig(workspaceId, controller.signal);
        if (controller.signal.aborted) return;
        setConfig(execution);
        const next = await knowTraceApi.listAgentRuns(workspaceId, controller.signal);
        if (controller.signal.aborted) return;
        setRuns(next);
        const fromUrl = new URL(window.location.href).searchParams.get("run");
        const initial = next.find((run) => run.id === fromUrl) ?? next[0];
        if (initial) {
          selectRun(initial.id);
          if (execution.mode === "remote") setExecutor(initial.executor_id);
        }
      } catch (caught) {
        if (!controller.signal.aborted) setError(message(caught));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [selectRun, workspaceId]);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();
    let resume: (() => void) | undefined;
    let retry: number | undefined;
    let revision = -1;
    let completed = false;
    function accept(next: AgentRunSnapshot) {
      if (controller.signal.aborted || next.revision <= revision) return;
      revision = next.revision;
      completed = terminal.has(next.status);
      setReconnecting(false);
      applySnapshot(next);
    }
    void (async () => {
      while (!controller.signal.aborted && !completed) {
        try {
          accept(await knowTraceApi.getAgentRun(workspaceId, runId, controller.signal));
          if (!completed && !controller.signal.aborted) {
            await knowTraceApi.streamAgentRun(workspaceId, runId, revision, accept, controller.signal);
          }
        } catch {
          if (!controller.signal.aborted) setReconnecting(true);
        }
        if (controller.signal.aborted || completed) break;
        await new Promise<void>((resolve) => {
          resume = resolve;
          retry = window.setTimeout(resolve, 1000);
        });
      }
    })();
    return () => {
      controller.abort();
      window.clearTimeout(retry);
      resume?.();
    };
  }, [applySnapshot, runId, workspaceId]);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = task.trim();
    const target = config?.mode === "remote" ? executor.trim() : null;
    if (!config || busy || !body || target === "") return;
    if (pending.current?.task !== body || pending.current.executor !== target) {
      pending.current = { id: crypto.randomUUID(), executor: target, task: body };
    }
    setBusy(true);
    setError("");
    try {
      const next = await knowTraceApi.createAgentRun(workspaceId, pending.current.id, target, body);
      pending.current = null;
      setRuns((old) => [next, ...old.filter((run) => run.id !== next.id)].slice(0, 30));
      selectRun(next.id);
      applySnapshot(next);
      setTask("");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  async function action(approved?: boolean) {
    if (!snapshot || busy) return;
    const approvalId = snapshot.approval?.id;
    if (approved !== undefined && !approvalId) return;
    setBusy(true);
    setError("");
    try {
      const next = approved !== undefined && approvalId
        ? await knowTraceApi.decideAgentRun(workspaceId, snapshot.id, approvalId, approved)
        : await knowTraceApi.cancelAgentRun(workspaceId, snapshot.id);
      applySnapshot(next);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  const approval = snapshot?.approval;
  return (
    <section className={styles.panel} aria-labelledby="agent-title">
      <header className={styles.heading}>
        <h2 id="agent-title">Agent 任务</h2>
        {config?.mode === "local" && <p>本地工作目录 · {config.directory}</p>}
        {config?.mode === "remote" && <details>
          <summary>连接本地执行器</summary>
          <p>在项目 backend 目录运行命令，再将终端显示的执行器 ID 填入下方。</p>
          <pre><code>{`uv run python -m app.features.agent --serve --root "<本地目录>" --workspace-id "${workspaceId}"`}</code></pre>
        </details>}
      </header>
      <form className={styles.form} onSubmit={start}>
        {config?.mode === "remote" && <>
          <label htmlFor="agent-executor">执行器 ID</label>
          <input id="agent-executor" value={executor} onChange={(event) => setExecutor(event.target.value)}
            required pattern={uuidPattern} placeholder="粘贴终端显示的 UUID" spellCheck={false} />
        </>}
        <label htmlFor="agent-task">任务</label>
        <textarea id="agent-task" value={task} onChange={(event) => setTask(event.target.value)}
          required maxLength={8000} rows={3} placeholder="例如，根据部署说明修正本地 README 的启动端口" />
        <button className={controls.primaryButton} type="submit" disabled={busy || loading || !config}>发起任务</button>
      </form>
      <div aria-live="assertive">{error && <p className={controls.feedbackError}>{error}</p>}</div>
      {runs.length > 0 && (
        <div className={styles.history}>
          <label htmlFor="agent-history">任务记录</label>
          <select id="agent-history" value={runId} onChange={(event) => selectRun(event.target.value)}>
            {runs.map((run) => <option key={run.id} value={run.id}>
              {statusText[run.status]} · {run.task.slice(0, 80)}
            </option>)}
          </select>
        </div>
      )}
      <p className={styles.status} role="status">
        {reconnecting ? "任务连接中断，正在重连…" : loading ? "正在读取任务记录…" :
          snapshot?.cancel_requested && snapshot.status === "APPLYING" ? "已请求取消，正在等待写入结果" :
          snapshot?.status === "WAITING_APPROVAL" && approval?.status === "approved" ? approvalText.approved :
          snapshot ? statusText[snapshot.status] : runId ? "正在读取任务…" : ""}
      </p>
      {snapshot && (
        <article className={styles.run}>
          <div className={styles.runHeading}>
            <h3>{snapshot.task}</h3>
            {!terminal.has(snapshot.status) && (
              <button className={controls.secondaryButton} type="button"
                disabled={busy || snapshot.cancel_requested} onClick={() => void action()}>取消任务</button>
            )}
          </div>
          {approval && (
            <section className={styles.approval} aria-labelledby="agent-diff-title">
              <h4 id="agent-diff-title">文件变更 · {approval.path}</h4>
              <p>{approvalText[approval.status]}</p>
              <div className={styles.diffScroll} role="region" tabIndex={0} aria-labelledby="agent-diff-title">
                <pre><code>{approval.diff.split("\n").map((line, index) => (
                  <span key={index} data-kind={line.startsWith("+") ? "addition" : line.startsWith("-") ? "deletion" : undefined}>
                    {line}{"\n"}
                  </span>
                ))}</code></pre>
              </div>
              {approval.error && <p className={controls.feedbackError}>{approval.error}</p>}
              {approval.change_id && <p>回退 ID <code>{approval.change_id}</code></p>}
              {approval.status === "pending" && (
                <div className={styles.actions}>
                  <button className={controls.secondaryButton} type="button" disabled={busy}
                    onClick={() => void action(false)}>拒绝变更</button>
                  <button className={controls.primaryButton} type="button" disabled={busy}
                    onClick={() => void action(true)}>确认写入</button>
                </div>
              )}
            </section>
          )}
          {snapshot.events.length > 0 && (
            <section aria-labelledby="agent-events-title">
              <h4 id="agent-events-title">执行记录</h4>
              <ol className={styles.events}>
                {snapshot.events.map((entry, index) => (
                  <li key={index}><strong>{eventText[entry.kind]}</strong><span>{entry.text}</span></li>
                ))}
              </ol>
            </section>
          )}
        </article>
      )}
    </section>
  );
}
