"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getSettings,
  updateSettings,
  setGlobalPagingMode,
} from "@/lib/backendApi";
import { getBackendSocket } from "@/lib/backendSocket";
import { getClinicians, patchClinician } from "@/lib/api";
import type { AppSettings } from "@/lib/backendTypes";
import type { ClinicianRecord } from "@/lib/types";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

interface ScheduleDraft {
  on_call: boolean;
  shift_start: string;
  shift_end: string;
  saving?: boolean;
  dirty?: boolean;
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        border: HAIRLINE,
        borderRadius: 12,
        background: "var(--color-background-primary)",
        padding: 18,
        marginBottom: 16,
      }}
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{title}</div>
        {description ? (
          <div
            style={{
              fontSize: 12,
              color: "var(--color-text-tertiary)",
              marginTop: 4,
            }}
          >
            {description}
          </div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function Row({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center justify-between"
      style={{
        padding: "10px 0",
        borderTop: HAIRLINE,
        gap: 16,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13 }}>{label}</div>
        {hint ? (
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              marginTop: 2,
            }}
          >
            {hint}
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: 38,
        height: 22,
        borderRadius: 999,
        border: HAIRLINE,
        background: checked
          ? "var(--color-text-primary)"
          : "var(--color-background-secondary)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "background 200ms ease",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: checked
            ? "var(--color-background-primary)"
            : "var(--color-text-secondary)",
          transition: "left 200ms cubic-bezier(.215,.61,.355,1)",
        }}
      />
    </button>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div
      style={{
        display: "inline-flex",
        border: HAIRLINE,
        borderRadius: 8,
        overflow: "hidden",
        background: "var(--color-background-secondary)",
      }}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            style={{
              padding: "6px 12px",
              fontSize: 12,
              border: "none",
              background: active
                ? "var(--color-background-primary)"
                : "transparent",
              color: active
                ? "var(--color-text-primary)"
                : "var(--color-text-secondary)",
              fontWeight: active ? 500 : 400,
              cursor: "pointer",
              transition: "background 200ms ease",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function SettingsView() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [clinicians, setClinicians] = useState<ClinicianRecord[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ScheduleDraft>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    getSettings().then(setSettings).catch((e) => setError(String(e.message ?? e)));
    getClinicians()
      .then((rows) => {
        setClinicians(rows);
        setDrafts(
          Object.fromEntries(
            rows.map((c) => [
              c.id,
              {
                on_call: Boolean(c.on_call),
                shift_start:
                  (c as ClinicianRecord & { shift_start?: string })
                    .shift_start ?? "",
                shift_end:
                  (c as ClinicianRecord & { shift_end?: string })
                    .shift_end ?? "",
              },
            ]),
          ),
        );
      })
      .catch(() => {});

    const socket = getBackendSocket({ role: "operator" });
    const onSettings = (s: AppSettings) => setSettings(s);
    const onModes = (m: { global_mode: "automated" | "manual" }) =>
      setSettings((cur) => (cur ? { ...cur, global_mode: m.global_mode } : cur));
    socket.on("settings_updated", onSettings);
    socket.on("paging_modes_updated", onModes);
    return () => {
      socket.off("settings_updated", onSettings);
      socket.off("paging_modes_updated", onModes);
    };
  }, []);

  function flashSaved() {
    setSavedAt(Date.now());
    window.setTimeout(() => setSavedAt(null), 1500);
  }

  async function patch(partial: Partial<AppSettings>, key: string) {
    setSavingKey(key);
    setError(null);
    try {
      const next = await updateSettings(partial);
      setSettings(next);
      flashSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingKey(null);
    }
  }

  async function setManualMode(manual: boolean) {
    setSavingKey("manual_mode");
    setError(null);
    try {
      await setGlobalPagingMode(manual ? "manual" : "automated");
      setSettings((cur) =>
        cur ? { ...cur, global_mode: manual ? "manual" : "automated" } : cur,
      );
      flashSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingKey(null);
    }
  }

  function updateDraft(id: string, patch: Partial<ScheduleDraft>) {
    setDrafts((prev) => ({
      ...prev,
      [id]: { ...prev[id], ...patch, dirty: true },
    }));
  }

  async function saveSchedule(id: string) {
    const d = drafts[id];
    if (!d) return;
    setDrafts((prev) => ({ ...prev, [id]: { ...d, saving: true } }));
    try {
      await patchClinician(id, {
        on_call: d.on_call,
        shift_start: d.shift_start || null,
        shift_end: d.shift_end || null,
      });
      setDrafts((prev) => ({
        ...prev,
        [id]: { ...d, saving: false, dirty: false },
      }));
      setClinicians((prev) =>
        prev.map((c) =>
          c.id === id
            ? ({
                ...c,
                on_call: d.on_call,
                shift_start: d.shift_start,
                shift_end: d.shift_end,
              } as ClinicianRecord)
            : c,
        ),
      );
      flashSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setDrafts((prev) => ({ ...prev, [id]: { ...d, saving: false } }));
    }
  }

  const manualMode = settings?.global_mode === "manual";

  const sortedClinicians = useMemo(
    () => [...clinicians].sort((a, b) => a.name.localeCompare(b.name)),
    [clinicians],
  );

  return (
    <div
      className="min-h-screen"
      style={{
        background: "var(--color-background-tertiary)",
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
        <span style={{ fontSize: 15, fontWeight: 500 }}>Polaris — Settings</span>
        <div className="flex items-center gap-3">
          <Link
            href="/operator"
            style={{ fontSize: 12, color: "var(--color-text-secondary)" }}
          >
            Operator
          </Link>
          <Link
            href="/clinician"
            style={{ fontSize: 12, color: "var(--color-text-secondary)" }}
          >
            Clinicians
          </Link>
          <span
            aria-live="polite"
            style={{
              fontSize: 11,
              color: "var(--color-text-info, #1D9E75)",
              opacity: savedAt ? 1 : 0,
              transition: "opacity 200ms ease",
            }}
          >
            Saved
          </span>
        </div>
      </header>

      <main style={{ maxWidth: 760, margin: "0 auto", padding: 20 }}>
        {error ? (
          <div
            style={{
              border: "0.5px solid var(--color-border-danger, #E0A0A0)",
              background: "var(--color-background-danger, #FFF1F1)",
              color: "var(--color-text-danger, #B00020)",
              padding: "8px 12px",
              borderRadius: 8,
              marginBottom: 16,
              fontSize: 12,
            }}
          >
            {error}
          </div>
        ) : null}

        <Section
          title="Manual mode"
          description="When manual mode is on, the operator must confirm every page before it goes out."
        >
          <Row
            label="Global manual mode"
            hint={
              settings?.global_mode === "manual"
                ? "All zones currently require operator confirmation."
                : "Pages dispatch automatically using policy."
            }
          >
            <Toggle
              checked={manualMode}
              disabled={!settings || savingKey === "manual_mode"}
              onChange={setManualMode}
            />
          </Row>
        </Section>

        <Section
          title="Page rate limit"
          description="Maximum pages a single clinician can receive per rolling hour before auto-dispatch skips them."
        >
          <Row
            label="Max pages per hour"
            hint="Applies to auto-dispatch only — manual operator pings always go through."
          >
            <input
              type="number"
              min={1}
              max={20}
              value={settings?.max_pages_per_hour ?? 3}
              disabled={!settings || savingKey === "max_pages_per_hour"}
              onChange={(e) => {
                const v = Number(e.target.value);
                setSettings((cur) =>
                  cur ? { ...cur, max_pages_per_hour: v } : cur,
                );
              }}
              onBlur={(e) =>
                patch(
                  { max_pages_per_hour: Number(e.target.value) },
                  "max_pages_per_hour",
                )
              }
              style={{
                width: 64,
                padding: "6px 10px",
                fontSize: 13,
                border: HAIRLINE,
                borderRadius: 8,
                background: "var(--color-background-secondary)",
                color: "var(--color-text-primary)",
                textAlign: "right",
                fontVariantNumeric: "tabular-nums",
              }}
            />
          </Row>
          <Row
            label="Require on-call"
            hint="Skip clinicians not flagged on-call when picking candidates."
          >
            <Toggle
              checked={Boolean(settings?.require_on_call)}
              disabled={!settings || savingKey === "require_on_call"}
              onChange={(v) =>
                patch({ require_on_call: v }, "require_on_call")
              }
            />
          </Row>
          <Row
            label="Allow off-shift"
            hint="Permit pages to clinicians outside their shift window."
          >
            <Toggle
              checked={Boolean(settings?.allow_off_shift)}
              disabled={!settings || savingKey === "allow_off_shift"}
              onChange={(v) =>
                patch({ allow_off_shift: v }, "allow_off_shift")
              }
            />
          </Row>
        </Section>

        <Section
          title="Operator default view"
          description="Which view the operator dashboard opens to on load."
        >
          <Row label="Default view">
            <Segmented<"map" | "feed">
              value={settings?.default_operator_view ?? "map"}
              options={[
                { value: "map", label: "Floor map" },
                { value: "feed", label: "Active cases" },
              ]}
              onChange={(v) =>
                patch({ default_operator_view: v }, "default_operator_view")
              }
            />
          </Row>
        </Section>

        <Section
          title="Schedule"
          description="On-call status and shift windows per clinician. Times are stored as ISO strings (HH:MM works)."
        >
          {sortedClinicians.length === 0 ? (
            <div
              style={{
                fontSize: 12,
                color: "var(--color-text-tertiary)",
                padding: "12px 0",
              }}
            >
              Loading clinicians…
            </div>
          ) : (
            <div
              className="grid"
              style={{
                gridTemplateColumns: "1.4fr 0.6fr 0.8fr 0.8fr 0.7fr",
                fontSize: 11,
                color: "var(--color-text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                padding: "8px 0",
                borderTop: HAIRLINE,
              }}
            >
              <div>Clinician</div>
              <div>On call</div>
              <div>Shift start</div>
              <div>Shift end</div>
              <div></div>
            </div>
          )}
          {sortedClinicians.map((c) => {
            const d = drafts[c.id] ?? {
              on_call: Boolean(c.on_call),
              shift_start: "",
              shift_end: "",
            };
            return (
              <div
                key={c.id}
                className="grid items-center"
                style={{
                  gridTemplateColumns: "1.4fr 0.6fr 0.8fr 0.8fr 0.7fr",
                  padding: "10px 0",
                  borderTop: HAIRLINE,
                  gap: 8,
                }}
              >
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
                    {(c.specialty ?? []).join(", ")}
                  </div>
                </div>
                <div>
                  <Toggle
                    checked={d.on_call}
                    onChange={(v) => updateDraft(c.id, { on_call: v })}
                  />
                </div>
                <input
                  type="time"
                  value={d.shift_start}
                  onChange={(e) =>
                    updateDraft(c.id, { shift_start: e.target.value })
                  }
                  style={{
                    padding: "6px 8px",
                    fontSize: 12,
                    border: HAIRLINE,
                    borderRadius: 8,
                    background: "var(--color-background-secondary)",
                    color: "var(--color-text-primary)",
                  }}
                />
                <input
                  type="time"
                  value={d.shift_end}
                  onChange={(e) =>
                    updateDraft(c.id, { shift_end: e.target.value })
                  }
                  style={{
                    padding: "6px 8px",
                    fontSize: 12,
                    border: HAIRLINE,
                    borderRadius: 8,
                    background: "var(--color-background-secondary)",
                    color: "var(--color-text-primary)",
                  }}
                />
                <div style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    disabled={!d.dirty || d.saving}
                    onClick={() => saveSchedule(c.id)}
                    style={{
                      fontSize: 12,
                      padding: "5px 10px",
                      borderRadius: 8,
                      border: HAIRLINE,
                      background:
                        d.dirty && !d.saving
                          ? "var(--color-text-primary)"
                          : "var(--color-background-secondary)",
                      color:
                        d.dirty && !d.saving
                          ? "var(--color-background-primary)"
                          : "var(--color-text-tertiary)",
                      cursor: d.dirty && !d.saving ? "pointer" : "default",
                      transition: "background 200ms ease, color 200ms ease",
                    }}
                  >
                    {d.saving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            );
          })}
        </Section>
      </main>
    </div>
  );
}
