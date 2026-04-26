import type { ProactiveAcked, QueuePage, QueueResponse, SbarBrief } from "./backendTypes";

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
