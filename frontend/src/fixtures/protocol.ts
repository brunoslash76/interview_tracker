/** WebSocket event names aligned with bin/local_server.py broadcasts and replies. */
export const WS_EVENTS = {
  snapshot: "app.snapshot",
  snapshotRequest: "snapshot.request",
  dashboardUpdated: "dashboard.updated",
  settingsUpdated: "settings.updated",
  scanStarted: "scan.started",
  scanProgress: "scan.progress",
  scanCompleted: "scan.completed",
  scanFailed: "scan.failed",
  scanStartCommand: "scan.start",
  settingsSave: "settings.save",
  error: "error",
  heartbeat: "heartbeat",
} as const;

export type WsEventName = (typeof WS_EVENTS)[keyof typeof WS_EVENTS];
