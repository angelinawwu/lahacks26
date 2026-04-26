"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertFeed, isAlertLive } from "@/components/AlertFeed";
import { FloorMap } from "@/components/FloorMap";
import { CasesTable } from "@/components/CasesTable";
import { CountBadge } from "@/components/badges";
import { QueuePanel } from "@/components/queue/QueuePanel";
import { ProactiveModal } from "@/components/proactive/ProactiveModal";
import { RecsBadge, hasCriticalRec } from "@/components/proactive/RecsBadge";
import { CoverageBanner } from "@/components/CoverageBanner";
import { getBackendSocket } from "@/lib/backendSocket";
import { getClinicians } from "@/lib/api";
import { getQueue, getSettings } from "@/lib/backendApi";
import { PendingApprovalRow } from "@/components/operator/PendingApprovalRow";
import { ManualOverridePanel } from "@/components/operator/ManualOverridePanel";
import Link from "next/link";
import { inferFloorWing } from "@/lib/floorData";
import type { FloorId } from "@/lib/floorData";
import type {
  ActiveAlert,
  AlertEvent,
  ClinicianPin,
  ClinicianRecord,
  ClinicianStatus,
  PriorityLevel,
} from "@/lib/types";
import type {
  PatternSignal,
  ProactiveRecommendation,
  QueuePage,
} from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

// Map a Flask page record into the AlertEvent shape used by the operator UI.
function pageToAlert(page: QueuePage): AlertEvent {
  const status: AlertEvent["status"] =
    page.status === "accepted"
      ? "accepted"
      : page.status === "declined"
        ? "declined"
        : page.status === "escalated"
          ? "escalating"
          : page.status === "cancelled" || page.status === "resolved"
            ? "resolved"
            : "paging";
  return {
    alert_id: page.id,
    title: page.message || page.room || page.id,
    room: page.room ?? null,
    priority: page.priority,
    assigned_clinician_id: page.doctor_id ?? null,
    assigned_clinician_name: page.doctor?.name,
    specialty: page.doctor?.specialty,
    status,
    created_at: page.created_at,
    ack_deadline_seconds: page.timeout_seconds ?? 60,
    responded_at: page.responded_at ?? undefined,
  };
}

export default function OperatorPage() {
  const [defaultViewLoaded, setDefaultViewLoaded] = useState(false);
  const [tab, setTab] = useState<1 | 2>(1);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [clinicians, setClinicians] = useState<ClinicianRecord[]>([]);
  const [selectedFloor, setSelectedFloor] = useState<FloorId | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<ActiveAlert | null>(null);

  // Backend (Flask :8001) state
  const [queue, setQueue] = useState<QueuePage[]>([]);
  const [pending, setPending] = useState<QueuePage[]>([]);
  const [recs, setRecs] = useState<ProactiveRecommendation[]>([]);
  const [activeRec, setActiveRec] = useState<ProactiveRecommendation | null>(null);
  const [recsOpen, setRecsOpen] = useState(false);
  const [patterns, setPatterns] = useState<PatternSignal[]>([]);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [manualMode, setManualMode] = useState(false);

  // Load default operator view and manual mode state once on mount
  useEffect(() => {
    if (defaultViewLoaded) return;
    getSettings()
      .then((s) => {
        setTab(s.default_operator_view === "feed" ? 2 : 1);
        setManualMode(s.global_mode === "manual");
      })
      .catch(() => {})
      .finally(() => setDefaultViewLoaded(true));
  }, [defaultViewLoaded]);

  // Flask :8001 socket — sole backend connection (alerts, queue, proactive, patterns).
  useEffect(() => {
    getClinicians().then(setClinicians).catch(() => {});

    const socket = getBackendSocket({ role: "operator" });

    const upsertAlert = (a: AlertEvent) => {
      setAlerts((prev) => {
        const idx = prev.findIndex((x) => x.alert_id === a.alert_id);
        if (idx === -1) return [a, ...prev];
        const copy = prev.slice();
        copy[idx] = { ...copy[idx], ...a };
        return copy;
      });
    };
    const upsertQueue = (page: QueuePage) => {
      setQueue((prev) => {
        const idx = prev.findIndex((p) => p.id === page.id);
        if (idx === -1) return [page, ...prev];
        const copy = prev.slice();
        copy[idx] = { ...copy[idx], ...page };
        return copy;
      });
    };
    const removeQueue = (id: string) => {
      setQueue((prev) => prev.filter((p) => p.id !== id));
    };

    const onSnapshot = (snap: {
      doctors?: ClinicianRecord[];
      active_pages?: QueuePage[];
    }) => {
      if (Array.isArray(snap?.doctors)) setClinicians(snap.doctors);
      if (Array.isArray(snap?.active_pages)) {
        setAlerts(snap.active_pages.map(pageToAlert).reverse());
      }
    };
    const onPendingApproval = (page: QueuePage) => {
      setPending((prev) => {
        const idx = prev.findIndex((p) => p.id === page.id);
        if (idx === -1) return [page, ...prev];
        const copy = prev.slice();
        copy[idx] = { ...copy[idx], ...page };
        return copy;
      });
    };

    const onPaged = (page: QueuePage) => {
      const a = pageToAlert(page);
      upsertAlert(a);
      upsertQueue(page);
      if (a.assigned_clinician_id) {
        setClinicians((prev) =>
          prev.map((c) =>
            c.id === a.assigned_clinician_id ? { ...c, status: "paging" } : c,
          ),
        );
      }
    };
    const onPageResponse = (page: QueuePage) => {
      const a = pageToAlert(page);
      upsertAlert(a);
      if (
        page.status === "accepted" ||
        page.status === "declined" ||
        page.status === "resolved"
      ) {
        removeQueue(page.id);
      } else {
        upsertQueue(page);
      }
      if (a.assigned_clinician_id && a.status === "accepted") {
        setClinicians((prev) =>
          prev.map((c) =>
            c.id === a.assigned_clinician_id ? { ...c, status: "on_case" } : c,
          ),
        );
      }
    };
    const onPageEscalated = (page: QueuePage) => {
      upsertAlert(pageToAlert(page));
      upsertQueue(page);
    };
    const onPageCancelled = (page: QueuePage) => {
      upsertAlert(pageToAlert(page));
      removeQueue(page.id);
      setPending((prev) => prev.filter((p) => p.id !== page.id));
    };

    const onSettingsUpdated = (s: { global_mode?: string }) => {
      if (s.global_mode !== undefined) setManualMode(s.global_mode === "manual");
    };
    const onModesUpdated = (m: { global_mode?: string }) => {
      if (m.global_mode !== undefined) setManualMode(m.global_mode === "manual");
    };
    const onDoctorChanged = (e: { id: string; status?: string; zone?: string }) => {
      setClinicians((prev) =>
        prev.map((c) =>
          c.id === e.id
            ? { ...c, status: (e.status as ClinicianStatus) ?? c.status, zone: e.zone ?? c.zone }
            : c,
        ),
      );
    };

    const onProactive = (rec: ProactiveRecommendation) => {
      setRecs((prev) => {
        const exists = prev.some((r) => r.id === rec.id);
        return exists ? prev.map((r) => (r.id === rec.id ? rec : r)) : [rec, ...prev];
      });
      if (rec.requires_ack) {
        setActiveRec((cur) => cur ?? rec);
      }
    };
    const onProactiveAcked = (data: { id: string }) => {
      setRecs((prev) => prev.filter((r) => r.id !== data.id));
      setActiveRec((cur) => (cur && cur.id === data.id ? null : cur));
    };

    const onPattern = (p: PatternSignal) => {
      setPatterns((prev) => {
        const key = (x: PatternSignal) => `${x.pattern_type}:${x.zone ?? ""}:${x.specialty ?? ""}`;
        const k = key(p);
        const without = prev.filter((x) => key(x) !== k);
        return [p, ...without].slice(0, 12);
      });
    };
    const onPatternCleared = (p: PatternSignal) => {
      setPatterns((prev) =>
        prev.filter(
          (x) =>
            !(x.pattern_type === p.pattern_type &&
              (x.zone ?? "") === (p.zone ?? "") &&
              (x.specialty ?? "") === (p.specialty ?? "")),
        ),
      );
    };

    socket.on("snapshot", onSnapshot);
    socket.on("page_pending_approval", onPendingApproval);
    socket.on("doctor_paged", onPaged);
    socket.on("alert_created", onPaged);
    socket.on("page_response", onPageResponse);
    socket.on("page_escalated", onPageEscalated);
    socket.on("page_cancelled", onPageCancelled);
    socket.on("doctor_status_changed", onDoctorChanged);
    socket.on("proactive_recommendation", onProactive);
    socket.on("proactive_recommendation_acked", onProactiveAcked);
    socket.on("pattern_detected", onPattern);
    socket.on("pattern_cleared", onPatternCleared);
    socket.on("settings_updated", onSettingsUpdated);
    socket.on("paging_modes_updated", onModesUpdated);

    getQueue()
      .then((res) => {
        const pages = res.pages ?? [];
        setQueue(pages);
        setAlerts((prev) => (prev.length > 0 ? prev : pages.map(pageToAlert).reverse()));
      })
      .catch(() => {});

    return () => {
      socket.off("snapshot", onSnapshot);
      socket.off("page_pending_approval", onPendingApproval);
      socket.off("doctor_paged", onPaged);
      socket.off("alert_created", onPaged);
      socket.off("page_response", onPageResponse);
      socket.off("page_escalated", onPageEscalated);
      socket.off("page_cancelled", onPageCancelled);
      socket.off("doctor_status_changed", onDoctorChanged);
      socket.off("proactive_recommendation", onProactive);
      socket.off("proactive_recommendation_acked", onProactiveAcked);
      socket.off("pattern_detected", onPattern);
      socket.off("pattern_cleared", onPatternCleared);
      socket.off("settings_updated", onSettingsUpdated);
      socket.off("paging_modes_updated", onModesUpdated);
    };
  }, []);

  const liveCount = useMemo(() => alerts.filter(isAlertLive).length, [alerts]);

  const handleFloorSelect = (floor: FloorId) => {
    setSelectedFloor(floor);
    setTab(1);
  };

  const handleAlertSelect = (alert: ActiveAlert | null) => {
    setSelectedAlert(alert);
    if (alert) {
      setSelectedFloor(alert.floor);
      setTab(1);
    }
  };

  const clinicianPins: ClinicianPin[] = useMemo(
    () =>
      clinicians.map((c) => {
        const { floor, wing } = inferFloorWing(c.zone);
        return {
          id: c.id,
          name: c.name,
          floor,
          wing,
          zone: c.zone,
          status: (c.status as ClinicianStatus) ?? "available",
          on_call: c.on_call,
          page_count_1hr: c.page_count_1hr,
          active_cases: c.active_cases,
        };
      }),
    [clinicians],
  );

  const activeAlerts: ActiveAlert[] = useMemo(
    () =>
      alerts.filter(isAlertLive).map((a) => {
        const { floor, wing } = inferFloorWing(a.room);
        return {
          alert_id: a.alert_id,
          floor,
          wing,
          zone: a.room ?? "",
          priority: (a.priority as PriorityLevel) ?? "P3",
        };
      }),
    [alerts],
  );

  const upsertQueueLocal = (p: QueuePage) => {
    setQueue((prev) => {
      const idx = prev.findIndex((x) => x.id === p.id);
      if (p.status === "cancelled" || p.status === "accepted" || p.status === "declined") {
        return prev.filter((x) => x.id !== p.id);
      }
      if (idx === -1) return [p, ...prev];
      const copy = prev.slice();
      copy[idx] = { ...copy[idx], ...p };
      return copy;
    });
  };

  const showRecsList = recsOpen && !activeRec;
  const recToShow = activeRec ?? (showRecsList ? recs[0] ?? null : null);

  return (
    <div
      className="min-h-screen"
      style={{
        background: "var(--color-background-primary)",
        color: "var(--color-text-primary)",
        fontSize: 13,
      }}
    >
      <div
        className="flex items-center justify-between"
        style={{ padding: "12px 16px", borderBottom: HAIRLINE, background: "var(--color-background-primary)" }}
      >
        <span style={{ fontSize: 15, fontWeight: 500 }}>Polaris — Operator</span>
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            UCLA Medical Center · Santa Monica
          </span>
          <Link
            href="/clinician"
            style={{
              fontSize: 12,
              padding: "4px 10px",
              border: HAIRLINE,
              borderRadius: 20,
              color: "var(--color-text-secondary)",
              textDecoration: "none",
              transition: "background 200ms ease",
            }}
          >
            Clinicians
          </Link>
          <Link
            href="/settings"
            style={{
              fontSize: 12,
              padding: "4px 10px",
              border: HAIRLINE,
              borderRadius: 20,
              color: "var(--color-text-secondary)",
              textDecoration: "none",
              transition: "background 200ms ease",
            }}
          >
            Settings
          </Link>
          <RecsBadge
            count={recs.length}
            hasCritical={hasCriticalRec(recs)}
            onClick={() => {
              if (recs.length === 0) return;
              setActiveRec(recs[0]);
              setRecsOpen(true);
            }}
          />
          <button
            type="button"
            onClick={() => setOverrideOpen(true)}
            style={{
              fontSize: 12,
              padding: "4px 10px",
              border: manualMode ? "0.5px solid #E0A100" : HAIRLINE,
              borderRadius: 20,
              color: manualMode ? "#E0A100" : "var(--color-text-secondary)",
              background: manualMode ? "rgba(224,161,0,0.08)" : "transparent",
              cursor: "pointer",
              fontWeight: manualMode ? 600 : 400,
              transition: "background 200ms ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = manualMode ? "rgba(224,161,0,0.15)" : "var(--color-background-secondary)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = manualMode ? "rgba(224,161,0,0.08)" : "transparent"; }}
          >
            {manualMode ? "Manual mode" : "Override"}
            {pending.length > 0 && (
              <span style={{
                marginLeft: 6,
                background: "#E0A100",
                color: "#fff",
                borderRadius: 999,
                fontSize: 10,
                fontWeight: 700,
                padding: "1px 6px",
              }}>
                {pending.length}
              </span>
            )}
          </button>
        </div>
      </div>

      <div className="flex" style={{ borderBottom: HAIRLINE, background: "var(--color-background-primary)" }}>
        <TabButton active={tab === 1} onClick={() => setTab(1)}>Floor view</TabButton>
        <TabButton active={tab === 2} onClick={() => setTab(2)}>
          Active cases <CountBadge count={liveCount} />
        </TabButton>
      </div>

      <CoverageBanner patterns={patterns} />

      {tab === 1 ? (
        <div
          className="grid"
          style={{
            gridTemplateColumns: "1fr 340px",
            height: "calc(100vh - 92px)",
          }}
        >
          <FloorMap
            clinicians={clinicianPins}
            alerts={activeAlerts}
            selectedFloor={selectedFloor}
            onFloorSelect={setSelectedFloor}
            onClinicianClick={(id) => console.log("clinician clicked", id)}
            selectedAlert={selectedAlert}
            onAlertSelect={handleAlertSelect}
          />
          <div
            style={{
              borderLeft: HAIRLINE,
              display: "grid",
              gridTemplateRows: "1fr 1fr",
              minHeight: 0,
            }}
          >
            <div style={{ minHeight: 0, overflow: "hidden" }}>
              <AlertFeed
                alerts={alerts}
                patterns={patterns}
                onFloorSelect={handleFloorSelect}
                onAlertSelect={handleAlertSelect}
              />
            </div>
            <div style={{ minHeight: 0, overflow: "hidden", borderTop: HAIRLINE, display: "flex", flexDirection: "column" }}>
              {pending.length > 0 && (
                <div style={{ flexShrink: 0, padding: "10px 12px 0", overflowY: "auto", maxHeight: "40%" }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "#E0A100", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 6 }}>
                    Pending approval ({pending.length})
                  </div>
                  {pending.map((p) => (
                    <PendingApprovalRow
                      key={p.id}
                      page={p}
                      clinicians={clinicians}
                      onApproved={(updated) => {
                        setPending((prev) => prev.filter((x) => x.id !== updated.id));
                        upsertQueueLocal(updated);
                        upsertAlert(pageToAlert(updated));
                      }}
                      onRejected={(id) => setPending((prev) => prev.filter((x) => x.id !== id))}
                    />
                  ))}
                </div>
              )}
              <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
                <QueuePanel pages={queue} onUpdate={upsertQueueLocal} />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <CasesTable cases={alerts} onFloorSelect={handleFloorSelect} onAlertSelect={handleAlertSelect} />
      )}

      <ManualOverridePanel
        open={overrideOpen}
        onClose={() => setOverrideOpen(false)}
        clinicians={clinicians}
        onPageSent={(page) => {
          setOverrideOpen(false);
          upsertQueueLocal(page);
          upsertAlert(pageToAlert(page));
        }}
      />

      {recToShow ? (
        <ProactiveModal
          rec={recToShow}
          onAcked={(id) => {
            setRecs((prev) => prev.filter((r) => r.id !== id));
            setActiveRec((cur) => {
              if (!cur || cur.id !== id) return cur;
              const next = recs.find((r) => r.id !== id) ?? null;
              return next;
            });
            if (recs.length <= 1) setRecsOpen(false);
          }}
          onDismissNonBlocking={() => {
            setActiveRec(null);
            setRecsOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "10px 18px",
        fontSize: 13,
        color: active ? "var(--color-text-primary)" : "var(--color-text-secondary)",
        cursor: "pointer",
        borderBottom: active
          ? "2px solid var(--color-text-primary)"
          : "2px solid transparent",
        background: "transparent",
        fontWeight: active ? 500 : 400,
        transition: "color 200ms ease",
      }}
    >
      {children}
    </button>
  );
}
