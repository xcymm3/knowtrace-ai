export type Permission = "read_only" | "project" | "full";
export type Status = "QUEUED" | "RUNNING" | "WAITING_APPROVAL" | "APPLYING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface RunSummary {
  id: string;
  thread_id: string;
  task: string;
  permission: Permission;
  status: Status;
  revision: number;
  created_at: string;
}

export interface Run extends RunSummary {
  cancel_requested: boolean;
  events: { kind: "tool_start" | "tool_end" | "tool_error" | "message" | "error"; text: string }[];
  approval: {
    id: string;
    path: string;
    diff: string;
    status: "pending" | "approved" | "rejected" | "applying" | "applied" | "failed" | "cancelled";
    error: string | null;
    change_id: string | null;
  } | null;
}

async function request<T>(path: string, signal?: AbortSignal, body?: object): Promise<T> {
  const response = await fetch(`/api/v1/agent${path}`, {
    signal,
    cache: "no-store",
    ...(body && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message ?? `Agent 请求失败（${response.status}）`);
  return data as T;
}

export const api = {
  config: (signal: AbortSignal) => request<{ directory: string }>("/config", signal),
  threads: (signal: AbortSignal) => request<RunSummary[]>("/threads", signal),
  thread: (id: string, signal: AbortSignal) => request<Run[]>(`/threads/${id}`, signal),
  start: (body: { id: string; thread_id: string; task: string; permission: Permission }) => request<Run>("/runs", undefined, body),
  decide: (id: string, approvalId: string, approved: boolean) => request<Run>(`/runs/${id}/decision`, undefined, { approval_id: approvalId, approved }),
  cancel: (id: string) => request<Run>(`/runs/${id}/cancel`, undefined, {}),
};
