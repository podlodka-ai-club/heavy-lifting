import { useEffect, useState } from "react";

import type { StatsSnapshot, UsageBucket } from "../../api";
import { getStatsSnapshot } from "../../api";
import "./stats.css";

const TASK_TYPES = ["fetch", "execute", "pr_feedback", "deliver"];
const STATUS_ORDER = ["new", "processing", "done", "failed"] as const;

/* ── Helpers ── */

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(s: string): string {
  const n = parseFloat(s);
  return isNaN(n) ? s : `$${n.toFixed(4)}`;
}

/* ── Bar row ── */

function BarRow({ label, value, max, suffix = "" }: { label: string; value: number; max: number; suffix?: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="st-bar-row">
      <span className="st-bar-label" title={label}>{label}</span>
      <div className="st-bar-track">
        <div className="st-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="st-bar-val">{fmt(value)}{suffix}</span>
    </div>
  );
}

/* ── Usage bar table ── */

function UsageBreakdown({ data, metric }: { data: Record<string, UsageBucket>; metric: "total_tokens" | "cost_usd" }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="muted" style={{ fontSize: "0.8rem" }}>Нет данных</p>;

  const values = entries.map(([, b]) =>
    metric === "cost_usd" ? parseFloat(b.cost_usd) : b.tokens.total
  );
  const max = Math.max(...values, 1);

  return (
    <div className="st-bar-table">
      {entries.map(([key, bucket], i) => (
        <BarRow
          key={key}
          label={key}
          max={max}
          value={values[i] ?? 0}
          suffix={metric === "cost_usd" ? "" : ""}
        />
      ))}
    </div>
  );
}

/* ── Page ── */

export function StatsPage() {
  const [snap, setSnap] = useState<StatsSnapshot | null>(null);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [error, setError] = useState("");
  const [tokenMetric, setTokenMetric] = useState<"total_tokens" | "cost_usd">("total_tokens");

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    getStatsSnapshot()
      .then(data => { if (!cancelled) { setSnap(data); setLoadState("loaded"); } })
      .catch(e => { if (!cancelled) { setLoadState("error"); setError(e instanceof Error ? e.message : "Ошибка"); } });
    return () => { cancelled = true; };
  }, []);

  const t = snap?.tasks;
  const u = snap?.token_usage;

  return (
    <main className="page st-page">
      <div className="st-hud">
        <div>
          <p className="st-hud-title">heavy-lifting · stats</p>
          <h1 className="st-hud-hero">{t ? fmt(t.total) : "—"}</h1>
          <p className="st-hud-sub">задач в системе</p>
        </div>
        {u && (
          <div className="st-kpi-row">
            <div className="st-kpi">
              <span className="st-kpi-label">Токенов</span>
              <strong className="st-kpi-val">{fmt(u.tokens.total)}</strong>
            </div>
            <div className="st-kpi">
              <span className="st-kpi-label">Стоимость</span>
              <strong className="st-kpi-val">{fmtCost(u.cost_usd.total)}</strong>
            </div>
            <div className="st-kpi">
              <span className="st-kpi-label">Кэш</span>
              <strong className="st-kpi-val">{fmt(u.tokens.cached)}</strong>
            </div>
          </div>
        )}
      </div>

      {loadState === "loading" && <p className="muted">Загрузка...</p>}
      {error && <p className="status-error" role="alert">{error}</p>}

      {snap && (
        <div className="st-grid">

          {/* Task status */}
          <div className="st-card">
            <p className="st-card-title">Статусы задач</p>
            <div className="st-status-grid">
              {STATUS_ORDER.map(status => (
                <div className="st-status-chip" key={status}>
                  <span className={`st-status-dot ${status}`} />
                  <span className="st-status-name">{status}</span>
                  <span className="st-status-count">{t?.by_status[status] ?? 0}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Tasks by type */}
          <div className="st-card">
            <p className="st-card-title">Задач по типу</p>
            <div className="st-bar-table">
              {TASK_TYPES.map(type => (
                <BarRow
                  key={type}
                  label={type}
                  max={t?.total ?? 1}
                  value={t?.by_type[type] ?? 0}
                />
              ))}
            </div>
          </div>

          {/* Type × status matrix */}
          <div className="st-card">
            <p className="st-card-title">Done / Failed по типу</p>
            <div className="st-bar-table">
              {TASK_TYPES.map(type => {
                const done = t?.by_type_and_status[type]?.done ?? 0;
                const failed = t?.by_type_and_status[type]?.failed ?? 0;
                const total = t?.by_type[type] ?? 1;
                return (
                  <div className="st-bar-row" key={type} style={{ gridTemplateColumns: "110px 1fr 1fr" }}>
                    <span className="st-bar-label">{type}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: "var(--green)" }}>
                      ✓ {done}
                    </span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: "0.7rem", color: failed > 0 ? "var(--red)" : "var(--muted)" }}>
                      ✗ {failed}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Token totals */}
          {u && (
            <div className="st-card">
              <p className="st-card-title">Токены (всего)</p>
              <div className="st-bar-table">
                {(["input", "output", "cached"] as const).map(k => (
                  <BarRow key={k} label={k} max={u.tokens.total} value={u.tokens[k]} />
                ))}
              </div>
            </div>
          )}

          {/* By model / provider */}
          {u && Object.keys(u.by_model).length > 0 && (
            <div className="st-card" style={{ gridColumn: "span 2" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                <p className="st-card-title" style={{ margin: 0 }}>По модели</p>
                <div style={{ display: "flex", gap: "0.4rem" }}>
                  {(["total_tokens", "cost_usd"] as const).map(m => (
                    <button
                      key={m}
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: "0.62rem",
                        textTransform: "uppercase",
                        padding: "0.15rem 0.45rem",
                        borderRadius: "3px",
                        border: "1px solid var(--edge-soft)",
                        background: tokenMetric === m ? "var(--orange)" : "transparent",
                        color: tokenMetric === m ? "var(--bg)" : "var(--muted)",
                        cursor: "pointer",
                      }}
                      type="button"
                      onClick={() => setTokenMetric(m)}
                    >
                      {m === "cost_usd" ? "cost" : "tokens"}
                    </button>
                  ))}
                </div>
              </div>
              <UsageBreakdown data={u.by_model} metric={tokenMetric} />
            </div>
          )}

          {/* By task type token usage */}
          {u && (
            <div className="st-card">
              <p className="st-card-title">Токены по типу задачи</p>
              <UsageBreakdown data={u.by_task_type} metric={tokenMetric} />
            </div>
          )}

        </div>
      )}
    </main>
  );
}
