"""Unit tests for bin/menubar_logic.py."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tests.support import load_bin_module


class MenubarLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logic = load_bin_module("menubar_logic")

    def test_is_rejected_detects_rejection_phrases(self):
        self.assertTrue(self.logic.is_rejected({"status": "Rejected after onsite"}))
        self.assertTrue(self.logic.is_rejected({"status": "Candidate withdraw"}))
        self.assertTrue(self.logic.is_rejected({"status": "Declined offer"}))
        self.assertFalse(self.logic.is_rejected({"status": "Active"}))

    def test_upcoming_records_filters_sorts_and_limits(self):
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        records = [
            {
                "company": "Later",
                "status": "Active",
                "interview_datetime": "2026-06-10T09:00:00+00:00",
            },
            {
                "company": "Rejected Future",
                "status": "Rejected",
                "interview_datetime": "2026-06-15T09:00:00+00:00",
            },
            {
                "company": "Soon",
                "status": "Active",
                "interview_datetime": "2026-06-02T09:00:00Z",
            },
            {
                "company": "Past",
                "status": "Active",
                "interview_datetime": "2026-05-01T09:00:00+00:00",
            },
        ]
        upcoming = self.logic.upcoming_records(records, now=now, limit=2)
        self.assertEqual(len(upcoming), 2)
        self.assertEqual(upcoming[0][1]["company"], "Soon")
        self.assertEqual(upcoming[1][1]["company"], "Later")

    def test_action_count_includes_upcoming_and_action_cues(self):
        now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        records = [
            {
                "status": "Active",
                "interview_datetime": "2026-06-05T09:00:00+00:00",
                "next_steps": "",
            },
            {
                "status": "Waiting",
                "interview_datetime": "",
                "next_steps": "Please complete the take-home by Friday",
            },
            {
                "status": "Rejected",
                "next_steps": "complete the form",
            },
            {
                "status": "Active",
                "interview_datetime": "2026-05-01T09:00:00+00:00",
                "next_steps": "book your calendly slot",
            },
        ]
        self.assertEqual(self.logic.action_count(records, now=now), 3)


if __name__ == "__main__":
    unittest.main()
