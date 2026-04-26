"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ActivePageCard } from "@/components/ActivePageCard";
import { StatusSegmented } from "@/components/StatusSegmented";
import { SbarCard } from "@/components/sbar/SbarCard";
import { ClinicianPageForm } from "@/components/clinician/ClinicianPageForm";
import { PriorityBadge } from "@/components/badges";
import { getBackendSocket } from "@/lib/backendSocket";
import { getBrief, resolvePage, respondToPage } from "@/lib/backendApi";
import { getClinicians } from "@/lib/api";
import type {
  ClinicianRecord,
  ClinicianStatus,
  IncomingPagePayload,
} from "@/lib/types";
import type { SbarBrief } from "@/lib/backendTypes";

// Flask `incoming_page` payload shape.
interface FlaskIncomingPage {
  page_id: string;
  message?: string;
  patient_id?: string | null;
  room?: string | null;
  priority: string;
  created_at: string;
  ack_deadline_seconds?: number;
}

function toIncomingPayload(p: FlaskIncomingPage): IncomingPagePayload {
  return {
    alert_id: p.page_id,
    title: p.message || p.room || `Page ${p.page_id.slice(0, 6)}`,
    room: p.room ?? null,
    priority: p.priority,
    reasoning: p.message ?? "",
    created_at: p.created_at,
    ack_deadline_seconds: p.ack_deadline_seconds ?? 60,
  };
}

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

export function ClinicianView({ id }: { id: string }) {
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

  // Flask :8001 socket — incoming pages + SBAR briefs for this clinician.
  useEffect(() => {
    if (!id) return;
    const socket = getBackendSocket({ role: "clinician", clinicianId: id });

    const onIncoming = (raw: FlaskIncomingPage) => {
      const p = toIncomingPayload(raw);
      setCurrent(p);
      setRecent((prev) =>
        [
          {
            alert_id: p.alert_id,
            title: p.title,
            priority: p.priority,
            outcome: "incoming" as const,
            at: p.created_at,
          },
          ...prev,
        ].slice(0, 10),
      );
    };
    const onSbar = (b: SbarBrief) => {
      setBrief(b);
    };

    socket.on("incoming_page", onIncoming);
    socket.on("sbar_brief", onSbar);
    return () => {
      socket.off("incoming_page", onIncoming);
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
    const pageId = current.alert_id;
    // Flask exposes responses via REST; fire-and-forget for snappy UI.
    respondToPage(pageId, response).catch(() => {});
    setRecent((prev) =>
      prev.map((x) =>
        x.alert_id === pageId
          ? { ...x, outcome: response === "accept" ? "accepted" : "declined" }
          : x,
      ),
    );
    if (response === "accept") {
      setAcceptedId(pageId);
      setStatus("on_case");
    } else {
      setBrief(null);
      setAcceptedId(null);
    }
    setCurrent(null);
  }

  function resolveCurrent() {
    if (!acceptedId) return;
    const pageId = acceptedId;
    resolvePage(pageId).catch(() => {});
    setRecent((prev) =>
      prev.map((x) => (x.alert_id === pageId ? { ...x, outcome: "resolved" } : x)),
    );
    setBrief(null);
    setAcceptedId(null);
    setStatus("available");
  }

  function changeStatus(next: ClinicianStatus) {
    setStatus(next);
    if (!id) return;
    const socket = getBackendSocket({ role: "clinician", clinicianId: id });
    socket.emit("status_update", { clinician_id: id, status: next });
  }

  const onCall = useMemo(() => Boolean(me?.on_call), [me]);
  const displayName = me?.name ?? (id || "Clinician");

  if (!id) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--color-text-danger)" }}>
        Missing clinician id. Try{" "}
        <Link href="/clinician" style={{ textDecoration: "underline" }}>
          the clinician directory
        </Link>
        .
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
        <Link
          href="/clinician"
          style={{ fontSize: 12, color: "var(--color-text-secondary)", textDecoration: "none" }}
          aria-label="Back to clinician directory"
        >
          ← Directory
        </Link>
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
            onResolve={resolveCurrent}
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

        <ClinicianPageForm clinicianId={id} />

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
