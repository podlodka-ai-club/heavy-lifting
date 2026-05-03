import type { KnownFactoryStationName } from "../../api";

type StationMeta = { label: string; title: string; shortLabel: string };

export const stationMeta: Record<
  KnownFactoryStationName,
  StationMeta
> = {
  fetch: { label: "FETCH", title: "tracker intake", shortLabel: "fetch" },
  execute: { label: "EXECUTE", title: "triage · runner · workspace", shortLabel: "execute" },
  pr_feedback: { label: "PR_FEEDBACK", title: "review response", shortLabel: "pr feedback" },
  tracker_feedback: {
    label: "TRACKER_FEEDBACK",
    title: "tracker response",
    shortLabel: "tracker feedback"
  },
  deliver: { label: "DELIVER", title: "tracker delivery", shortLabel: "deliver" }
};

export function getStationMeta(name: string): StationMeta {
  if (name in stationMeta) {
    return stationMeta[name as KnownFactoryStationName];
  }

  const label = name.replaceAll("_", " ").toUpperCase();
  return {
    label,
    title: `${name.replaceAll("_", " ")} station`,
    shortLabel: name.replaceAll("_", " ")
  };
}
