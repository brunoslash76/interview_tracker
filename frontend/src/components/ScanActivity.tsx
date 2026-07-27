import type { ScanStatus } from "../types";
import { SCAN_PHASE_LABELS } from "../lib/interviewUtils";

export function ScanActivity({
  scan,
  open,
  setOpen,
}: {
  scan: ScanStatus;
  open: boolean;
  setOpen: (value: boolean) => void;
}) {
  const running = scan.state === "running";
  const determinate = running && typeof scan.total === "number";
  const total = scan.total || 0;
  const current = scan.current || 0;
  const percent =
    total === 0
      ? scan.phase === "discovery"
        ? 0
        : 100
      : Math.min(100, Math.round((current / total) * 100));

  if (!running && !open) return null;
  if (running && !open) {
    return (
      <button type="button" className="activity-chip" onClick={() => setOpen(true)}>
        <span className="spinner" /> {determinate ? `${current}/${total}` : "Scanning…"}
      </button>
    );
  }
  if (!open) return null;

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => event.currentTarget === event.target && setOpen(false)}
    >
      <section className="scan-modal" role="dialog" aria-modal="true" aria-label="Gmail scan progress">
        <header>
          <div>
            <h2>{scan.source === "scheduled" ? "Scheduled Gmail scan" : "Reading your Gmail"}</h2>
            <p>{SCAN_PHASE_LABELS[scan.phase] || scan.phase}</p>
          </div>
          <button type="button" className="icon-button" aria-label="Minimize scan" onClick={() => setOpen(false)}>
            —
          </button>
        </header>
        <div
          className={`progress ${determinate ? "" : "indeterminate"}`}
          role="progressbar"
          aria-valuenow={determinate ? percent : undefined}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <i style={determinate ? { width: `${percent}%` } : undefined} />
        </div>
        <div className="scan-meta">
          <strong>{determinate ? `${current} of ${total} threads` : "Discovering threads…"}</strong>
          <span>{Math.floor(scan.elapsed_seconds || 0)}s</span>
        </div>
        {scan.thread_id && <p className="muted">Processing thread {scan.thread_id.slice(0, 12)}…</p>}
        {scan.state === "failed" && <p className="error">{scan.error || "The scan failed."}</p>}
        <p className="muted">You can minimize this window and keep using the dashboard.</p>
        <footer>
          <button type="button" className="secondary" onClick={() => setOpen(false)}>
            {running ? "Minimize" : "Close"}
          </button>
        </footer>
      </section>
    </div>
  );
}
