import type {
  AppSettings,
  PagingModesState,
  ProactiveAcked,
  QueuePage,
  QueueResponse,
  SbarBrief,
} from "./backendTypes";

const base = () =>
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001";

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const t = await r.text().catch(() => r.statusText);
    throw new Error(t || r.statusText);
  }
  return (await r.json()) as T;
}

export async function getQueue(): Promise<QueueResponse> {
  const r = await fetch(`${base()}/api/queue`, { cache: "no-store" });
  return jsonOrThrow<QueueResponse>(r);
}

export async function escalatePage(pageId: string): Promise<QueuePage> {
  const r = await fetch(`${base()}/api/queue/${pageId}/escalate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return jsonOrThrow<QueuePage>(r);
}

export async function cancelPage(pageId: string): Promise<QueuePage> {
  const r = await fetch(`${base()}/api/queue/${pageId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return jsonOrThrow<QueuePage>(r);
}

export async function ackProactive(
  recId: string,
  body: { outcome: "approve" | "reject"; operator_id?: string },
): Promise<ProactiveAcked> {
  const r = await fetch(`${base()}/api/proactive/${recId}/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return jsonOrThrow<ProactiveAcked>(r);
}

export async function getBrief(pageId: string): Promise<SbarBrief> {
  const r = await fetch(`${base()}/api/brief/${pageId}`, { cache: "no-store" });
  return jsonOrThrow<SbarBrief>(r);
}

export async function respondToPage(
  pageId: string,
  outcome: "accept" | "decline",
): Promise<QueuePage> {
  const r = await fetch(`${base()}/api/page/${pageId}/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome }),
  });
  return jsonOrThrow<QueuePage>(r);
}

export async function resolvePage(pageId: string): Promise<QueuePage> {
  const r = await fetch(`${base()}/api/page/${pageId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return jsonOrThrow<QueuePage>(r);
}

export async function getSettings(): Promise<AppSettings> {
  const r = await fetch(`${base()}/api/settings`, { cache: "no-store" });
  return jsonOrThrow<AppSettings>(r);
}

export async function updateSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
  const r = await fetch(`${base()}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return jsonOrThrow<AppSettings>(r);
}

export async function getPagingModes(): Promise<PagingModesState> {
  const r = await fetch(`${base()}/api/paging-modes`, { cache: "no-store" });
  return jsonOrThrow<PagingModesState>(r);
}

export async function setGlobalPagingMode(
  mode: "automated" | "manual",
  operatorId = "operator",
  reason = "",
): Promise<{ global_mode: "automated" | "manual" }> {
  const r = await fetch(`${base()}/api/paging-modes/global`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, operator_id: operatorId, reason }),
  });
  return jsonOrThrow(r);
}
