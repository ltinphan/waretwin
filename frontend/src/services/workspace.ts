import type { WarehouseLayout } from "../layout/types";

export interface Warehouse {
  id: string;
  name: string;
  created_at: string;
}

export interface LayoutRevision {
  id: string;
  warehouse_id: string;
  state: "draft" | "published";
  version: number;
  document: WarehouseLayout;
  created_at: string;
}

export class WorkspaceError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface LayoutValidation {
  version: number;
  valid: boolean;
  issues: { path: string; code: string; message: string; severity: 'error' }[];
}

/** Tokens remain in memory; callers clear their client on sign-out. */
export function workspaceClient(token: string) {
  async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    const response = await fetch(`/api/workspace${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new WorkspaceError(response.status,
        typeof data?.detail === "string" ? data.detail : "Workspace request failed");
    }
    return data as T;
  }

  const revisionPath = (warehouse: string, revision: string) =>
    `/warehouses/${encodeURIComponent(warehouse)}/revisions/${encodeURIComponent(revision)}`;

  return {
    me: () => request<{ organization_id: string; user_id: string }>("/me"),
    warehouses: () => request<Warehouse[]>("/warehouses"),
    create: (name: string, document: WarehouseLayout) =>
      request<LayoutRevision>("/warehouses", "POST", { name, document }),
    createEmpty: (name: string, width: number, depth: number, height: number) =>
      request<LayoutRevision>("/warehouses/empty", "POST", { name, width, depth, height }),
    revisions: (warehouse: string) => request<Omit<LayoutRevision, "document" | "warehouse_id">[]>(
      `/warehouses/${encodeURIComponent(warehouse)}/revisions`),
    revision: (warehouse: string, revision: string) =>
      request<LayoutRevision>(revisionPath(warehouse, revision)),
    validate: (revision: LayoutRevision) =>
      request<LayoutValidation>(`${revisionPath(revision.warehouse_id, revision.id)}/validation`),
    save: (revision: LayoutRevision, document: WarehouseLayout) =>
      request<LayoutRevision>(revisionPath(revision.warehouse_id, revision.id), "PUT", {
        expected_version: revision.version, document,
      }),
    publish: (revision: LayoutRevision) =>
      request<LayoutRevision>(`${revisionPath(revision.warehouse_id, revision.id)}/publish`, "POST", {
        expected_version: revision.version,
      }),
    fork: (revision: LayoutRevision) =>
      request<LayoutRevision>(`${revisionPath(revision.warehouse_id, revision.id)}/fork`, "POST"),
  };
}
