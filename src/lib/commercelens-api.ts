export type ProjectStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";
export type ProductRole = "OWN" | "COMPETITOR";
export type TaskStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface ResearchProject {
  id: string;
  name: string;
  category: string | null;
  target_platform: string | null;
  target_audience: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface Product {
  id: string;
  project_id: string;
  role: ProductRole;
  name: string;
  brand_name: string | null;
  external_url: string | null;
  price: number | null;
  currency: string | null;
  description: string | null;
  attributes: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProductComparisonItem {
  product: Product;
  document_count: number;
  indexed_document_count: number;
}

export interface ProductComparison {
  project_id: string;
  own_product_count: number;
  competitor_product_count: number;
  products: ProductComparisonItem[];
}

export interface SourceDocument {
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

export interface ResearchTask {
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

export interface ReportCitation {
  id: string;
  excerpt: string;
  file_name: string;
  kind: string;
  position: number;
}

export interface ReportFinding {
  id: string;
  type: string;
  title: string;
  content: string;
  citations: ReportCitation[];
}

export interface SelectionReport {
  id: string;
  project_id: string;
  title: string;
  summary: string | null;
  status: string;
  findings: ReportFinding[];
  created_at: string;
}

export class ApiError extends Error {
  constructor(message: string, public readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

function apiBaseUrl() {
  // The browser always talks to the same Next.js origin. In local development
  // the route handler proxies requests to FastAPI; on Vercel, vercel.json
  // routes the same path to the backend service.
  return "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("无法连接后端服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string } }
      | null;
    throw new ApiError(payload?.error?.message ?? "请求失败，请稍后重试。", payload?.error?.code);
  }
  return response.json() as Promise<T>;
}

export const commerceLensApi = {
  listProjects: () => request<ResearchProject[]>("/api/v1/projects"),
  createProject: (payload: Pick<ResearchProject, "name" | "category" | "target_platform" | "target_audience">) =>
    request<ResearchProject>("/api/v1/projects", { method: "POST", body: JSON.stringify(payload) }),
  getComparison: (projectId: string) =>
    request<ProductComparison>(`/api/v1/projects/${projectId}/comparison`),
  createProduct: (
    projectId: string,
    payload: Pick<Product, "role" | "name" | "brand_name" | "price" | "currency" | "description" | "attributes">,
  ) => request<Product>(`/api/v1/projects/${projectId}/products`, { method: "POST", body: JSON.stringify(payload) }),
  listDocuments: (projectId: string) =>
    request<SourceDocument[]>(`/api/v1/projects/${projectId}/documents`),
  listTasks: (projectId: string) => request<ResearchTask[]>(`/api/v1/tasks/projects/${projectId}`),
  uploadDocument: (projectId: string, formData: FormData) =>
    request<{ task_id: string }>(`/api/v1/projects/${projectId}/documents`, {
      method: "POST",
      body: formData,
    }),
  listReports: (projectId: string) => request<SelectionReport[]>(`/api/v1/projects/${projectId}/reports`),
  createReport: (projectId: string) =>
    request<SelectionReport>(`/api/v1/projects/${projectId}/reports`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  submitFeedback: (projectId: string, reportId: string, decision: "APPROVED" | "REJECTED") =>
    request(`/api/v1/projects/${projectId}/reports/${reportId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    }),
  taskEvents: (taskId: string) => new EventSource(`${apiBaseUrl()}/api/v1/tasks/${taskId}/events`),
};
