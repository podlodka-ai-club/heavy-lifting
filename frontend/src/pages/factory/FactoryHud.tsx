import type { FactorySnapshot } from "../../api";

type FactoryHudProps = {
  bottleneck: FactorySnapshot["bottleneck"];
};

export function FactoryHud({ bottleneck }: FactoryHudProps) {
  return (
    <section className="factory-hud" aria-label="Factory summary">
      <div className="hud-panel hud-main">
        <p className="eyebrow">heavy-lifting · factory command map</p>
        <h1>Factory Flow</h1>
        <p className="intro">
          Live snapshot из `/factory`: станции, очереди, активная работа, ошибки и честные
          data gaps без синтетических метрик.
        </p>
      </div>
      <div className="hud-panel hud-card">
        <span className="mono-label">Current bottleneck</span>
        <strong>{bottleneck?.station ?? "none"}</strong>
        <span className="muted">{bottleneck ? `WIP ${bottleneck.wip_count}` : "No WIP"}</span>
      </div>
    </section>
  );
}
