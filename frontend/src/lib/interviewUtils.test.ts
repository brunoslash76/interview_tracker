import { describe, expect, it } from "vitest";
import { sampleInterviews } from "../fixtures/interviews";
import {
  ageDays,
  computeStats,
  dateValue,
  formatDate,
  needsAction,
  rejected,
  upcomingDays,
} from "./interviewUtils";

describe("interviewUtils", () => {
  it("formats invalid dates as em dash", () => {
    expect(formatDate("not-a-date")).toBe("—");
    expect(dateValue("")).toBeNull();
  });

  it("detects rejection and action cues", () => {
    const active = sampleInterviews[0];
    expect(rejected(active)).toBe(false);
    expect(needsAction(active, new Date("2026-07-25T12:00:00Z"))).toBe(true);
    expect(
      needsAction({ company: "X", status: "Rejected", next_steps: "Calendly" }),
    ).toBe(false);
    expect(
      needsAction({ company: "X", status: "Active", next_steps: "Please respond to schedule" }),
    ).toBe(true);
  });

  it("formats valid dates", () => {
    expect(formatDate("2026-07-01T12:00:00Z")).toMatch(/2026/);
  });

  it("treats stale quiet records in stats", () => {
    const now = new Date("2026-07-25T12:00:00Z");
    expect(upcomingDays(sampleInterviews[0], now)).toBe(7);
    const stats = computeStats(sampleInterviews, now);
    expect(stats.total).toBe(3);
    expect(stats.offers).toBe(1);
    expect(ageDays(sampleInterviews[2], now.getTime())).toBeGreaterThan(14);
  });
});
