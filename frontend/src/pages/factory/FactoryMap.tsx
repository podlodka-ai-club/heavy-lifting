import type { FactorySnapshot } from "../../api";
import { FactoryRoutes } from "./FactoryRoutes";
import { OrchestratorNode } from "./OrchestratorNode";
import { StationCard } from "./StationCard";

type FactoryMapProps = {
  snapshot: FactorySnapshot;
  prefersReducedMotion: boolean;
};

export function FactoryMap({ snapshot, prefersReducedMotion }: FactoryMapProps) {
  return (
    <section className="factory-map" aria-label="Factory station map">
      <FactoryRoutes
        prefersReducedMotion={prefersReducedMotion}
        stations={snapshot.stations}
      />

      <OrchestratorNode />

      <div className="station-grid">
        {snapshot.stations.map((station) => (
          <StationCard
            isBottleneck={snapshot.bottleneck?.station === station.name}
            key={station.name}
            station={station}
          />
        ))}
      </div>
    </section>
  );
}
