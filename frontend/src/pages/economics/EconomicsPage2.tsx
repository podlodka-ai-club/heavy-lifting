import { useEffect, useState } from "react";

import type { EconomicsPeriodParams, EconomicsRoot, EconomicsSeriesPoint, EconomicsSnapshot } from "../../api";
import { generateMockRevenue, getEconomicsSnapshot } from "../../api";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatDateTime } from "../../lib/formatters";
import "./economics2.css";

type LoadState = "idle" | "loading" | "loaded" | "error";
type ActionState = "idle" | "running" | "done" | "error";

type PeriodPreset = "7d" | "30d" | "90d" | "all";
const ALL_PERIOD_FROM = "1970-01-01";

function presetToPeriod(
  preset: PeriodPreset,
  bucket: "day" | "week" | "month"
): EconomicsPeriodParams | undefined {
  if (preset === "all") {
    return {
      from: ALL_PERIOD_FROM,
      bucket,
    };
  }
  const days = preset === "7d" ? 7 : preset === "30d" ? 30 : 90;
  const to = new Date();
  const from = new Date(to.getTime() - days * 86_400_000);
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
    bucket,
  };
}

const COIN_POSITIONS: Array<{ top: string; left: string }> = [
  { top: "16%", left: "15%" },
  { top: "30%", left: "56%" },
  { top: "12%", left: "72%" },
  { top: "44%", left: "28%" },
  { top: "26%", left: "88%" },
  { top: "54%", left: "8%" },
  { top: "60%", left: "46%" },
  { top: "68%", left: "22%" },
  { top: "64%", left: "78%" },
  { top: "80%", left: "40%" },
  { top: "22%", left: "38%" },
  { top: "74%", left: "62%" },
];

export function EconomicsPage2() {
  const [snapshot, setSnapshot] = useState<EconomicsSnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [preset, setPreset] = useState<PeriodPreset>("all");
  const [bucket, setBucket] = useState<"day" | "week" | "month">("day");
  const reducedMotion = usePrefersReducedMotion();

  async function load(
    period?: EconomicsPeriodParams,
    cancelled: () => boolean = () => false,
  ) {
    setLoadState("loading");
    setError("");
    try {
      const data = await getEconomicsSnapshot(period);
      if (!cancelled()) {
        setSnapshot(data);
        setLoadState("loaded");
      }
    } catch (e) {
      if (!cancelled()) {
        setLoadState("error");
        setError(e instanceof Error ? e.message : "Не удалось загрузить economics");
      }
    }
  }

  useEffect(() => {
    let cancelled = false;
    void load(presetToPeriod(preset, bucket), () => cancelled);
    return () => { cancelled = true; };
  }, [preset, bucket]);

  async function mockRevenue() {
    if (actionState === "running") return;
    setActionState("running");
    setActionMsg("");
    setError("");
    try {
      const result = await generateMockRevenue();
      setActionState("done");
      setActionMsg(`+${result.created_count} monetized`);
      await load(presetToPeriod(preset, bucket));
    } catch (e) {
      setActionState("error");
      setError(e instanceof Error ? e.message : "Mock revenue failed");
    }
  }

  const totals = snapshot?.totals;
  const margin = computeMargin(totals?.revenue_usd, totals?.token_cost_usd);

  return (
    <main className="page e2-page">
      <section className="factory-hud e2-hud" aria-label="Economics overview">
        <div className="hud-panel hud-main">
          <p className="eyebrow">heavy-lifting · economics · scrooge vault</p>
          <h1>
            <span className="e2-hero-profit">{fmtMoney(totals?.profit_usd ?? "0.000000")}</span>
            <span className="e2-hero-label"> чистой прибыли</span>
          </h1>
          <p className="intro">
            Монеты падают от закрытых задач. Токены пробивают дыры в дне. Скрудж смотрит на
            разницу.
          </p>
        </div>
        <div className="hud-panel hud-card e2-kpi-card">
          <div className="e2-kpi-row">
            <Kpi label="Revenue" value={fmtMoney(totals?.revenue_usd ?? "0")} tone="green" />
            <Kpi label="Token cost" value={fmtMoney(totals?.token_cost_usd ?? "0")} tone="red" />
          </div>
          <div className="e2-kpi-row">
            <Kpi label="Margin" value={margin} tone="normal" />
            <Kpi label="Roots closed" value={totals?.closed_roots_count ?? 0} tone="normal" />
          </div>
        </div>
      </section>

      {loadState === "loading" ? <p className="factory-loading">Загружаю экономику...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <section className="e2-period-bar" aria-label="Period filter">
            <div className="e2-period-presets">
              {(["7d", "30d", "90d", "all"] as PeriodPreset[]).map(p => (
                <button
                  key={p}
                  className={`e2-period-btn${preset === p ? " active" : ""}`}
                  type="button"
                  onClick={() => setPreset(p)}
                >
                  {p}
                </button>
              ))}
            </div>
            <div className="e2-period-buckets">
              {(["day", "week", "month"] as const).map(b => (
                <button
                  key={b}
                  className={`e2-period-btn${bucket === b ? " active" : ""}`}
                  type="button"
                  onClick={() => setBucket(b)}
                >
                  {b}
                </button>
              ))}
            </div>
          </section>

          <section className="factory-telemetry" aria-label="Telemetry">
            <span>
              <strong>GET /economics</strong>
            </span>
            <span>{formatDateTime(snapshot.generated_at)}</span>
            <span>
              {preset === "all"
                ? "all available data"
                : snapshot.period.from && snapshot.period.to
                ? `${snapshot.period.from.slice(0, 10)} → ${snapshot.period.to.slice(0, 10)}`
                : "all available data"}
            </span>
            <span className={snapshot.totals.missing_revenue_count > 0 ? "e2-warn" : ""}>
              missing: {snapshot.totals.missing_revenue_count}
            </span>
            <button
              className="inline-action"
              disabled={actionState === "running"}
              type="button"
              onClick={() => void mockRevenue()}
            >
              {actionState === "running" ? "Generating..." : "Mock revenue"}
            </button>
            {actionMsg ? <span className="status-inline-ok">{actionMsg}</span> : null}
          </section>

          <MoneyFlow
            dataGaps={snapshot.data_gaps}
            reducedMotion={reducedMotion}
            roots={snapshot.roots}
            totals={snapshot.totals}
          />

          {snapshot.series.length > 0 ? (
            <SeriesPanel bucket={snapshot.period.bucket} series={snapshot.series} />
          ) : null}
        </>
      ) : null}
    </main>
  );
}

// ─── Money Flow (3-col vault visualization) ──────────────────────────────────

function MoneyFlow({
  roots,
  totals,
  dataGaps,
  reducedMotion,
}: {
  roots: EconomicsRoot[];
  totals: EconomicsSnapshot["totals"];
  dataGaps: string[];
  reducedMotion: boolean;
}) {
  const revenue = parseFloat(totals.revenue_usd);
  const cost = parseFloat(totals.token_cost_usd);
  const [goldLevel, setGoldLevel] = useState(0);

  useEffect(() => {
    const level =
      revenue > 0 ? Math.max(6, Math.min(88, ((revenue - cost) / revenue) * 88)) : 6;
    const timer = setTimeout(() => setGoldLevel(level), 140);
    return () => clearTimeout(timer);
  }, [revenue, cost]);

  const isNegative = cost > revenue && revenue > 0;

  return (
    <section className="hud-panel e2-flow" aria-label="Money flow visualization">
      <InflowPanel roots={roots} />
      <VaultCenter
        closedCount={totals.closed_roots_count}
        goldLevel={goldLevel}
        isNegative={isNegative}
        reducedMotion={reducedMotion}
      />
      <LeaksPanel dataGaps={dataGaps} totals={totals} />
    </section>
  );
}

// ─── Vault center ─────────────────────────────────────────────────────────────

function VaultCenter({
  goldLevel,
  isNegative,
  closedCount,
  reducedMotion,
}: {
  goldLevel: number;
  isNegative: boolean;
  closedCount: number;
  reducedMotion: boolean;
}) {
  return (
    <div className="e2-vault-col">
      <ScroofgeIcon />
      <div className="e2-vault" aria-label={`Хранилище: ${goldLevel.toFixed(0)}% заполнено`}>
        <div aria-hidden className="e2-vault-rim" />
        <div
          aria-hidden
          className={`e2-vault-gold${isNegative ? " negative" : ""}`}
          style={{ height: `${goldLevel}%` }}
        >
          <div className="e2-vault-surface" />
          <div aria-hidden className="e2-coins-pile">
            {COIN_POSITIONS.map((pos, i) => (
              <span key={i} className="e2-coin-static" style={pos} />
            ))}
          </div>
        </div>

        {reducedMotion ? null : (
          <div aria-hidden className="e2-coin-shower">
            <span className="e2-falling-coin c1">¤</span>
            <span className="e2-falling-coin c2">¤</span>
            <span className="e2-falling-coin c3">¤</span>
            <span className="e2-falling-coin c4">¤</span>
          </div>
        )}

        <div aria-hidden className="e2-leaks">
          {[0, 1, 2].map((i) => (
            <div key={i} className="e2-leak-slot">
              <span className="e2-drip" style={{ animationDelay: `${i * 0.42}s` }} />
              <span className="e2-drip" style={{ animationDelay: `${i * 0.42 + 0.72}s` }} />
            </div>
          ))}
        </div>
      </div>
      <span className="mono-label e2-vault-label">
        хранилище · {closedCount} root{closedCount !== 1 ? "s" : ""}
      </span>
    </div>
  );
}

// ─── Scrooge duck (pure CSS art) ─────────────────────────────────────────────

function ScroofgeIcon() {
  return (
    <div aria-hidden className="e2-scrooge">
      <div className="scr-hat">
        <div className="scr-brim" />
      </div>
      <div className="scr-hat-band" />
      <div className="scr-head" />
      <div className="scr-beak" />
      <div className="scr-eye" />
      <div className="scr-glasses" />
      <div className="scr-collar" />
      <div className="scr-coat" />
      <div className="scr-cane" />
    </div>
  );
}

// ─── Inflow panel (left) ──────────────────────────────────────────────────────

function InflowPanel({ roots }: { roots: EconomicsRoot[] }) {
  const recent = roots.slice(-8).reverse();
  const totalRevenue = roots.reduce((s, r) => s + parseFloat(r.revenue_usd ?? "0"), 0);
  const missingCount = roots.filter((r) => !r.revenue_usd).length;

  return (
    <div className="e2-inflow-col">
      <p className="eyebrow e2-col-eyebrow">+ Revenue inflow</p>
      <p className="e2-col-big">{fmtMoney(totalRevenue.toFixed(6))}</p>
      {missingCount > 0 ? (
        <p className="e2-warn-small">{missingCount} без revenue</p>
      ) : null}
      <div className="e2-task-list">
        {recent.map((root) => (
          <TaskCoin key={root.root_task_id} root={root} />
        ))}
      </div>
      {roots.length > 8 ? (
        <p className="muted e2-more">+{roots.length - 8} more roots</p>
      ) : null}
    </div>
  );
}

function TaskCoin({ root }: { root: EconomicsRoot }) {
  const hasRevenue = root.revenue_usd !== null;
  return (
    <div className={`e2-task-row${hasRevenue ? "" : " missing"}`}>
      <span aria-hidden className={`e2-coin-badge${hasRevenue ? "" : " empty"}`}>
        {hasRevenue ? "¤" : "?"}
      </span>
      <span className="e2-task-id">{root.external_task_id ?? `#${root.root_task_id}`}</span>
      <span className="e2-task-amount">
        {hasRevenue && root.revenue_usd ? fmtMoney(root.revenue_usd) : "—"}
      </span>
    </div>
  );
}

// ─── Leaks panel (right) ──────────────────────────────────────────────────────

function LeaksPanel({
  totals,
  dataGaps,
}: {
  totals: EconomicsSnapshot["totals"];
  dataGaps: string[];
}) {
  const revenue = parseFloat(totals.revenue_usd);
  const cost = parseFloat(totals.token_cost_usd);
  const costRatio = revenue > 0 ? Math.min(100, (cost / revenue) * 100) : 0;

  return (
    <div className="e2-leaks-col">
      <p className="eyebrow e2-col-eyebrow e2-out-label">— Token leaks</p>
      <p className="e2-col-big e2-col-out">{fmtMoney(totals.token_cost_usd)}</p>

      <div className="e2-cost-ratio-wrap">
        <div className="e2-cost-ratio-bar">
          <div className="e2-cost-ratio-fill" style={{ width: `${costRatio}%` }} />
        </div>
        <span className="muted e2-ratio-label">{costRatio.toFixed(1)}% от выручки</span>
      </div>

      <div className="e2-gap-section">
        <p className="e2-gap-title">Незапломбированные дыры</p>
        {dataGaps.map((gap) => (
          <div key={gap} className="e2-gap-row">
            <span aria-hidden className="e2-gap-hole" />
            <span className="e2-gap-name">{gap.replaceAll("_", " ")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Series chart ─────────────────────────────────────────────────────────────

function SeriesPanel({
  series,
  bucket,
}: {
  series: EconomicsSeriesPoint[];
  bucket: string;
}) {
  const maxRevenue = Math.max(...series.map((p) => parseFloat(p.revenue_usd)), 1);

  return (
    <section className="hud-panel e2-series-section" aria-label="Economics series">
      <div className="e2-series-header">
        <p className="eyebrow">Хроника — {bucket}</p>
        <h2>Динамика потока</h2>
      </div>
      <div className="e2-series-chart-wrap">
        <div className="e2-series-chart">
          {series.map((point) => {
            const revenue = parseFloat(point.revenue_usd);
            const cost = parseFloat(point.token_cost_usd);
            const profit = parseFloat(point.profit_usd);
            const revH = Math.max(2, (revenue / maxRevenue) * 100);
            const costH = Math.max(2, (cost / maxRevenue) * 100);
            return (
              <div key={point.bucket} className="e2-series-group">
                <div className="e2-series-bars">
                  <div
                    className="e2-bar-revenue"
                    style={{ height: `${revH}%` }}
                    title={`Revenue: ${fmtMoney(point.revenue_usd)}`}
                  />
                  <div
                    className="e2-bar-cost"
                    style={{ height: `${costH}%` }}
                    title={`Cost: ${fmtMoney(point.token_cost_usd)}`}
                  />
                </div>
                <div className="e2-series-tick">
                  <span className="e2-tick-date">
                    {point.bucket.slice(5) || point.bucket}
                  </span>
                  <span className={`e2-tick-profit${profit >= 0 ? " pos" : " neg"}`}>
                    {profit >= 0 ? "+" : ""}
                    {fmtMoney(point.profit_usd)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="e2-series-legend">
        <span className="e2-legend-item rev">Revenue</span>
        <span className="e2-legend-item cost">Token cost</span>
      </div>
    </section>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: "green" | "red" | "normal";
}) {
  const cls =
    tone === "green" ? "metric-value e2-green" : tone === "red" ? "metric-value bad" : "metric-value";
  return (
    <div className="e2-kpi">
      <span className="metric-label">{label}</span>
      <strong className={cls}>{value}</strong>
    </div>
  );
}

function computeMargin(revenue?: string, cost?: string): string {
  if (!revenue || !cost) return "—";
  const r = parseFloat(revenue);
  const c = parseFloat(cost);
  if (r <= 0) return "—";
  return `${(((r - c) / r) * 100).toFixed(1)}%`;
}

function fmtMoney(value: string | number): string {
  const num = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(num)) return "$0.00";
  return `$${num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
