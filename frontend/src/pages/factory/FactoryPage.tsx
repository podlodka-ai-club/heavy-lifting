import { useEffect, useState } from "react";

import { FactorySnapshot, getFactorySnapshot } from "../../api";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { DataGapsPanel } from "./DataGapsPanel";
import { FactoryHud } from "./FactoryHud";
import { FactoryMap } from "./FactoryMap";
import { FactoryTelemetry } from "./FactoryTelemetry";

type LoadState = "idle" | "loading" | "loaded" | "error";

export function FactoryPage() {
  const [snapshot, setSnapshot] = useState<FactorySnapshot | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [error, setError] = useState<string>("");
  const prefersReducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    let cancelled = false;

    async function loadFactory() {
      setLoadState("loading");
      setError("");

      try {
        const loadedSnapshot = await getFactorySnapshot();

        if (cancelled) {
          return;
        }

        setSnapshot(loadedSnapshot);
        setLoadState("loaded");
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setLoadState("error");
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить factory");
      }
    }

    void loadFactory();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page factory-page">
      <FactoryHud bottleneck={snapshot?.bottleneck ?? null} />

      {loadState === "loading" ? <p className="factory-loading">Загрузка factory...</p> : null}
      {error ? (
        <p className="status-error" role="alert">
          {error}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <FactoryTelemetry snapshot={snapshot} />
          <FactoryMap prefersReducedMotion={prefersReducedMotion} snapshot={snapshot} />
          <DataGapsPanel dataGaps={snapshot.data_gaps} />
        </>
      ) : null}
    </main>
  );
}
