"use client";

import { useCallback, useEffect, useState } from "react";
import { getClinicians, postDispatch } from "@/lib/api";
import type { CaseResult, ClinicianRecord, DispatchResult, PriorityResult } from "@/lib/types";

function priorityStyles(p: string) {
  switch (p) {
    case "P1":
      return "bg-rose-500/15 border-rose-500/40 text-rose-200";
    case "P2":
      return "bg-amber-500/12 border-amber-500/35 text-amber-100";
    case "P3":
      return "bg-sky-500/10 border-sky-500/35 text-sky-100";
    case "P4":
      return "bg-slate-500/10 border-slate-500/30 text-slate-200";
    default:
      return "bg-slate-800/50 border-slate-600/40 text-slate-200";
  }
}

export function MedPageConsole() {
  const [raw, setRaw] = useState(
    "Patient in room 412 with sudden chest pain and diaphoresis, vitals unstable."
  );
  const [room, setRoom] = useState("room_412");
  const [hint, setHint] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<DispatchResult | null>(null);
  const [staff, setStaff] = useState<ClinicianRecord[]>([]);
  const [staffErr, setStaffErr] = useState<string | null>(null);

  const loadStaff = useCallback(() => {
    setStaffErr(null);
    getClinicians()
      .then(setStaff)
      .catch((e: Error) => setStaffErr(e.message));
  }, []);

  useEffect(() => {
    loadStaff();
  }, [loadStaff]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const data = await postDispatch({
        raw_text: raw.trim() || "help",
        room: room.trim() || undefined,
        specialty_hint: hint.trim() || undefined,
      });
      setResult(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  const pr: PriorityResult | null = result?.priority ?? null;
  const cr: CaseResult | null = result?.case ?? null;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <header className="mb-8 border-b border-zinc-800/80 pb-6">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50 sm:text-3xl">
            MedPage dispatch
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-400">
            Sends alerts through the same priority and case pipeline as the Python
            uAgents. Run the API with{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 text-zinc-300">
              uvicorn api.main:app --reload --port 8000
            </code>{" "}
            from the project root.
          </p>
        </header>

        <div className="grid gap-8 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <form
              onSubmit={onSubmit}
              className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5 shadow-sm"
            >
              <label className="block text-sm font-medium text-zinc-300">Clinical alert</label>
              <textarea
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                rows={5}
                className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-[border,box-shadow] duration-200 ease-out focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/30"
                placeholder="Describe the situation…"
              />
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-zinc-300">Room / zone hint</label>
                  <input
                    value={room}
                    onChange={(e) => setRoom(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-zinc-950/60 px-3 py-2 text-sm outline-none transition-[border,box-shadow] duration-200 ease-out focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/30"
                    placeholder="e.g. room_301, icu, or_1"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-zinc-300">
                    Specialty hint (optional)
                  </label>
                  <input
                    value={hint}
                    onChange={(e) => setHint(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-zinc-700 bg-zinc-950/60 px-3 py-2 text-sm outline-none transition-[border,box-shadow] duration-200 ease-out focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/30"
                    placeholder="e.g. cardiology"
                  />
                </div>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex h-10 items-center justify-center rounded-lg bg-sky-600 px-5 text-sm font-medium text-white transition-[background,transform,opacity] duration-200 ease-out hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? "Dispatching…" : "Run dispatch"}
                </button>
                {err ? (
                  <span className="text-sm text-rose-400" role="alert">
                    {err}
                  </span>
                ) : null}
              </div>
            </form>

            {pr ? (
              <section
                className={`mt-6 rounded-xl border p-4 transition-[opacity,transform] duration-200 ease-out ${
                  priorityStyles(pr.priority)
                }`}
                style={{ transitionTimingFunction: "cubic-bezier(0.215, 0.61, 0.355, 1)" }}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-300">
                    Triage
                  </h2>
                  <span className="rounded-md bg-black/20 px-2.5 py-0.5 font-mono text-lg font-semibold">
                    {pr.priority}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-zinc-200/90">{pr.reasoning}</p>
                {pr.guardrail_flags?.length ? (
                  <ul className="mt-3 flex flex-wrap gap-1.5 text-xs text-zinc-300/90">
                    {pr.guardrail_flags.map((f) => (
                      <li
                        key={f}
                        className="rounded-md border border-white/10 bg-black/15 px-2 py-0.5"
                      >
                        {f}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {pr.fallback_used ? (
                  <p className="mt-2 text-xs text-amber-200/80">Used keyword fallback (ASI-1 off)</p>
                ) : null}
              </section>
            ) : null}

            {cr ? (
              <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900/30 p-4">
                <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">
                  Ranked candidates
                </h2>
                <p className="mt-1 text-xs text-zinc-500">
                  {cr.total_available} available · query: {cr.specialty_query?.join(", ") || "—"}
                </p>
                <p className="mt-2 text-sm text-zinc-300/90">{cr.reasoning}</p>
                <ol className="mt-4 space-y-3">
                  {cr.candidates.map((c, i) => (
                    <li
                      key={c.id}
                      className="rounded-lg border border-zinc-800/80 bg-zinc-950/50 p-3"
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-medium text-zinc-100">
                          {i + 1}. {c.name}
                        </span>
                        <span className="font-mono text-xs text-zinc-500">
                          {(c.score * 100).toFixed(0)}% · ~{c.eta_minutes ?? "?"} min
                        </span>
                      </div>
                      <p className="mt-1.5 text-sm text-zinc-400">{c.reasoning}</p>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-zinc-500">
                        {c.zone ? <span>zone: {c.zone}</span> : null}
                        {c.on_call ? <span>on call</span> : null}
                        {c.specialty?.length ? (
                          <span>{c.specialty.join(" · ")}</span>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
                {cr.fallback_used ? (
                  <p className="mt-3 text-xs text-amber-200/80">Heuristic ranking (ASI-1 off)</p>
                ) : null}
              </section>
            ) : null}
          </div>

          <aside className="lg:col-span-2">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-medium text-zinc-300">Clinicians (TinyDB)</h2>
                <button
                  type="button"
                  onClick={loadStaff}
                  className="text-xs text-sky-400/90 transition-colors duration-200 ease-out hover:text-sky-300"
                >
                  Refresh
                </button>
              </div>
              {staffErr ? (
                <p className="mt-2 text-sm text-rose-400">{staffErr}</p>
              ) : (
                <ul className="mt-3 max-h-[min(60vh,520px)] space-y-2 overflow-y-auto pr-1 text-sm">
                  {staff.map((c) => (
                    <li
                      key={c.id}
                      className="rounded-lg border border-zinc-800/60 bg-zinc-950/40 px-3 py-2"
                    >
                      <div className="font-medium text-zinc-200">{c.name}</div>
                      <div className="mt-0.5 text-xs text-zinc-500">
                        {c.status} · {c.zone}
                        {c.on_call ? " · on call" : ""} · pgs {c.page_count_1hr}/hr
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
