import type { Interview } from "../types";

export const STAGES = [
  "Initial Contact",
  "Phone Screen",
  "Technical Round",
  "Final Interview",
  "Offer",
] as const;

export function dateValue(raw?: string | null) {
  if (!raw) return null;
  const value = new Date(raw);
  return Number.isNaN(value.getTime()) ? null : value;
}

export function formatDate(raw?: string | null) {
  const value = dateValue(raw);
  return value
    ? value.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
    : "—";
}

export function rejected(record: Interview) {
  return /reject|withdraw|declin/i.test(record.status || "");
}

export function upcomingDays(record: Interview, now = new Date()) {
  const value = dateValue(record.interview_datetime);
  if (!value) return null;
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  value.setHours(0, 0, 0, 0);
  return Math.round((value.getTime() - today.getTime()) / 86_400_000);
}

export function needsAction(record: Interview, now = new Date()) {
  if (rejected(record)) return false;
  const days = upcomingDays(record, now);
  if (days !== null && days >= 0 && days <= 10) return true;
  return /take-?home|challenge|calendly|book |schedule your|incomplete|please respond|reply to|docusign|\bnda\b|reference/i.test(
    `${record.next_steps || ""} ${record.status || ""}`,
  );
}

export function ageDays(record: Interview, now = Date.now()) {
  const value = dateValue(record.last_email_date || record.first_seen);
  return value ? Math.floor((now - value.getTime()) / 86_400_000) : null;
}

export function computeStats(records: Interview[], now = new Date()) {
  return {
    total: records.length,
    action: records.filter((item) => needsAction(item, now)).length,
    upcoming: records.filter((item) => {
      const days = upcomingDays(item, now);
      return days !== null && days >= 0 && !rejected(item);
    }).length,
    offers: records.filter(
      (item) => item.stage === "Offer" || /offer/i.test(item.status || ""),
    ).length,
    quiet: records.filter((item) => (ageDays(item, now.getTime()) || 0) > 14 && !rejected(item)).length,
  };
}

export const SCAN_PHASE_LABELS: Record<string, string> = {
  starting: "Starting scanner",
  config: "Loading settings",
  discovery: "Finding matching Gmail threads",
  extracting: "Reading Gmail threads",
  merging: "Updating your dashboard",
  complete: "Complete",
  failed: "Scan failed",
};
