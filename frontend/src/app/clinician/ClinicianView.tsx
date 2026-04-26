"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ActivePageCard } from "@/components/ActivePageCard";
import { StatusSegmented } from "@/components/StatusSegmented";
import { SbarCard } from "@/components/sbar/SbarCard";
import { PriorityBadge } from "@/components/badges";
import { getSocket } from "@/lib/socket";
import { getBackendSocket } from "@/lib/backendSocket";
import { getBrief } from "@/lib/backendApi";
import { getClinicians } from "@/lib/api";
import type {
  ClinicianRecord,
  ClinicianStatus,
  IncomingPagePayload,
  PageResolvedPayload,
} from "@/lib/types";
import type { SbarBrief } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

interface RecentItem {
  alert_id: string;
  title: string;
  priority: string;
  outcome: "incoming" | "accepted" | "declined" | "escalated" | "resolved";
  at: string;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - Date.parse(iso);
  if (Number.isNaN(ms)) return "";
  const min = Math.floor(ms / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

export function ClinicianView() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const [me, setMe] = useState<ClinicianRecord | null>(null);
  const [status, setStatus] = useState<ClinicianStatus>("available");
  const [current, setCurrent] = useState<IncomingPagePayload | null>(null);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [brief, setBrief] = useState<SbarBrief | null>(null);
  const [acceptedId, setAcceptedId] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getClinicians()
      .then((rows) => {
        const found = rows.find((r) => r.id === id) ?? null;
        setMe(found);
        if (found) setStatus((found.status as ClinicianStatus) ?? "available");
      })
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const socket = getSocket({ role: "clinician", clinicianId: id });

    const onIncoming = (p: IncomingPagePayload) => {
      setCurrent(p);
      setRecent((prev) =>
        [{ alert_id: p.alert_id, title: p.title, priority: p.priority, outcome: "incoming" as const, at: p.created_at }, ...prev].slice(0, 10),
      );
    };
    const onResolved = (r: PageResolvedPayload) => {
      setCurrent((cur) => (cur && cur.alert_id === r.alert_id ? null : cur));
      setRecent((prev) =>
        prev.map((x) => (x.alert_id === r.alert_id ? { ...x, outcome: r.outcome } : x)),
      );
    };

    socket.on("incoming_page", onIncoming);
    socket.on("page_resolved", onResolved);
    return () => {
      socket.off("incoming_page", onIncoming);
      socket.off("page_resolved", onResolved);
    };
  }, [id]);

  // Backend (Flask :8001) socket — listen for SBAR briefs delivered to this clinician
  useEffect(() => {
    if (!id) return;
    const socket = getBackendSocket({ role: "clinician", clinicianId: id });

    const onSbar = (b: SbarBrief) => {
      setBrief(b);
    };

    socket.on("sbar_brief", onSbar);
    return () => {
      socket.off("sbar_brief", onSbar);
    };
  }, [id]);

  // After accepting, fetch the brief if it didn't arrive via socket within ~1.5s
  useEffect(() => {
    if (!acceptedId) return;
    if (brief && (brief.page_id === acceptedId || brief.alert_id === acceptedId)) return;
    const t = window.setTimeout(() => {
      getBrief(acceptedId)
        .then((b) => setBrief(b))
        .catch(() => {});
    }, 1500);
    return () => window.clearTimeout(t);
  }, [acceptedId, brief]);

  function emitResponse(response: "accept" | "decline") {
    if (!current || !id) return;
    const socket = getSocket({ role: "clinician", clinicianId: id });
    socket.emit("page_response", { alert_id: current.alert_id, clinician_id: id, response });
    setRecent((prev) =>
      prev.map((x) =>
        x.alert_id === current.alert_id
          ? { ...x, outcome: response === "accept" ? "accepted" : "declined" }
          : x,
      ),
    );
    if (response === "accept") {
      setAcceptedId(current.alert_id);
    } else {
      setBrief(null);
      setAcceptedId(null);
    }
    setCurrent(null);
  }

  function changeStatus(next: ClinicianStatus) {
    setStatus(next);
    if (!id) return;
    const socket = getSocket({ role: "clinician", clinicianId: id });
    socket.emit("status_update", { clinician_id: id, status: next });
  }

  const onCall = useMemo(() => Boolean(me?.on_call), [me]);
  const displayName = me?.name ?? (id || "Clinician");

  if (!id) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--color-text-danger)" }}>
        Missing <code>?id=</code> query param. Try{" "}
        <a href="/clinician?id=dr_chen" style={{ textDecoration: "underline" }}>/clinician?id=dr_chen</a>.
      </div>
    );
  }

  return (
    <div
      className="mx-auto min-h-screen"
      style={{
        maxWidth: 430,
        background: "var(--color-background-tertiary)",
        color: "var(--color-text-primary)",
      }}
    >
      <header
        className="flex items-center justify-between"
        style={{ padding: "12px 16px", borderBottom: HAIRLINE, background: "var(--color-background-primary)" }}
      >
        <span style={{ fontSize: 15, fontWeight: 600 }}>Polaris</span>
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{displayName}</span>
          <span
            aria-label="online"
            style={{ width: 8, height: 8, borderRadius: "50%", background: status === "off_shift" ? "#9CA3AF" : "#1D9E75", display: "inline-block" }}
          />
        </div>
      </header>

      <main className="flex flex-col gap-3" style={{ padding: 14 }}>
        {onCall ? (
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-info)",
              background: "var(--color-background-info)",
              border: "0.5px solid var(--color-border-info)",
              padding: "6px 10px",
              borderRadius: 20,
              display: "inline-block",
              alignSelf: "flex-start",
            }}
          >
            On call
          </div>
        ) : null}

        {current ? (
          <ActivePageCard
            page={current}
            onAccept={() => emitResponse("accept")}
            onDecline={() => emitResponse("decline")}
          />
        ) : brief ? (
          <SbarCard
            brief={brief}
            onMarkRead={() => {
              setBrief(null);
              setAcceptedId(null);
            }}
          />
        ) : (
          <div
            style={{
              border: HAIRLINE,
              borderRadius: 12,
              padding: 16,
              background: "var(--color-background-primary)",
              fontSize: 12,
              color: "var(--color-text-tertiary)",
              textAlign: "center",
            }}
          >
            No active pages — you&apos;re all clear.
          </div>
        )}

        <div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
            Status
          </div>
          <StatusSegmented value={status} onChange={changeStatus} />
        </div>

        <div>
          <div style={{ fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
            Recent pages
          </div>
          <div style={{ border: HAIRLINE, borderRadius: 12, background: "var(--color-background-primary)", overflow: "hidden" }}>
            {recent.length === 0 ? (
              <div style={{ padding: "16px 12px", fontSize: 12, color: "var(--color-text-tertiary)", textAlign: "center" }}>
                No history yet.
              </div>
            ) : (
              recent.map((r, i) => (
                <div
                  key={`${r.alert_id}-${i}`}
                  className="flex items-start justify-between"
                  style={{
                    padding: "10px 12px",
                    borderBottom: i === recent.length - 1 ? "none" : HAIRLINE,
                    gap: 10,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{r.title}</div>
                    <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                      {r.outcome} · {timeAgo(r.at)}
                    </div>
                  </div>
                  <PriorityBadge priority={r.priority} />
                </div>
              ))
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
