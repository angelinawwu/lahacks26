"use client";

import { useEffect, useState } from "react";
import { PatternBadge, severityColor } from "./PatternBadge";
import type { ProactiveRecommendation } from "@/lib/backendTypes";
import { ackProactive } from "@/lib/backendApi";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

export function ProactiveModal({
  rec,
  operatorId,
  onAcked,
  onDismissNonBlocking,
}: {
  rec: ProactiveRecommendation;
  operatorId?: string;
  onAcked: (id: string, outcome: "approve" | "reject") => void;
  onDismissNonBlocking?: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!rec.requires_ack && onDismissNonBlocking) {
      const id = window.setTimeout(onDismissNonBlocking, 8000);
      return () => window.clearTimeout(id);
    }
  }, [rec.requires_ack, onDismissNonBlocking]);

  async function ack(outcome: "approve" | "reject") {
    if (busy) return;
    setBusy(outcome);
    setErr(null);
    try {
      await ackProactive(rec.id, { outcome, operator_id: operatorId });
      onAcked(rec.id, outcome);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ack failed");
      // optimistic local dismissal so the UI doesn't deadlock if backend stub is missing
      onAcked(rec.id, outcome);
    } finally {
      setBusy(null);
    }
  }

  function onBackdrop() {
    if (rec.requires_ack) return;
    onDismissNonBlocking?.();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="rec-title"
      onClick={onBackdrop}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.35)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "12vh 16px 16px",
        zIndex: 50,
      }}
    >
      <div
        className="polaris-card-in"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 480,
          background: "var(--color-background-primary)",
          border: HAIRLINE,
          borderRadius: 14,
          padding: 18,
          boxShadow: "0 20px 60px -20px rgba(0,0,0,0.35)",
          transformOrigin: "top right",
        }}
      >
        <div className="flex items-start justify-between" style={{ gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              Sentinel · Proactive recommendation
            </div>
            <div className="flex items-center" style={{ gap: 8, marginTop: 6 }}>
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: severityColor(rec.severity),
                  display: "inline-block",
                }}
              />
              <PatternBadge pattern={rec.pattern_type} zone={rec.zone} />
              {rec.requires_ack ? (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 500,
                    color: "#7A1F1D",
                    background: "#FBE3E2",
                    padding: "1px 7px",
                    borderRadius: 20,
                  }}
                >
                  Requires ACK
                </span>
              ) : null}
            </div>
            <div
              id="rec-title"
              style={{
                fontSize: 17,
                fontWeight: 600,
                color: "var(--color-text-primary)",
                marginTop: 8,
                lineHeight: 1.3,
              }}
            >
              {rec.recommendation}
            </div>
          </div>
        </div>

        <p
          style={{
            fontSize: 12,
            color: "var(--color-text-secondary)",
            background: "var(--color-background-secondary)",
            border: HAIRLINE,
            borderRadius: 8,
            padding: "10px 12px",
            margin: "12px 0 0",
            lineHeight: 1.45,
          }}
        >
          <span style={{ color: "var(--color-text-info)", fontWeight: 500, marginRight: 4 }}>Why:</span>
          {rec.rationale}
        </p>

        {rec.suggested_actions && rec.suggested_actions.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <div
              style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 6,
              }}
            >
              Suggested actions
            </div>
            <ul
              style={{
                fontSize: 12,
                color: "var(--color-text-primary)",
                listStyle: "disc",
                paddingLeft: 18,
                margin: 0,
                lineHeight: 1.5,
              }}
            >
              {rec.suggested_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {err ? (
          <p style={{ fontSize: 11, color: "var(--color-text-danger)", marginTop: 10 }}>{err}</p>
        ) : null}

        <div className="grid gap-2" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 14 }}>
          <button
            type="button"
            onClick={() => ack("reject")}
            disabled={busy !== null}
            style={{
              height: 40,
              borderRadius: 10,
              border: "0.5px solid var(--color-border-secondary)",
              color: "var(--color-text-primary)",
              background: "transparent",
              fontSize: 13,
              fontWeight: 500,
              cursor: busy ? "not-allowed" : "pointer",
              transition: "background 200ms ease",
            }}
            onMouseEnter={(e) => {
              if (!busy) e.currentTarget.style.background = "var(--color-background-secondary)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
          >
            {busy === "reject" ? "Dismissing…" : "Dismiss"}
          </button>
          <button
            type="button"
            onClick={() => ack("approve")}
            disabled={busy !== null}
            style={{
              height: 40,
              borderRadius: 10,
              border: "0.5px solid #1D9E75",
              background: "#1D9E75",
              color: "#FFFFFF",
              fontSize: 13,
              fontWeight: 600,
              cursor: busy ? "not-allowed" : "pointer",
              transition: "background 200ms ease",
            }}
            onMouseEnter={(e) => {
              if (!busy) e.currentTarget.style.background = "#178A65";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#1D9E75";
            }}
          >
            {busy === "approve" ? "Approving…" : "Approve action"}
          </button>
        </div>
      </div>
    </div>
  );
}
