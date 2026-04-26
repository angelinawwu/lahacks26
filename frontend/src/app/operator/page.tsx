"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertFeed, isAlertLive } from "@/components/AlertFeed";
import { FloorMap } from "@/components/FloorMap";
import { CasesTable } from "@/components/CasesTable";
import { CountBadge } from "@/components/badges";
import { getSocket } from "@/lib/socket";
import { getClinicians } from "@/lib/api";
import { inferFloorWing } from "@/lib/floorData";
import type { FloorId } from "@/lib/floorData";
import type {
  ActiveAlert,
  AlertEvent,
  ClinicianPin,
  ClinicianRecord,
  ClinicianStatus,
  ClinicianStatusChanged,
  OperatorSnapshot,
  PriorityLevel,
} from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export default function OperatorPage() {
  const [tab, setTab] = useState<1 | 2>(1);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [clinicians, setClinicians] = useState<ClinicianRecord[]>([]);
  const [selectedFloor, setSelectedFloor] = useState<FloorId | null>(null);
  const [selectedAlert, setSelectedAlert] = useState<ActiveAlert | null>(null);

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

  const handleFloorSelect = (floor: FloorId) => {
    setSelectedFloor(floor);
    setTab(1); // Switch to floor view tab
  };

  const handleAlertSelect = (alert: ActiveAlert | null) => {
    setSelectedAlert(alert);
    if (alert) {
      setSelectedFloor(alert.floor);
      setTab(1); // Switch to floor view tab when alert is selected
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
          <FloorMap
            clinicians={clinicianPins}
            alerts={activeAlerts}
            selectedFloor={selectedFloor}
            onFloorSelect={setSelectedFloor}
            onClinicianClick={(id) => console.log("clinician clicked", id)}
            selectedAlert={selectedAlert}
            onAlertSelect={handleAlertSelect}
          />
          <div style={{ borderLeft: HAIRLINE }}>
            <AlertFeed alerts={alerts} onFloorSelect={handleFloorSelect} onAlertSelect={handleAlertSelect} />
          </div>
        </div>
      ) : (
        <CasesTable cases={alerts} onFloorSelect={handleFloorSelect} onAlertSelect={handleAlertSelect} />
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
