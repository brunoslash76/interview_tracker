export type Interview = {
  id?: number;
  thread_id?: string;
  company: string;
  position?: string | null;
  stage?: string | null;
  status?: string | null;
  interview_datetime?: string | null;
  last_email_date?: string | null;
  first_seen?: string | null;
  next_steps?: string | null;
  notes?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  meeting_link?: string | null;
  last_updated?: string | null;
};

export type DashboardPayload = {
  records: Interview[];
  generated_at: string;
  summary?: Record<string, unknown> | null;
  stats?: Record<string, number>;
};

export type Settings = {
  email: string;
  scan_times: string[];
  max_scan_times: number;
};

export type ScanStatus = {
  state: "idle" | "running" | "succeeded" | "failed";
  phase: string;
  source?: "dashboard" | "tray" | "scheduled" | "manual";
  run_id?: string | null;
  sequence?: number;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  elapsed_seconds?: number;
  current?: number;
  total?: number | null;
  thread_id?: string | null;
  new_count?: number;
  updated_count?: number;
  extracted_count?: number | null;
  error?: string | null;
};

export type AppSnapshot = {
  dashboard: DashboardPayload;
  settings: Settings;
  scan: ScanStatus;
};

export type ServerMessage = {
  version: 1;
  type: string;
  request_id?: string;
  payload: unknown;
};
