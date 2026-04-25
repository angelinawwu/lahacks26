"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertFeed, isAlertLive } from "@/components/AlertFeed";
import { FloorMap } from "@/components/FloorMap";
import { CasesTable } from "@/components/CasesTable";
import { CountBadge } from "@/components/badges";
import { getSocket } from "@/lib/socket";
import { getClinicians } from "@/lib/api";
import type {
  AlertEvent,
  ClinicianRecord,
  ClinicianStatusChanged,
  OperatorSnapshot,
} from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export default function OperatorPage() {
  const [tab, setTab] = useState<1 | 2>(1);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [clinicians, setClinicians] = useState<ClinicianRecord[]>([]);

  useEffect(() => {
    getClinicians().then(setClinicians).catch(() => {});

    const socket = getSocket({ role: "operator" });

    const onSnapshot = (snap: OperatorSnapshot) => {
      if (Array.isArray(snap?.active_cases)) setAlerts(snap.active_cases.reverse());
      if (Array.isArray(snap?.clinicians)) setClinicians(snap.clinicians);
    };
    const onAlertCreated = (a: AlertEvent) => {
      setAlerts((prev) => [a, ...prev.filter((x) => x.alert_id !== a.alert_id)]);
      if (a.assigned_clinician_id) {
        setClinicians((prev) =>
          prev.map((c) =>
            c.id === a.assigned_clinician_id ? { ...c, status: "paging" } : c,
          ),
        );
      }
    };
    const onAlertUpdated = (a: AlertEvent) => {
      setAlerts((prev) => prev.map((x) => (x.alert_id === a.alert_id ? { ...x, ...a } : x)));
      if (a.assigned_clinician_id && (a.status === "accepted" || a.status === "en_route")) {
        setClinicians((prev) =>
          prev.map((c) =>
            c.id === a.assigned_clinician_id ? { ...c, status: "on_case" } : c,
          ),
        );
      }
    };
    const onClinicianChanged = (e: ClinicianStatusChanged) => {
      setClinicians((prev) =>
        prev.map((c) => (c.id === e.clinician_id ? { ...c, status: e.status, zone: e.zone ?? c.zone } : c)),
      );
    };

    socket.on("snapshot", onSnapshot);
    socket.on("alert_created", onAlertCreated);
    socket.on("alert_updated", onAlertUpdated);
    socket.on("clinician_status_changed", onClinicianChanged);

    return () => {
      socket.off("snapshot", onSnapshot);
      socket.off("alert_created", onAlertCreated);
      socket.off("alert_updated", onAlertUpdated);
      socket.off("clinician_status_changed", onClinicianChanged);
    };
  }, []);

  const liveCount = useMemo(() => alerts.filter(isAlertLive).length, [alerts]);
  const activeP1Room = useMemo(() => {
    const live = alerts.find((a) => a.priority === "P1" && isAlertLive(a));
    return live?.room ?? null;
  }, [alerts]);

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
        <span style={{ fontSize: 15, fontWeight: 500 }}>MedPage — Operator</span>
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
            Memorial Hospital · Floor 3
          </span>
          <button
            type="button"
            style={{
              fontSize: 12,
              padding: "4px 10px",
              border: HAIRLINE,
              borderRadius: 20,
              color: "var(--color-text-secondary)",
              background: "transparent",
              cursor: "pointer",
              transition: "background 200ms ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-background-secondary)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            Override
          </button>
        </div>
      </div>

      <div className="flex" style={{ borderBottom: HAIRLINE, background: "var(--color-background-primary)" }}>
        <TabButton active={tab === 1} onClick={() => setTab(1)}>Floor view</TabButton>
        <TabButton active={tab === 2} onClick={() => setTab(2)}>
          Active cases <CountBadge count={liveCount} />
        </TabButton>
      </div>

      {tab === 1 ? (
        <div
          className="grid"
          style={{
            gridTemplateColumns: "1fr 320px",
            height: "calc(100vh - 92px)",
          }}
        >
          <FloorMap clinicians={clinicians} activeAlertRoom={activeP1Room} />
          <div style={{ borderLeft: HAIRLINE }}>
            <AlertFeed alerts={alerts} />
          </div>
        </div>
      ) : (
        <CasesTable cases={alerts} />
      )}
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
