import { useEffect, useRef, useState } from "react";

import type { RetroEntry, RetroTag } from "../../api";
import { listRetroEntries, listRetroTags } from "../../api";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatDateTime } from "../../lib/formatters";
import "./retro.css";

/* ─── Severity helpers ───────────────────────────────────────────────────── */

type SeverityTone = "error" | "warning" | "info";

const SEVERITY_ORDER: SeverityTone[] = ["error", "warning", "info"];

function normalizeSeverity(severity: string): SeverityTone {
  if (severity === "error" || severity === "critical") return "error";
  if (severity === "warning") return "warning";
  return "info";
}

function dominantSeverity(counts: Record<string, number>): SeverityTone {
  const normalizedCounts = SEVERITY_ORDER.reduce<Record<SeverityTone, number>>(
    (acc, severity) => ({ ...acc, [severity]: 0 }),
    { error: 0, warning: 0, info: 0 }
  );
  for (const [severity, count] of Object.entries(counts)) {
    normalizedCounts[normalizeSeverity(severity)] += count;
  }

  return SEVERITY_ORDER.reduce<SeverityTone>((dominant, severity) => {
    if (normalizedCounts[severity] > normalizedCounts[dominant]) return severity;
    return dominant;
  }, "info");
}

function severityColor(severity: string): string {
  const tone = normalizeSeverity(severity);
  if (tone === "error") return "var(--red)";
  if (severity === "warning") return "var(--orange)";
  if (severity === "info") return "var(--cyan)";
  return "var(--cyan)";
}

function tagFontSize(count: number, maxCount: number): number {
  if (maxCount <= 1) return 1.2;
  const ratio = Math.log(count + 1) / Math.log(maxCount + 1);
  return 0.85 + ratio * 1.7;
}

function severityChips(counts: Record<string, number>): Array<[SeverityTone, number]> {
  const normalizedCounts: Record<SeverityTone, number> = {
    error: 0,
    warning: 0,
    info: 0,
  };
  for (const [severity, count] of Object.entries(counts)) {
    normalizedCounts[normalizeSeverity(severity)] += count;
  }
  return SEVERITY_ORDER.map(severity => [severity, normalizedCounts[severity]]);
}

/* ─── Page ───────────────────────────────────────────────────────────────── */

export function RetroPage() {
  const [tags, setTags] = useState<RetroTag[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [error, setError] = useState("");
  const [selectedTag, setSelectedTag] = useState<RetroTag | null>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    listRetroTags()
      .then(data => { if (!cancelled) { setTags(data); setLoadState("loaded"); } })
      .catch(e => { if (!cancelled) { setLoadState("error"); setError(e instanceof Error ? e.message : "Ошибка загрузки"); } });
    return () => { cancelled = true; };
  }, []);

  const maxCount = tags.length > 0 ? Math.max(...tags.map(tag => tag.count)) : 1;
  const totalEntries = tags.reduce((s, t) => s + t.count, 0);
  const errorCount = tags.reduce(
    (s, t) => s + (t.severity_counts.error ?? 0) + (t.severity_counts.critical ?? 0),
    0
  );

  return (
    <main className="page rt-page">
      <section className="f2-hud rt-hud" aria-label="Retro overview">
        <div className="hud-panel">
          <p className="eyebrow">heavy-lifting · ретроспектива · агрегат боли</p>
          <h1>
            <span className="rt-hero">{totalEntries}</span>
            <span className="rt-hero-label"> зафиксированных болей</span>
          </h1>
          <p className="intro">
            Каждый тег — паттерн отказа. Размер — частота. Цвет — severity.
          </p>
        </div>
        <div className="hud-panel hud-card rt-kpi-card">
          <div className="rt-kpi">
            <span className="mono-label">Теги</span>
            <strong className="rt-kpi-val">{tags.length}</strong>
          </div>
          <div className="rt-kpi">
            <span className="mono-label">Errors</span>
            <strong className="rt-kpi-val" style={{ color: "var(--red)" }}>{errorCount}</strong>
          </div>
        </div>
      </section>

      {loadState === "loading" && <p className="factory-loading">Загружаю боль системы...</p>}
      {error && <p className="status-error" role="alert">{error}</p>}

      {loadState === "loaded" && tags.length === 0 && (
        <div className="rt-empty">
          <p className="muted">Нет данных. Агенты пока не жаловались.</p>
        </div>
      )}

      {tags.length > 0 && (
        <>
          <PainCloud
            maxCount={maxCount}
            reduced={reduced}
            selectedTag={selectedTag?.tag ?? null}
            tags={tags}
            onSelect={t => setSelectedTag(prev => prev?.tag === t.tag ? null : t)}
          />
          {selectedTag && (
            <TagDetailPanel
              key={selectedTag.tag}
              tag={selectedTag}
              onClose={() => setSelectedTag(null)}
            />
          )}
        </>
      )}
    </main>
  );
}

/* ─── Pain Cloud ─────────────────────────────────────────────────────────── */

function PainCloud({
  tags,
  maxCount,
  selectedTag,
  reduced,
  onSelect,
}: {
  tags: RetroTag[];
  maxCount: number;
  selectedTag: string | null;
  reduced: boolean;
  onSelect: (t: RetroTag) => void;
}) {
  return (
    <section className="rt-cloud-wrap" aria-label="Pain tag cloud">
      {!reduced && <div aria-hidden className="rt-radar-sweep" />}
      <ul className="rt-cloud">
        {tags.map((tag, i) => {
          const severity = dominantSeverity(tag.severity_counts);
          const color = severityColor(severity);
          const size = tagFontSize(tag.count, maxCount);
          const isSelected = selectedTag === tag.tag;
          const rotation = ((i * 7) % 11) - 5;
          return (
            <li key={tag.tag} className="rt-tag-item">
              <button
                aria-label={`${tag.tag}: ${tag.count} entries, severity: ${severity}`}
                aria-pressed={isSelected}
                className={`rt-tag rt-sev-${severity}${isSelected ? " rt-tag-active" : ""}`}
                style={{
                  fontSize: `${size}rem`,
                  "--tag-color": color,
                  "--tag-rot": `${rotation}deg`,
                } as React.CSSProperties}
                type="button"
                onClick={() => onSelect(tag)}
              >
                {tag.tag}
                <span aria-hidden className="rt-tag-count">{tag.count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ─── Tag Detail Panel ───────────────────────────────────────────────────── */

function TagDetailPanel({ tag, onClose }: { tag: RetroTag; onClose: () => void }) {
  const [entries, setEntries] = useState<RetroEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [entryError, setEntryError] = useState("");
  const [instruction, setInstruction] = useState("");
  const [sent, setSent] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setEntryError("");
    listRetroEntries(tag.tag, 10)
      .then(data => {
        if (!cancelled) {
          setEntries(data);
          setLoading(false);
        }
      })
      .catch(e => {
        if (!cancelled) {
          setEntries([]);
          setEntryError(e instanceof Error ? e.message : "Не удалось загрузить записи");
          setLoading(false);
        }
      });
    textareaRef.current?.focus();
    return () => { cancelled = true; };
  }, [tag.tag]);

  const severity = dominantSeverity(tag.severity_counts);
  const color = severityColor(severity);

  function handleSend() {
    if (!instruction.trim()) return;
    setSent(true);
    setInstruction("");
  }

  return (
    <section
      className="rt-panel hud-panel"
      aria-label={`Details: ${tag.tag}`}
      style={{ "--tag-color": color } as React.CSSProperties}
    >
      <div className="rt-panel-header">
        <div>
          <p className="eyebrow" style={{ color }}>Паттерн боли · {severity}</p>
          <h2 className="rt-panel-tag">{tag.tag}</h2>
        </div>
        <button aria-label="Закрыть" className="rt-close-btn" type="button" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="rt-panel-body">
        <div className="rt-panel-stats">
          <StatChip label="Всего" value={tag.count} />
          <StatChip label="Задач" value={tag.affected_tasks_count} />
          {severityChips(tag.severity_counts)
            .filter(([, cnt]) => cnt > 0)
            .map(([sev, cnt]) => (
              <StatChip
                key={sev}
                label={sev}
                tone={sev}
                value={cnt}
              />
            ))}
          <StatChip label="Первый раз" value={formatDateTime(tag.first_seen).split(",")[0]} />
          <StatChip label="Последний" value={formatDateTime(tag.last_seen).split(",")[0]} />
        </div>

        <div className="rt-panel-cols">
          <div className="rt-entries-col">
            <p className="eyebrow">Последние записи</p>
            {loading && <p className="muted">Загружаю...</p>}
            {entryError && <p className="status-error compact" role="alert">{entryError}</p>}
            {!loading && entries.length === 0 && <p className="muted">Нет записей</p>}
            <div className="rt-entries">
              {entries.map(e => <EntryRow entry={e} key={e.id} />)}
            </div>
          </div>

          <div className="rt-action-col">
            <p className="eyebrow">Инструкция мета-агенту</p>
            <p className="muted rt-action-hint">
              Локальный черновик, backend endpoint не вызывается.
            </p>
            <textarea
              ref={textareaRef}
              className="rt-textarea"
              placeholder={`Когда встречается "${tag.tag}", агент должен...`}
              rows={5}
              value={instruction}
              onChange={e => { setInstruction(e.target.value); setSent(false); }}
            />
            <div className="rt-action-footer">
              {sent && <span className="status-inline-ok">Черновик сохранен локально</span>}
              <button
                className="rt-send-btn"
                disabled={!instruction.trim()}
                type="button"
                onClick={handleSend}
              >
                Сохранить локально
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: SeverityTone;
}) {
  const color = tone ? severityColor(tone) : undefined;
  return (
    <div className="rt-stat-chip">
      <span className="metric-label">{label}</span>
      <strong className="metric-value" style={{ color }}>{value}</strong>
    </div>
  );
}

function EntryRow({ entry }: { entry: RetroEntry }) {
  const color = severityColor(entry.severity);
  const tone = normalizeSeverity(entry.severity);
  return (
    <div className={`rt-entry-row rt-entry-${tone}`}>
      <div className="rt-entry-header">
        <span className="rt-entry-sev" style={{ color }}>{tone}</span>
        <span className="muted rt-entry-meta">
          {entry.task_type} · {formatDateTime(entry.created_at)}
        </span>
      </div>
      <p className="rt-entry-msg">{entry.message}</p>
      {entry.suggested_action && (
        <p className="rt-entry-action">→ {entry.suggested_action}</p>
      )}
    </div>
  );
}
