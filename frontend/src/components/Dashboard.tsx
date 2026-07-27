import { useEffect, useMemo, useState } from "react";
import type { Interview } from "../types";
import {
  STAGES,
  computeStats,
  dateValue,
  formatDate,
  needsAction,
} from "../lib/interviewUtils";
import { Header } from "./Header";

export function Dashboard({
  records,
  generatedAt,
  connected,
  onScan,
  settingsHref = "/settings",
}: {
  records: Interview[];
  generatedAt: string;
  connected: boolean;
  onScan: () => void;
  settingsHref?: string;
}) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const statuses = useMemo(
    () => [...new Set(records.map((item) => item.status || "").filter(Boolean))].sort(),
    [records],
  );
  const filtered = useMemo(
    () =>
      records
        .filter(
          (item) =>
            !query || `${item.company} ${item.position || ""}`.toLowerCase().includes(query.toLowerCase()),
        )
        .filter((item) => !stage || item.stage === stage)
        .filter((item) => !status || item.status === status)
        .sort(
          (a, b) =>
            (dateValue(b.last_email_date)?.getTime() || 0) - (dateValue(a.last_email_date)?.getTime() || 0),
        ),
    [records, query, stage, status],
  );
  useEffect(() => setPage(1), [query, stage, status, perPage]);
  const pages = Math.max(1, Math.ceil(filtered.length / perPage));
  const visible = filtered.slice((page - 1) * perPage, page * perPage);
  const stats = computeStats(records);

  return (
    <main className="wrap">
      <Header connected={connected} onScan={onScan} settingsHref={settingsHref} />
      <p className="generated">Data updated {generatedAt}</p>
      <section className="stats" aria-label="Summary statistics">
        {Object.entries(stats).map(([key, value]) => (
          <article className="stat" key={key}>
            <strong>{value}</strong>
            <span>{key}</span>
          </article>
        ))}
      </section>
      <section className="panel pipeline">
        <h2>Pipeline</h2>
        <div>
          {STAGES.map((item) => (
            <button
              type="button"
              key={item}
              className={stage === item ? "selected" : ""}
              aria-label={`${item}, ${records.filter((record) => record.stage === item).length} opportunities`}
              aria-pressed={stage === item}
              onClick={() => setStage(stage === item ? "" : item)}
            >
              <strong>{records.filter((record) => record.stage === item).length}</strong>
              <span>{item}</span>
            </button>
          ))}
        </div>
      </section>
      <section className="panel controls">
        <input
          aria-label="Search"
          placeholder="Company or position…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select aria-label="Stage" value={stage} onChange={(event) => setStage(event.target.value)}>
          <option value="">All stages</option>
          {STAGES.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <select aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">All statuses</option>
          {statuses.map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setQuery("");
            setStage("");
            setStatus("");
          }}
        >
          Clear
        </button>
      </section>
      <section className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Company & position</th>
              <th scope="col">Next steps</th>
              <th scope="col">Interview</th>
              <th scope="col">Last email</th>
              <th scope="col">Stage</th>
              <th scope="col">Contact</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((item, index) => (
              <tr key={item.thread_id || item.id || index} className={needsAction(item) ? "action" : ""}>
                <td>
                  <strong>{item.company}</strong>
                  <small>{item.position || "—"}</small>
                </td>
                <td>
                  {item.next_steps || "—"}
                  {item.meeting_link && (
                    <a className="join" href={item.meeting_link}>
                      Join meeting
                    </a>
                  )}
                </td>
                <td>{formatDate(item.interview_datetime)}</td>
                <td>{formatDate(item.last_email_date)}</td>
                <td>
                  <span className="badge">{item.stage || "—"}</span>
                </td>
                <td>{item.contact_name || item.contact_email || "—"}</td>
                <td>{item.status || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!visible.length && <div className="empty">No opportunities match these filters.</div>}
      </section>
      <footer className="pager">
        <span>
          Showing {visible.length ? (page - 1) * perPage + 1 : 0}–{Math.min(page * perPage, filtered.length)} of{" "}
          {filtered.length}
        </span>
        <select
          aria-label="Rows per page"
          value={perPage}
          onChange={(event) => setPerPage(Number(event.target.value))}
        >
          {[5, 10, 20, 50].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <button type="button" className="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          Previous
        </button>
        <span>
          {page} / {pages}
        </span>
        <button type="button" className="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
          Next
        </button>
      </footer>
    </main>
  );
}
