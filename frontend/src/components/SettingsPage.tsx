import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Settings } from "../types";
import { Header } from "./Header";

export function SettingsPage({
  settings,
  save,
  connected,
  dashboardHref = "/dashboard",
}: {
  settings: Settings;
  save: (value: Pick<Settings, "email" | "scan_times">) => Promise<Settings>;
  connected: boolean;
  dashboardHref?: string;
}) {
  const [email, setEmail] = useState(settings.email || "");
  const [times, setTimes] = useState(settings.scan_times || []);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setEmail(settings.email || "");
    setTimes(settings.scan_times || []);
  }, [settings]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("Saving…");
    try {
      const saved = await save({ email: email.trim(), scan_times: times.filter(Boolean) });
      setEmail(saved.email);
      setTimes(saved.scan_times);
      setMessage("Saved. Scheduler updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <main className="wrap settings-page">
      <Header connected={connected} settings dashboardHref={dashboardHref} />
      <form className="panel settings-card" onSubmit={submit}>
        <h2>Scan settings</h2>
        <p className="muted">Configure daily Gmail scan times and an optional account involvement filter.</p>
        <label htmlFor="settings-email">Email filter</label>
        <input
          id="settings-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
        />
        <span>Daily scan times (max {settings.max_scan_times})</span>
        {times.map((time, index) => (
          <div className="time-row" key={`${index}-${time}`}>
            <input
              type="time"
              aria-label={`Scan time ${index + 1}`}
              value={time}
              onChange={(event) =>
                setTimes(times.map((item, i) => (i === index ? event.target.value : item)))
              }
            />
            <button type="button" className="danger" onClick={() => setTimes(times.filter((_, i) => i !== index))}>
              Remove
            </button>
          </div>
        ))}
        <div className="form-actions">
          <button
            type="button"
            className="secondary"
            disabled={times.length >= settings.max_scan_times}
            onClick={() => setTimes([...times, "09:00"])}
          >
            Add time
          </button>
          <button className="primary" disabled={!connected}>
            Save and apply schedule
          </button>
        </div>
        <p className="status" role="status">
          {message}
        </p>
      </form>
    </main>
  );
}
