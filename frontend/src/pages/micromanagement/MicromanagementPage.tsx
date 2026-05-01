import { useEffect, useRef, useState } from "react";

import type { TaskRecord } from "../../api";
import { listTasks } from "../../api";
import { formatDateTime } from "../../lib/formatters";
import "./micromanagement.css";

const POLL_INTERVAL_MS = 3000;

/* ── Status helpers ─────────────────────────────────────────────────────── */

type StatusTone = "new" | "processing" | "done" | "failed";

function normalizeStatus(status: string): StatusTone {
  if (status === "processing" || status === "in_progress") return "processing";
  if (status === "done") return "done";
  if (status === "failed") return "failed";
  return "new";
}

function StatusBadge({ status }: { status: string }) {
  const tone = normalizeStatus(status);
  return (
    <span className={`mm-status status-${tone}`}>
      <span aria-hidden className="mm-status-dot" />
      {status}
    </span>
  );
}

/* ── Relative time ──────────────────────────────────────────────────────── */

function relativeSeconds(iso: string): number {
  return Math.round((Date.now() - new Date(iso).getTime()) / 1000);
}

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s ago`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm === 0 ? `${h}h ago` : `${h}h ${rm}m ago`;
}

/* ── Detail panel ───────────────────────────────────────────────────────── */

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="mm-detail-kv">
      <span className="mm-detail-key">{label}</span>
      <span className="mm-detail-val">{value}</span>
    </div>
  );
}

function MetadataBlock({ data, label }: { data: Record<string, unknown> | null; label: string }) {
  if (!data) return null;
  const json = JSON.stringify(data, null, 2);
  return (
    <div>
      <p className="mm-detail-section-label">{label}</p>
      <div className="mm-json-wrap">
        <pre className="mm-json">{json}</pre>
      </div>
    </div>
  );
}

function TaskDetail({ task }: { task: TaskRecord }) {
  const metadata = task.result_payload?.metadata as Record<string, unknown> | undefined;
  const hasMetadata = metadata && typeof metadata === "object" && Object.keys(metadata).length > 0;
  const contextClean = task.context
    ? Object.fromEntries(Object.entries(task.context).filter(([, v]) => v !== null))
    : null;

  return (
    <div className="mm-detail-inner">
      <div>
        <p className="mm-detail-section-label">Детали задачи</p>
        <div className="mm-detail-grid">
          <KV label="ID" value={task.id} />
          <KV label="Root ID" value={task.root_id} />
          <KV label="Parent ID" value={task.parent_id} />
          <KV label="Attempt" value={task.attempt} />
          <KV label="Workspace key" value={task.workspace_key} />
          <KV label="Repo ref" value={task.repo_ref} />
          <KV label="Branch" value={task.branch_name} />
          <KV label="Created" value={formatDateTime(task.created_at)} />
          <KV label="Updated" value={formatDateTime(task.updated_at)} />
          <KV
            label="PR"
            value={
              task.pr_url ? (
                <a href={task.pr_url} rel="noreferrer" target="_blank">
                  {task.pr_external_id ?? task.pr_url}
                </a>
              ) : null
            }
          />
        </div>
      </div>

      {task.error && (
        <div>
          <p className="mm-detail-section-label" style={{ color: "var(--red)" }}>Ошибка</p>
          <pre className="mm-json" style={{ color: "var(--red)" }}>{task.error}</pre>
        </div>
      )}

      {task.result_payload?.summary ? (
        <div>
          <p className="mm-detail-section-label">Summary</p>
          <p className="mm-detail-val">{String(task.result_payload.summary)}</p>
        </div>
      ) : null}

      {task.result_payload?.details ? (
        <div>
          <p className="mm-detail-section-label">Details</p>
          <pre className="mm-json">{String(task.result_payload.details)}</pre>
        </div>
      ) : null}

      {hasMetadata && (
        <MetadataBlock data={metadata as Record<string, unknown>} label="Result metadata" />
      )}

      {contextClean && Object.keys(contextClean).length > 0 && (
        <MetadataBlock data={contextClean} label="Context" />
      )}
    </div>
  );
}

/* ── Table row ──────────────────────────────────────────────────────────── */

function TaskRow({
  task,
  expanded,
  onToggle,
}: {
  task: TaskRecord;
  expanded: boolean;
  onToggle: () => void;
}) {
  const age = relativeSeconds(task.updated_at);
  const isActive = normalizeStatus(task.status) === "processing";
  const colSpan = 7;

  return (
    <>
      <tr
        aria-expanded={expanded}
        className={`mm-row-expandable${expanded ? " mm-row-expanded" : ""}`}
        onClick={onToggle}
      >
        <td className="mm-mono">{task.id}</td>
        <td>
          <span className="mm-type">{task.task_type}</span>
        </td>
        <td>
          <StatusBadge status={task.status} />
        </td>
        <td className="mm-dim">{task.tracker_name ?? "—"}</td>
        <td className="mm-dim">{task.external_parent_id ?? task.external_task_id ?? "—"}</td>
        <td className={isActive ? "mm-mono" : "mm-dim"} style={isActive ? { color: "var(--orange)" } : undefined}>
          {fmtAge(age)}
        </td>
        <td>
          {task.error ? (
            <span className="mm-error-cell" title={task.error}>
              {task.error}
            </span>
          ) : task.result_payload?.summary ? (
            <span className="mm-dim">{String(task.result_payload.summary).slice(0, 60)}</span>
          ) : (
            <span className="mm-dim">—</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="mm-detail-row">
          <td colSpan={colSpan}>
            <TaskDetail task={task} />
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export function MicromanagementPage() {
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [loadState, setLoadState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [secondsSinceRefresh, setSecondsSinceRefresh] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function fetchTasks(isInitial = false) {
    if (isInitial) setLoadState("loading");
    listTasks()
      .then(data => {
        const sorted = [...data].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
        );
        setTasks(sorted);
        setLastRefresh(new Date());
        setSecondsSinceRefresh(0);
        if (isInitial) setLoadState("loaded");
      })
      .catch(e => {
        if (isInitial) {
          setLoadState("error");
          setError(e instanceof Error ? e.message : "Не удалось загрузить задачи");
        }
      });
  }

  useEffect(() => {
    fetchTasks(true);
    intervalRef.current = setInterval(() => fetchTasks(), POLL_INTERVAL_MS);
    tickRef.current = setInterval(() => setSecondsSinceRefresh(s => s + 1), 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, []);

  const processing = tasks.filter(t => normalizeStatus(t.status) === "processing");
  const failed = tasks.filter(t => normalizeStatus(t.status) === "failed");
  const done = tasks.filter(t => normalizeStatus(t.status) === "done");

  return (
    <main className="page mm-page">
      <div className="mm-hud">
        <div>
          <p className="mm-hud-title">heavy-lifting · micromanagement</p>
          <h1 className="mm-hud-hero">{tasks.length}</h1>
          <p className="mm-hud-sub">задач всего · сортировка по активности</p>
        </div>
        <div className="mm-kpis">
          <div className="mm-kpi">
            <span className="mm-kpi-label">Active</span>
            <strong className={`mm-kpi-val${processing.length > 0 ? " pulse" : ""}`}>
              {processing.length}
            </strong>
          </div>
          <div className="mm-kpi">
            <span className="mm-kpi-label">Failed</span>
            <strong className="mm-kpi-val" style={failed.length > 0 ? { color: "var(--red)" } : undefined}>
              {failed.length}
            </strong>
          </div>
          <div className="mm-kpi">
            <span className="mm-kpi-label">Done</span>
            <strong className="mm-kpi-val" style={{ color: "var(--green)" }}>
              {done.length}
            </strong>
          </div>
        </div>
        {lastRefresh && (
          <span className="mm-refresh-badge">
            обновлено {secondsSinceRefresh}s назад
          </span>
        )}
      </div>

      {loadState === "loading" && <p className="mm-loading">Загрузка задач...</p>}
      {error && <p className="status-error" role="alert">{error}</p>}

      {loadState === "loaded" && tasks.length === 0 && (
        <div className="mm-empty">Нет задач. Система молчит.</div>
      )}

      {tasks.length > 0 && (
        <div className="mm-table-wrap">
          <table className="mm-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Tracker</th>
                <th>External ID</th>
                <th>Updated</th>
                <th>Summary / Error</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map(task => (
                <TaskRow
                  key={task.id}
                  expanded={expandedId === task.id}
                  task={task}
                  onToggle={() => setExpandedId(prev => prev === task.id ? null : task.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
