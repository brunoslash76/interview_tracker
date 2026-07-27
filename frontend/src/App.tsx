import { Suspense, lazy, useEffect, useState } from "react";
import { useLiveApp } from "./useLiveApp";
import { LoadingScreen } from "./components/LoadingScreen";
import { ScanActivity } from "./components/ScanActivity";
import { Toasts } from "./components/Toasts";
import "./styles.css";

const Dashboard = lazy(() =>
  import("./components/Dashboard").then((module) => ({ default: module.Dashboard })),
);
const SettingsPage = lazy(() =>
  import("./components/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);

export default function App() {
  const live = useLiveApp();
  const [scanOpen, setScanOpen] = useState(() => sessionStorage.getItem("scan-minimized") !== "true");
  const running = live.scan.state === "running";

  useEffect(() => {
    sessionStorage.setItem("scan-minimized", String(!scanOpen));
  }, [scanOpen]);

  useEffect(() => {
    if (running && live.scan.source === "dashboard") setScanOpen(true);
    if (running && live.scan.source && live.scan.source !== "dashboard") setScanOpen(false);
    if (live.scan.state === "succeeded") setScanOpen(false);
  }, [running, live.scan.run_id, live.scan.source, live.scan.state]);

  async function startScan() {
    setScanOpen(true);
    try {
      await live.startScan();
    } catch {
      /* toast/status arrives from connection */
    }
  }

  if (!live.snapshot) return <LoadingScreen />;

  const path = location.pathname;
  const route = path.startsWith("/settings") ? (
    <SettingsPage settings={live.snapshot.settings} save={live.saveSettings} connected={live.connected} />
  ) : (
    <Dashboard
      records={live.snapshot.dashboard.records}
      generatedAt={live.snapshot.dashboard.generated_at}
      connected={live.connected}
      onScan={startScan}
    />
  );

  return (
    <>
      <Suspense fallback={<LoadingScreen />}>{route}</Suspense>
      <ScanActivity
        scan={live.scan}
        open={scanOpen && (running || live.scan.state === "failed")}
        setOpen={setScanOpen}
      />
      <Toasts items={live.toasts} dismiss={live.dismissToast} />
    </>
  );
}
