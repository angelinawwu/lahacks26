import { io, Socket } from "socket.io-client";

export type SocketRole = "operator" | "clinician";

export interface SocketOpts {
  role: SocketRole;
  clinicianId?: string;
}

const url = () =>
  process.env.NEXT_PUBLIC_SOCKET_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

const cache = new Map<string, Socket>();

function cacheKey(opts: SocketOpts): string {
  return `${opts.role}:${opts.clinicianId ?? ""}`;
}

export function getSocket(opts: SocketOpts): Socket {
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

export function disposeSocket(opts: SocketOpts): void {
  const key = cacheKey(opts);
  const socket = cache.get(key);
  if (socket) {
    socket.disconnect();
    cache.delete(key);
  }
}
