"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { getClinicians } from "@/lib/api";
import { getBackendSocket } from "@/lib/backendSocket";
import { getQueue } from "@/lib/backendApi";
import type {
  ClinicianRecord,
  ClinicianStatus,
} from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const STATUS_COLOR: Record<string, string> = {
  available: "#1D9E75",
  paging: "#E0A100",
  in_procedure: "#7C5CFF",
  on_case: "#3478F6",
  off_shift: "#9CA3AF",
};

function statusLabel(s: string): string {
  return s.replace(/_/g, " ");
}

export function ClinicianDirectory() {
  const router = useRouter();
  const params = useSearchParams();
  const [rows, setRows] = useState<ClinicianRecord[]>([]);
  const [livePages, setLivePages] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState("");

  // Legacy /clinician?id=dr_chen → /clinician/dr_chen redirect.
  useEffect(() => {
    const legacy = params.get("id");
    if (legacy) {
      router.replace(`/clinician/${legacy}`);
    }
  }, [params, router]);

  useEffect(() => {
    getClinicians().then(setRows).catch(() => {});
    getQueue()
      .then((res) => {
        const map: Record<string, number> = {};
        for (const p of res.pages ?? []) {
          if (p.status === "paging" || p.status === "pending") {
            const id = p.doctor_id ?? "";
            if (!id) continue;
            map[id] = (map[id] ?? 0) + 1;
          }
        }
        setLivePages(map);
      })
      .catch(() => {});

    const socket = getBackendSocket({ role: "operator" });
    const onSnapshot = (snap: { doctors?: ClinicianRecord[] }) => {
      if (!Array.isArray(snap?.doctors)) return;
      // Merge: never let a partial snapshot blank out clinicians we already
      // fetched from /clinicians. Use snapshot rows for live status, but keep
      // any clinicians the snapshot omits.
      setRows((prev) => {
        const byId = new Map<string, ClinicianRecord>();
        for (const c of prev) byId.set(c.id, c);
        for (const c of snap.doctors!) {
          byId.set(c.id, { ...byId.get(c.id), ...c } as ClinicianRecord);
        }
        return Array.from(byId.values());
      });
    };
    const onChanged = (e: { id: string; status?: string; zone?: string }) => {
      setRows((prev) =>
        prev.map((c) =>
          c.id === e.id
            ? { ...c, status: (e.status as ClinicianStatus) ?? c.status, zone: e.zone ?? c.zone }
            : c,
        ),
      );
    };
    socket.on("snapshot", onSnapshot);
    socket.on("doctor_status_changed", onChanged);
    return () => {
      socket.off("snapshot", onSnapshot);
      socket.off("doctor_status_changed", onChanged);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q) ||
        (c.specialty ?? []).some((s) => s.toLowerCase().includes(q)) ||
        (c.zone ?? "").toLowerCase().includes(q),
    );
  }, [rows, filter]);

  return (
    <div
      className="min-h-screen"
      style={{
        background: "var(--color-background-primary)",
        color: "var(--color-text-primary)",
        fontSize: 13,
      }}
    >
      <header
        className="flex items-center justify-between"
        style={{
          padding: "12px 16px",
          borderBottom: HAIRLINE,
          background: "var(--color-background-primary)",
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 500 }}>
          Polaris — Clinicians
        </span>
        <div className="flex items-center gap-3">
          <Link
            href="/operator"
            style={{ fontSize: 12, color: "var(--color-text-secondary)" }}
          >
            Operator
          </Link>
          <Link
            href="/settings"
            style={{ fontSize: 12, color: "var(--color-text-secondary)" }}
          >
            Settings
          </Link>
        </div>
      </header>

      <div
        style={{
          padding: "12px 16px",
          borderBottom: HAIRLINE,
          background: "var(--color-background-primary)",
        }}
      >
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name, specialty, or zone…"
          style={{
            width: "100%",
            maxWidth: 420,
            padding: "8px 12px",
            border: HAIRLINE,
            borderRadius: 8,
            fontSize: 13,
            background: "var(--color-background-secondary)",
            color: "var(--color-text-primary)",
            outline: "none",
          }}
        />
      </div>

      <div style={{ maxWidth: 980, margin: "0 auto", padding: 16 }}>
        <div
          style={{
            border: HAIRLINE,
            borderRadius: 12,
            background: "var(--color-background-primary)",
            overflow: "hidden",
          }}
        >
          <div
            className="grid"
            style={{
              gridTemplateColumns: "1.4fr 1.2fr 1fr 0.8fr 0.6fr 0.6fr",
              padding: "10px 14px",
              fontSize: 11,
              color: "var(--color-text-secondary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              borderBottom: HAIRLINE,
              background: "var(--color-background-secondary)",
            }}
          >
            <div>Clinician</div>
            <div>Specialty</div>
            <div>Zone</div>
            <div>Status</div>
            <div style={{ textAlign: "right" }}>Live pages</div>
            <div style={{ textAlign: "right" }}>Pages 1h</div>
          </div>

          {filtered.length === 0 ? (
            <div
              style={{
                padding: "24px 14px",
                textAlign: "center",
                fontSize: 12,
                color: "var(--color-text-tertiary)",
              }}
            >
              No clinicians match.
            </div>
          ) : (
            filtered.map((c, i) => {
              const status = (c.status as ClinicianStatus) ?? "available";
              const live = livePages[c.id] ?? 0;
              return (
                <Link
                  key={c.id}
                  href={`/clinician/${c.id}`}
                  className="grid"
                  style={{
                    gridTemplateColumns: "1.4fr 1.2fr 1fr 0.8fr 0.6fr 0.6fr",
                    padding: "12px 14px",
                    borderBottom:
                      i === filtered.length - 1 ? "none" : HAIRLINE,
                    fontSize: 13,
                    color: "var(--color-text-primary)",
                    textDecoration: "none",
                    transition: "background 200ms ease",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background =
                      "var(--color-background-secondary)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  <div className="flex items-center gap-2" style={{ minWidth: 0 }}>
                    <span
                      aria-hidden
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: STATUS_COLOR[status] ?? "#9CA3AF",
                        flexShrink: 0,
                      }}
                    />
                    <div style={{ minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: 500,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {c.name}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: "var(--color-text-tertiary)",
                        }}
                      >
                        {c.id}
                        {c.on_call ? " · on call" : ""}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      color: "var(--color-text-secondary)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {(c.specialty ?? []).join(", ") || "—"}
                  </div>
                  <div style={{ color: "var(--color-text-secondary)" }}>
                    {c.zone || "—"}
                  </div>
                  <div style={{ color: "var(--color-text-secondary)" }}>
                    {statusLabel(status)}
                  </div>
                  <div
                    style={{
                      textAlign: "right",
                      color:
                        live > 0
                          ? "var(--color-text-primary)"
                          : "var(--color-text-tertiary)",
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: live > 0 ? 600 : 400,
                    }}
                  >
                    {live}
                  </div>
                  <div
                    style={{
                      textAlign: "right",
                      color: "var(--color-text-tertiary)",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {c.page_count_1hr ?? 0}
                  </div>
                </Link>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
