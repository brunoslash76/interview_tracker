import type { ScanStatus } from "../types";

export const idleScan: ScanStatus = {
  state: "idle",
  phase: "idle",
  current: 0,
  total: null,
};

export const runningScheduledScan: ScanStatus = {
  state: "running",
  phase: "extracting",
  source: "scheduled",
  run_id: "run-scheduled-1",
  current: 2,
  total: 5,
  elapsed_seconds: 12,
};

export const failedScan: ScanStatus = {
  state: "failed",
  phase: "failed",
  source: "dashboard",
  run_id: "run-failed-1",
  error: "Claude extraction failed",
  current: 1,
  total: 3,
};
