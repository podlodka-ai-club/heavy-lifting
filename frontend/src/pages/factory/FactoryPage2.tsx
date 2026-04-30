import { useEffect, useState } from "react";

import type { FactorySnapshot, FactoryStation } from "../../api";
import { getFactorySnapshot } from "../../api";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatAge, formatDateTime } from "../../lib/formatters";
import "./factory2.css";

type StationName = FactoryStation["name"];

/* ─── Meta per station ───────────────────────────────────────────────────── */

const META: Record<
  StationName,
  { label: string; role: string; color: string; cls: string }
> = {
  fetch:       { label: "FETCH",     role: "Загрузчик",        color: "var(--orange)", cls: "fetch"      },
  execute:     { label: "EXECUTE",   role: "Пресс",            color: "var(--yellow)", cls: "execute"    },
  pr_feedback: { label: "REVIEW",    role: "Контроль качества", color: "var(--cyan)",   cls: "review"     },
  deliver:     { label: "DELIVER",   role: "Отгрузка",          color: "var(--violet)", cls: "deliver"    },
};

/* ─── Page ───────────────────────────────────────────────────────────────── */

export function FactoryPage2() {
  const [snapshot, setSnapshot] = useState<FactorySnapshot | null>(null);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [error, setError] = useState("");
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoadState("loading");
      setError("");
      try {
        const data = await getFactorySnapshot();
        if (!cancelled) { setSnapshot(data); setLoadState("loaded"); }
      } catch (e) {
        if (!cancelled) { setLoadState("error"); setError(e instanceof Error ? e.message : "Ошибка загрузки"); }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  const bn = snapshot?.bottleneck?.station ?? null;

  return (
    <main className="page f2-page">
      {/* HUD */}
      <section className="f2-hud" aria-label="Factory v2">
        <div className="hud-panel">
          <p className="eyebrow">heavy-lifting · завод по Голдратту v2</p>
          <h1>Factory Floor</h1>
          <p className="intro">
            Каждый агент — станок. Высота штабеля перед ним — очередь. Конвейер несёт задачи
            между станками. Ограничение системы светится жёлтым.
          </p>
        </div>
        <div className="hud-panel hud-card">
          <span className="mono-label">Bottleneck</span>
          <strong style={{ color: "var(--orange-2)", fontFamily: "var(--mono)", fontSize: "1.7rem" }}>
            {bn ? META[bn].label : "none"}
          </strong>
          <span className="muted">{snapshot?.bottleneck ? `WIP ${snapshot.bottleneck.wip_count}` : "No WIP"}</span>
        </div>
      </section>

      {loadState === "loading" ? <p className="factory-loading">Загрузка factory...</p> : null}
      {error ? <p className="status-error" role="alert">{error}</p> : null}

      {snapshot ? (
        <>
          {/* Telemetry */}
          <section className="factory-telemetry">
            <span><strong>GET /factory</strong></span>
            <span>{formatDateTime(snapshot.generated_at)}</span>
            {snapshot.stations.map(s => (
              <span key={s.name}>
                {META[s.name].label.toLowerCase()} wip={s.wip_count} q={s.queue_count}
              </span>
            ))}
          </section>

          {/* Scene */}
          <FactoryScene bottleneck={bn} reduced={reduced} snapshot={snapshot} />

          {/* Data gaps */}
          {snapshot.data_gaps.length > 0 && (
            <section className="gaps-panel hud-panel" aria-label="Data gaps">
              <div>
                <p className="eyebrow">Data gaps</p>
                <h2>Честные пробелы</h2>
              </div>
              <ul>
                {snapshot.data_gaps.map(g => <li key={g}>{g}</li>)}
              </ul>
            </section>
          )}
        </>
      ) : null}
    </main>
  );
}

/* ─── Factory Scene ──────────────────────────────────────────────────────── */

function FactoryScene({
  snapshot,
  bottleneck,
  reduced,
}: {
  snapshot: FactorySnapshot;
  bottleneck: StationName | null;
  reduced: boolean;
}) {
  return (
    <section className="f2-scene-wrap" aria-label="Factory floor">
      <div className="f2-scene">
        {/* isometric grid floor — decorative */}
        <div aria-hidden className="f2-grid" />

        {/* factory floor surface */}
        <div aria-hidden className="f2-floor-surface" />

        {/* machines + belt */}
        <div className="f2-factory-row" aria-label="Pipeline">
          {snapshot.stations.map((station, i) => {
            const isLast = i === snapshot.stations.length - 1;
            const isBottleneck = station.name === bottleneck;
            const meta = META[station.name];

            return (
              <div key={station.name} className="f2-station-slot">
                {/* queue stack above belt, before machine */}
                <QueueStack
                  cls={meta.cls}
                  color={meta.color}
                  count={station.queue_count}
                />

                {/* the machine */}
                <Machine
                  isBottleneck={isBottleneck}
                  label={meta.label}
                  reduced={reduced}
                  role={meta.role}
                  station={station}
                />

                {/* belt segment to next station */}
                {isLast ? null : (
                  <BeltSegment
                    color={meta.color}
                    reduced={reduced}
                    wipCount={station.wip_count}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* stats panels below scene */}
      <div className="f2-stats-row">
        {snapshot.stations.map(station => (
          <StationStats key={station.name} station={station} />
        ))}
      </div>
    </section>
  );
}

/* ─── Queue Stack ────────────────────────────────────────────────────────── */

function QueueStack({
  count,
  color,
  cls,
}: {
  count: number;
  color: string;
  cls: string;
}) {
  const visible = Math.min(count, 10);
  const overflow = count > 10 ? count - 10 : 0;

  return (
    <div
      className={`f2-queue f2-queue-${cls}`}
      aria-label={`Queue: ${count} items`}
      style={{ "--q-color": color } as React.CSSProperties}
    >
      {overflow > 0 && (
        <span className="f2-queue-overflow">+{overflow}</span>
      )}
      {Array.from({ length: visible }).map((_, i) => (
        <span key={i} className="f2-queue-box" />
      ))}
    </div>
  );
}

/* ─── Machine (4 distinct visual variants) ───────────────────────────────── */

function Machine({
  station,
  isBottleneck,
  label,
  role,
  reduced,
}: {
  station: FactoryStation;
  isBottleneck: boolean;
  label: string;
  role: string;
  reduced: boolean;
}) {
  const meta = META[station.name];
  const active = station.active_count > 0 || station.wip_count > 0;
  const lightCls =
    isBottleneck ? "warn" : station.failed_count > 0 ? "bad" : active ? "ok" : "idle";
  const speedCls = reduced ? "" : isBottleneck ? "fast" : active ? "slow" : "";

  return (
    <div
      className={`f2-machine f2-machine-${meta.cls}${isBottleneck ? " f2-bottleneck" : ""}`}
      aria-label={`${label} machine`}
      style={{ "--m-color": meta.color } as React.CSSProperties}
    >
      {/* Machine-specific interior (chimneys, pistons, etc.) */}
      <MachineInterior
        active={active}
        isBottleneck={isBottleneck}
        reduced={reduced}
        speedCls={speedCls}
        variant={meta.cls}
      />

      {/* Status indicator light */}
      <div aria-hidden className={`f2-status-light f2-light-${lightCls}`} />

      {/* WIP fill — liquid level inside machine */}
      <div
        aria-hidden
        className="f2-wip-fill"
        style={{ height: `${Math.min(80, station.wip_count * 14)}%` }}
      />

      {/* Machine nameplate */}
      <div className="f2-nameplate">
        <span className="f2-nameplate-label">{label}</span>
        <span className="f2-nameplate-role">{role}</span>
      </div>
    </div>
  );
}

/* ─── Machine interior variants ─────────────────────────────────────────── */

function MachineInterior({
  variant,
  speedCls,
  isBottleneck,
  active,
  reduced,
}: {
  variant: string;
  speedCls: string;
  isBottleneck: boolean;
  active: boolean;
  reduced: boolean;
}) {
  if (variant === "fetch") {
    return (
      <>
        {/* Intake funnel */}
        <div aria-hidden className="f2-fetch-funnel" />
        {/* conveyor roller */}
        <div aria-hidden className="f2-fetch-roller" />
        <div aria-hidden className="f2-fetch-roller f2-roller-2" />
        {/* Single chimney */}
        <div aria-hidden className="f2-chimney f2-chimney-1">
          {(!reduced && active) && <div className="f2-smoke" />}
        </div>
      </>
    );
  }

  if (variant === "execute") {
    return (
      <>
        {/* Three chimneys */}
        <div aria-hidden className="f2-chimney f2-chimney-1">
          {(!reduced && isBottleneck) && <div className="f2-smoke f2-smoke-heavy" />}
        </div>
        <div aria-hidden className="f2-chimney f2-chimney-2">
          {(!reduced && active) && <div className="f2-smoke" />}
        </div>
        <div aria-hidden className="f2-chimney f2-chimney-3">
          {(!reduced && isBottleneck) && <div className="f2-smoke" />}
        </div>
        {/* Piston arm */}
        <div
          aria-hidden
          className={`f2-piston-arm${speedCls ? ` f2-piston-${speedCls}` : ""}`}
        />
        <div aria-hidden className="f2-piston-head" />
        {/* Gear */}
        <div aria-hidden className={`f2-gear${speedCls ? ` f2-gear-${speedCls}` : ""}`} />
      </>
    );
  }

  if (variant === "review") {
    return (
      <>
        {/* Scanning arm */}
        <div
          aria-hidden
          className={`f2-scan-arm${(!reduced && active) ? " f2-scan-active" : ""}`}
        />
        {/* Display screens */}
        <div aria-hidden className="f2-screen f2-screen-1" />
        <div aria-hidden className="f2-screen f2-screen-2" />
        {/* Antenna */}
        <div aria-hidden className="f2-antenna" />
      </>
    );
  }

  if (variant === "deliver") {
    return (
      <>
        {/* Output door/hatch */}
        <div aria-hidden className="f2-hatch" />
        {/* Two chimneys */}
        <div aria-hidden className="f2-chimney f2-chimney-1">
          {(!reduced && active) && <div className="f2-smoke" />}
        </div>
        <div aria-hidden className="f2-chimney f2-chimney-2" />
        {/* Exit chute */}
        <div aria-hidden className="f2-chute" />
        {/* Spinning dial */}
        <div aria-hidden className={`f2-dial${speedCls ? ` f2-dial-${speedCls}` : ""}`} />
      </>
    );
  }

  return null;
}

/* ─── Belt Segment ───────────────────────────────────────────────────────── */

function BeltSegment({
  wipCount,
  color,
  reduced,
}: {
  wipCount: number;
  color: string;
  reduced: boolean;
}) {
  const items = Math.min(wipCount, 4);

  return (
    <div
      className="f2-belt-segment"
      style={{ "--b-color": color } as React.CSSProperties}
    >
      <div aria-hidden className={`f2-belt-surface${reduced ? "" : " f2-belt-moving"}`} />
      {/* WIP items on belt */}
      <div aria-hidden className="f2-belt-items">
        {Array.from({ length: items }).map((_, i) => (
          <span
            key={i}
            className={`f2-belt-item${reduced ? "" : " f2-item-rolling"}`}
            style={{ animationDelay: `${i * 0.55}s` }}
          />
        ))}
      </div>
    </div>
  );
}

/* ─── Station Stats (below scene) ────────────────────────────────────────── */

function StationStats({ station }: { station: FactoryStation }) {
  const meta = META[station.name];
  return (
    <div className="f2-station-stats" style={{ "--m-color": meta.color } as React.CSSProperties}>
      <div className="f2-stats-header">
        <span className="mono-label" style={{ color: meta.color }}>{meta.label}</span>
        {station.failed_count > 0 && (
          <span className="f2-fail-badge">{station.failed_count} fail</span>
        )}
      </div>
      <div className="f2-wip-meter-bar" aria-label={`WIP ${station.wip_count}`}>
        <span style={{ width: `${Math.min(100, station.wip_count * 14)}%` }} />
      </div>
      <div className="f2-stats-grid">
        <Metric label="WIP"     value={station.wip_count} />
        <Metric label="Queue"   value={station.queue_count} />
        <Metric label="Active"  value={station.active_count} />
        <Metric
          label="Failed"
          tone={station.failed_count > 0 ? "bad" : "normal"}
          value={station.failed_count}
        />
        <Metric label="Oldest q"  value={formatAge(station.oldest_queue_age_seconds)} />
        <Metric label="Oldest a"  value={formatAge(station.oldest_active_age_seconds)} />
      </div>
      <div className="f2-status-strip">
        <span>new {station.counts_by_status.new}</span>
        <span>proc {station.counts_by_status.processing}</span>
        <span>done {station.counts_by_status.done}</span>
        <span>fail {station.counts_by_status.failed}</span>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "normal",
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
