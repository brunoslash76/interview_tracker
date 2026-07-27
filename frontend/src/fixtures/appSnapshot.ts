import type { AppSnapshot } from "../types";
import { sampleInterviews } from "./interviews";
import { idleScan, runningScheduledScan } from "./scanStatus";

export function makeSnapshot(overrides: Partial<AppSnapshot> = {}): AppSnapshot {
  return {
    dashboard: {
      records: sampleInterviews,
      generated_at: "just now",
      summary: null,
      stats: undefined,
    },
    settings: {
      email: "",
      scan_times: ["09:00", "20:00"],
      max_scan_times: 5,
    },
    scan: idleScan,
    ...overrides,
  };
}

export const defaultSnapshot = makeSnapshot({ scan: runningScheduledScan });
