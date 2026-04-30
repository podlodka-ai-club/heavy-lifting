import type { FactoryStation } from "../../api";

export const stationMeta: Record<
  FactoryStation["name"],
  { label: string; title: string; shortLabel: string }
> = {
  fetch: { label: "FETCH", title: "tracker intake", shortLabel: "fetch" },
  execute: { label: "EXECUTE", title: "triage · runner · workspace", shortLabel: "execute" },
  pr_feedback: { label: "PR_FEEDBACK", title: "review response", shortLabel: "pr feedback" },
  deliver: { label: "DELIVER", title: "tracker delivery", shortLabel: "deliver" }
};
