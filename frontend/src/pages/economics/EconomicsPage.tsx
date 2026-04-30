import { useEffect, useState } from "react";

import { EconomicsSnapshot, generateMockRevenue, getEconomicsSnapshot } from "../../api";
import { formatDateTime } from "../../lib/formatters";

type LoadState = "idle" | "loading" | "loaded" | "error";
type ActionState = "idle" | "running" | "done" | "error";

export function EconomicsPage() {
  const [snapshot, setSnapshot] = useState<EconomicsSnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [error, setError] = useState<string>("");
  const [actionMessage, setActionMessage] = useState<string>("");

  async function loadEconomics(cancelled: () => boolean = () => false) {
    setLoadState("loading");
    setError("");

    try {
      const loadedSnapshot = await getEconomicsSnapshot();

      if (cancelled()) {
        return;
      }

      setSnapshot(loadedSnapshot);
      setLoadState("loaded");
    } catch (loadError) {
      if (cancelled()) {
        return;
      }

      setLoadState("error");
      setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить economics");
    }
  }

  useEffect(() => {
    let cancelled = false;
    void loadEconomics(() => cancelled);

    return () => {
      cancelled = true;
    };
  }, []);

  async function createMockRevenue() {
    if (actionState === "running") {
      return;
    }

    setActionState("running");
    setActionMessage("");
    setError("");

    try {
      const result = await generateMockRevenue();
      setActionState("done");
      setActionMessage(`mock revenue: +${result.created_count} / updated ${result.updated_count}`);
      await loadEconomics();
    } catch (actionError) {
      setActionState("error");
      setError(
        actionError instanceof Error ? actionError.message : "Не удалось создать mock revenue"
      );
    }
  }

  return (
    <main className="page economics-page">
      <section className="factory-hud" aria-label="Economics summary">
        <div className="hud-panel hud-main">
          <p className="eyebrow">heavy-lifting · economics</p>
          <h1>Money Flow</h1>
          <p className="intro">
            Snapshot закрытых root-задач: revenue, token cost, profit и явные пробелы в
            экономической модели MVP.
          </p>
        </div>
        <div className="hud-panel hud-card">
          <span className="mono-label">Profit</span>
          <strong>{formatMoney(snapshot?.totals.profit_usd ?? "0.000000")}</strong>
          <span className="muted">{snapshot?.totals.closed_roots_count ?? 0} closed roots</span>
        </div>
      </section>

      {loadState === "loading" ? <p className="factory-loading">Загрузка economics...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <section className="factory-telemetry" aria-label="Economics telemetry">
            <span>
              <strong>GET /economics</strong>
            </span>
            <span>generated_at={formatDateTime(snapshot.generated_at)}</span>
            <span>bucket={snapshot.period.bucket}</span>
            <span>missing={snapshot.totals.missing_revenue_count}</span>
            <button
              className="inline-action"
              type="button"
              disabled={actionState === "running"}
              onClick={createMockRevenue}
            >
              {actionState === "running" ? "Generating..." : "Mock revenue"}
            </button>
            {actionMessage ? <span className="status-inline-ok">{actionMessage}</span> : null}
          </section>

          <section className="economics-summary-grid" aria-label="Money summary">
            <Metric label="Revenue" value={formatMoney(snapshot.totals.revenue_usd)} />
            <Metric label="Token cost" value={formatMoney(snapshot.totals.token_cost_usd)} />
            <Metric
              label="Profit"
              tone={snapshot.totals.profit_usd.startsWith("-") ? "bad" : "normal"}
              value={formatMoney(snapshot.totals.profit_usd)}
            />
            <Metric label="Monetized" value={snapshot.totals.monetized_roots_count} />
            <Metric
              label="Missing"
              tone={snapshot.totals.missing_revenue_count > 0 ? "bad" : "normal"}
              value={snapshot.totals.missing_revenue_count}
            />
            <Metric label="Closed" value={snapshot.totals.closed_roots_count} />
          </section>

          <section className="economics-table-panel" aria-label="Economics series">
            <div className="section-heading compact">
              <p className="eyebrow">Series</p>
              <h2>Bucketed money</h2>
            </div>
            <DataTable
              emptyText="No closed roots in this period."
              rows={snapshot.series.map((point) => [
                point.bucket,
                String(point.closed_roots_count),
                String(point.monetized_roots_count),
                formatMoney(point.revenue_usd),
                formatMoney(point.token_cost_usd),
                formatMoney(point.profit_usd)
              ])}
              headers={["bucket", "closed", "monetized", "revenue", "cost", "profit"]}
            />
          </section>

          <section className="economics-table-panel" aria-label="Economics roots">
            <div className="section-heading compact">
              <p className="eyebrow">Roots</p>
              <h2>Closed root tasks</h2>
            </div>
            <DataTable
              emptyText="No closed roots."
              rows={snapshot.roots.map((root) => [
                String(root.root_task_id),
                root.external_task_id ?? "none",
                formatDateTime(root.closed_at),
                root.revenue_usd ? formatMoney(root.revenue_usd) : "missing",
                formatMoney(root.token_cost_usd),
                root.profit_usd ? formatMoney(root.profit_usd) : "missing",
                root.revenue_source ?? "none",
                root.revenue_confidence ?? "none"
              ])}
              headers={[
                "root",
                "external",
                "closed",
                "revenue",
                "cost",
                "profit",
                "source",
                "confidence"
              ]}
            />
          </section>

          <section className="gaps-panel" aria-label="Economics data gaps">
            <div>
              <p className="eyebrow">Data gaps</p>
              <h2>Честные пробелы экономики MVP</h2>
            </div>
            <ul>
              {snapshot.data_gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </main>
  );
}

function DataTable({
  headers,
  rows,
  emptyText
}: {
  headers: string[];
  rows: string[][];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="muted">{emptyText}</p>;
  }

  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join("|")}>
              {row.map((cell, index) => (
                <td key={`${index}:${cell}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "normal"
}: {
  label: string;
  value: number | string;
  tone?: "normal" | "bad";
}) {
  return (
    <span className="metric">
      <span className="metric-label">{label}</span>
      <strong className={tone === "bad" ? "metric-value bad" : "metric-value"}>{value}</strong>
    </span>
  );
}

function formatMoney(value: string): string {
  return `$${value}`;
}
