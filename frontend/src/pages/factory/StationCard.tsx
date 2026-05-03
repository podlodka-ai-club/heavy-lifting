import type { FactoryStation } from "../../api";
import { formatAge } from "../../lib/formatters";
import { getStationMeta } from "./factoryMeta";

type StationCardProps = {
  station: FactoryStation;
  isBottleneck: boolean;
};

export function StationCard({ station, isBottleneck }: StationCardProps) {
  const meta = getStationMeta(station.name);

  return (
    <article
      className={`station-card station-${station.name}${isBottleneck ? " bottleneck" : ""}`}
      aria-label={`${meta.shortLabel} station`}
    >
      <div className="station-topline">
        <span className="mono-label">{meta.label}</span>
        {isBottleneck ? <span className="hot-badge">BOTTLENECK</span> : null}
      </div>
      <div className="station-machine" aria-hidden="true">
        <div className="machine-cube">
          <span className="cube-top" />
          <span className="cube-front" />
          <span className="cube-side" />
        </div>
        <div className="machine-stack">
          {Array.from({ length: Math.min(station.wip_count, 5) }, (_, index) => (
            <span key={index} />
          ))}
        </div>
      </div>
      <h2>{meta.title}</h2>
      <div className="wip-meter" aria-label={`${meta.shortLabel} WIP ${station.wip_count}`}>
        <span
          style={{
            minWidth: station.wip_count > 0 ? "3px" : "0",
            width: `${Math.min(100, station.wip_count * 12)}%`
          }}
        />
      </div>
      <div className="metric-grid">
        <Metric label="WIP" value={station.wip_count} />
        <Metric label="Queue" value={station.queue_count} />
        <Metric label="Active" value={station.active_count} />
        <Metric
          label="Failed"
          tone={station.failed_count > 0 ? "bad" : "normal"}
          value={station.failed_count}
        />
        <Metric label="Oldest q" value={formatAge(station.oldest_queue_age_seconds)} />
        <Metric label="Oldest a" value={formatAge(station.oldest_active_age_seconds)} />
      </div>
      <div className="status-strip" aria-label={`${meta.shortLabel} status counts`}>
        <span>new {station.counts_by_status.new}</span>
        <span>processing {station.counts_by_status.processing}</span>
        <span>done {station.counts_by_status.done}</span>
        <span>failed {station.counts_by_status.failed}</span>
        <span>total {station.total_count}</span>
      </div>
    </article>
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
