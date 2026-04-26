import { io, Socket } from "socket.io-client";

export type BackendSocketRole = "operator" | "clinician";

export interface BackendSocketOpts {
  role: BackendSocketRole;
  clinicianId?: string;
}

const url = () =>
  process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001";

const cache = new Map<string, Socket>();

function cacheKey(opts: BackendSocketOpts): string {
  return `${opts.role}:${opts.clinicianId ?? ""}`;
}

export function getBackendSocket(opts: BackendSocketOpts): Socket {
  const key = cacheKey(opts);
  const existing = cache.get(key);
  if (existing) return existing;

  const socket = io(url(), {
    transports: ["websocket", "polling"],
    auth: {
      role: opts.role,
      clinician_id: opts.clinicianId,
    },
    reconnection: true,
    reconnectionDelay: 500,
  });

  cache.set(key, socket);
  return socket;
}

export function disposeBackendSocket(opts: BackendSocketOpts): void {
  const key = cacheKey(opts);
  const socket = cache.get(key);
  if (socket) {
    socket.disconnect();
    cache.delete(key);
  }
}
