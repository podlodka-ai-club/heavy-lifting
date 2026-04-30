import type { FactoryStation } from "../../api";

type FactoryRoutesProps = {
  stations: FactoryStation[];
  prefersReducedMotion: boolean;
};

export function FactoryRoutes({ stations, prefersReducedMotion }: FactoryRoutesProps) {
  const stationsWithWip = new Set(
    stations.filter((station) => station.wip_count > 0).map((station) => station.name)
  );

  return (
    <svg
      className="factory-routes"
      viewBox="0 0 1000 620"
      role="img"
      aria-label="Factory handoff routes"
    >
      <path className="handoff-route route-fetch" d="M500 108 C410 168 285 238 178 334" />
      <path className="handoff-route route-execute" d="M500 108 C470 222 426 316 358 410" />
      <path className="handoff-route route-pr_feedback" d="M500 108 C574 224 642 316 730 408" />
      <path className="handoff-route route-deliver" d="M500 108 C626 170 746 248 852 342" />

      {stationsWithWip.has("fetch") ? (
        <circle
          className="payload-marker payload-fetch"
          cx={prefersReducedMotion ? 178 : undefined}
          cy={prefersReducedMotion ? 334 : undefined}
          r="8"
          aria-label="fetch payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="9s" repeatCount="indefinite" path="M500 108 C410 168 285 238 178 334" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("execute") ? (
        <circle
          className="payload-marker payload-execute"
          cx={prefersReducedMotion ? 358 : undefined}
          cy={prefersReducedMotion ? 410 : undefined}
          r="9"
          aria-label="execute payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="7s" repeatCount="indefinite" path="M500 108 C470 222 426 316 358 410" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("pr_feedback") ? (
        <circle
          className="payload-marker payload-pr_feedback"
          cx={prefersReducedMotion ? 730 : undefined}
          cy={prefersReducedMotion ? 408 : undefined}
          r="8"
          aria-label="pr feedback payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="8s" repeatCount="indefinite" path="M500 108 C574 224 642 316 730 408" />
          )}
        </circle>
      ) : null}
      {stationsWithWip.has("deliver") ? (
        <circle
          className="payload-marker payload-deliver"
          cx={prefersReducedMotion ? 852 : undefined}
          cy={prefersReducedMotion ? 342 : undefined}
          r="8"
          aria-label="deliver payload marker"
        >
          {prefersReducedMotion ? null : (
            <animateMotion dur="10s" repeatCount="indefinite" path="M500 108 C626 170 746 248 852 342" />
          )}
        </circle>
      ) : null}
    </svg>
  );
}
