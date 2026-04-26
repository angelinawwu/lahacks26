"use client";

import { useEffect, useState } from "react";
import type { SbarBrief, SbarSections } from "@/lib/backendTypes";

const HAIRLINE = "0.5px solid var(--color-border-tertiary)";

const LABELS: Array<{ key: keyof SbarSections; label: string; letter: string }> = [
  { key: "situation", label: "Situation", letter: "S" },
  { key: "background", label: "Background", letter: "B" },
  { key: "assessment", label: "Assessment", letter: "A" },
  { key: "request", label: "Request", letter: "R" },
];

const HEADERS = /^(situation|background|assessment|request)\s*[:\-]?\s*/i;

function parseSbar(text: string): SbarSections {
  if (!text) return {};
  const out: SbarSections = {};
  // Split on common SBAR separators; tolerate lowercase/uppercase
  const lines = text.split(/\r?\n+|(?<=[.!?])\s+(?=(?:Situation|Background|Assessment|Request)\b)/i);
  let current: keyof SbarSections | null = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^(Situation|Background|Assessment|Request)\b\s*[:\-]?\s*(.*)$/i);
    if (m) {
      current = m[1].toLowerCase() as keyof SbarSections;
      out[current] = (out[current] ?? "") + (out[current] ? " " : "") + m[2];
    } else if (current) {
      out[current] = (out[current] ?? "") + " " + line;
    }
  }
  return out;
}

function wordCountColor(count: number): { bg: string; fg: string } {
  if (count >= 100) return { bg: "#FBE3E2", fg: "#7A1F1D" };
  if (count >= 80) return { bg: "#FAEEDA", fg: "#633806" };
  return { bg: "#EAF3DE", fg: "#27500A" };
}

export function SbarCard({
  brief,
  onMarkRead,
  onResolve,
}: {
  brief: SbarBrief;
  onMarkRead?: () => void;
  onResolve?: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const sections: SbarSections = brief.sections ?? parseSbar(brief.brief_text);
  const hasParsed = Boolean(
    sections.situation || sections.background || sections.assessment || sections.request,
  );
  const wc = brief.word_count ?? brief.brief_text.trim().split(/\s+/).filter(Boolean).length;
  const tone = wordCountColor(wc);

  useEffect(() => {
    const id = window.setTimeout(() => setCollapsed(true), 30_000);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <section
      className="polaris-card-in"
      style={{
        background: "var(--color-background-primary)",
        border: HAIRLINE,
        borderRadius: 12,
        padding: 14,
        boxShadow: "0 1px 0 rgba(0,0,0,0.02)",
      }}
    >
      <div className="flex items-start justify-between" style={{ gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 11,
              color: "var(--color-text-tertiary)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            SBAR brief
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--color-text-primary)",
              marginTop: 3,
            }}
          >
            Patient handoff
          </div>
        </div>
        <span
          style={{
            fontSize: 10,
            fontWeight: 500,
            background: tone.bg,
            color: tone.fg,
            padding: "2px 7px",
            borderRadius: 20,
            whiteSpace: "nowrap",
          }}
          title={wc >= 100 ? "Brief exceeds 100-word target" : undefined}
        >
          {wc} words
        </span>
      </div>

      {!collapsed ? (
        hasParsed ? (
          <div className="flex flex-col" style={{ gap: 8, marginTop: 12 }}>
            {LABELS.map(({ key, label, letter }) => {
              const value = sections[key];
              if (!value) return null;
              return (
                <div
                  key={key}
                  style={{
                    border: HAIRLINE,
                    borderRadius: 8,
                    padding: "8px 10px",
                    background: "var(--color-background-tertiary)",
                  }}
                >
                  <div
                    className="flex items-center"
                    style={{
                      gap: 6,
                      fontSize: 10,
                      color: "var(--color-text-tertiary)",
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      marginBottom: 4,
                    }}
                  >
                    <span
                      style={{
                        width: 16,
                        height: 16,
                        borderRadius: 4,
                        background: "var(--color-background-info)",
                        color: "var(--color-text-info)",
                        fontSize: 10,
                        fontWeight: 600,
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      {letter}
                    </span>
                    {label}
                  </div>
                  <div style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.45 }}>
                    {value.trim().replace(HEADERS, "")}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p
            style={{
              fontSize: 13,
              color: "var(--color-text-primary)",
              marginTop: 12,
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
            }}
          >
            {brief.brief_text}
          </p>
        )
      ) : (
        <p
          style={{
            fontSize: 12,
            color: "var(--color-text-tertiary)",
            marginTop: 10,
            fontStyle: "italic",
          }}
        >
          Collapsed · tap Show to re-open.
        </p>
      )}

      <div className="flex items-center justify-end" style={{ gap: 6, marginTop: 10 }}>
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          style={{
            fontSize: 11,
            color: "var(--color-text-secondary)",
            padding: "3px 10px",
            border: "0.5px solid var(--color-border-secondary)",
            borderRadius: 20,
            background: "transparent",
            cursor: "pointer",
            transition: "background 200ms ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--color-background-secondary)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
          }}
        >
          {collapsed ? "Show" : "Collapse"}
        </button>
        {onMarkRead ? (
          <button
            type="button"
            onClick={onMarkRead}
            style={{
              fontSize: 11,
              color: "#FFFFFF",
              padding: "3px 10px",
              border: "0.5px solid #1D9E75",
              background: "#1D9E75",
              borderRadius: 20,
              cursor: "pointer",
              fontWeight: 500,
              transition: "background 200ms ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#178A65";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#1D9E75";
            }}
          >
            Mark as read
          </button>
        ) : null}
        {onResolve ? (
          <a
            role="button"
            tabIndex={0}
            onClick={onResolve}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onResolve();
              }
            }}
            style={{
              fontSize: 11,
              color: "var(--color-text-info)",
              padding: "3px 10px",
              borderRadius: 20,
              cursor: "pointer",
              fontWeight: 500,
              textDecoration: "underline",
              textUnderlineOffset: 2,
            }}
          >
            Resolve page
          </a>
        ) : null}
      </div>
    </section>
  );
}
