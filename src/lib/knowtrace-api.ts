export type WorkspaceStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";
export type TaskStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface WorkspaceProject {
  id: string;
  name: string;
  category: string | null;
  target_platform: string | null;
  target_audience: string | null;
  status: WorkspaceStatus;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  project_id: string;
  product_id: string | null;
  kind: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProcessingTask {
  id: string;
  project_id: string;
  document_id: string | null;
  task_type: string;
  status: TaskStatus;
  progress: number;
  attempt_count: number;
  max_attempts: number;
  output_payload: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export class ApiError extends Error {
  constructor(message: string, public readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError("无法连接后端服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "请求失败，请稍后重试。", payload?.error?.code);
  }
  return response.json() as Promise<T>;
}

export const knowTraceApi = {
  listWorkspaces: () => request<WorkspaceProject[]>("/api/v1/projects"),
  createWorkspace: (name: string) =>
    request<WorkspaceProject>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, category: null, target_platform: null, target_audience: null }),
    }),
  listDocuments: (workspaceId: string) => request<KnowledgeDocument[]>(`/api/v1/projects/${workspaceId}/documents`),
  listTasks: (workspaceId: string) => request<ProcessingTask[]>(`/api/v1/tasks/projects/${workspaceId}`),
  uploadDocument: (workspaceId: string, formData: FormData) =>
    request<{ task_id: string }>(`/api/v1/projects/${workspaceId}/documents`, { method: "POST", body: formData }),
  taskEvents: (taskId: string) => new EventSource(`/api/v1/tasks/${taskId}/events`),
};
