import { ThemeButton } from "./ThemeButton";

export function Header({
  connected,
  settings = false,
  onScan,
  dashboardHref = "/dashboard",
  settingsHref = "/settings",
}: {
  connected: boolean;
  settings?: boolean;
  onScan?: () => void;
  dashboardHref?: string;
  settingsHref?: string;
}) {
  return (
    <header className="top">
      <div>
        <h1>
          <span className={`live-dot ${connected ? "" : "offline"}`} />
          Interview Tracker
        </h1>
        <p className="muted">{connected ? "Live connection active" : "Reconnecting to local app…"}</p>
      </div>
      <nav>
        {onScan && (
          <button type="button" className="primary" onClick={onScan}>
            Scan Gmail now
          </button>
        )}
        <a className="pill-button" href={settings ? dashboardHref : settingsHref}>
          {settings ? "Dashboard" : "Settings"}
        </a>
        <ThemeButton />
      </nav>
    </header>
  );
}
