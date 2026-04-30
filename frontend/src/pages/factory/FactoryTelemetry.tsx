import type { FactorySnapshot } from "../../api";
import { formatDateTime } from "../../lib/formatters";

type FactoryTelemetryProps = {
  snapshot: FactorySnapshot;
};

export function FactoryTelemetry({ snapshot }: FactoryTelemetryProps) {
  const totalWip = snapshot.stations.reduce((sum, station) => sum + station.wip_count, 0);
  const totalFailed = snapshot.stations.reduce((sum, station) => sum + station.failed_count, 0);
  const totalActive = snapshot.stations.reduce((sum, station) => sum + station.active_count, 0);

  return (
    <section className="factory-telemetry" aria-label="Factory telemetry">
      <span>
        <strong>GET /factory</strong>
      </span>
      <span>generated_at={formatDateTime(snapshot.generated_at)}</span>
      <span>wip={totalWip}</span>
      <span>active={totalActive}</span>
      <span>failed={totalFailed}</span>
    </section>
  );
}
