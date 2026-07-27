import type { Interview } from "../types";

export const sampleInterviews: Interview[] = [
  {
    thread_id: "t1",
    company: "Acme",
    position: "Engineer",
    stage: "Phone Screen",
    status: "Scheduled",
    interview_datetime: "2026-08-01T15:00:00Z",
    last_email_date: "2026-07-20T10:00:00Z",
    next_steps: "Book interview slot via Calendly",
  },
  {
    thread_id: "t2",
    company: "Bravo",
    stage: "Offer",
    status: "Offer Received",
    last_email_date: "2026-07-18T09:00:00Z",
  },
  {
    thread_id: "t3",
    company: "Quiet Co",
    stage: "Initial Contact",
    status: "Active",
    last_email_date: "2026-06-01T09:00:00Z",
  },
];
