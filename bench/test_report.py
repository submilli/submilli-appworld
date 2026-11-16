"""Reporting regressions. Run with python -m unittest discover -s bench -p 'test_*.py'."""

import contextlib
import copy
import io
import unittest
from unittest.mock import patch

import report


def records():
    return {
        ("claude-haiku", arm): [[{
            "task_id": "example_1", "model": "claude-haiku", "arm": arm,
            "evaluation": {"success": True}, "agent_seconds": 1, "wall_seconds": 1,
            "usage": {"model_calls": 1},
            "transcript": [{"type": "ai", "usage": {"input_tokens": 10000, "output_tokens": 1000}}],
        }]]
        for arm in report.ARMS
    }


class ReportTests(unittest.TestCase):
    def test_empty_subset_is_not_reported_as_zero_success(self):
        data = records()
        self.assertNotIn("Haiku", report.subset_table(data, lambda _: False, "empty"))
        for metric in ("cost", "time", "success"):
            with self.subTest(metric=metric):
                self.assertNotIn("Haiku", report.lead_table(data, lambda _: False, metric))

    def test_missing_transcript_has_missing_cells_not_fake_measurements(self):
        data = records()
        del data[("claude-haiku", "tools")][0][0]["transcript"]
        row = report.subset_table(data, lambda _: True, "partial").splitlines()[-1]
        self.assertEqual(row.count("–"), 3)
        self.assertIn("100.0%", row)
        self.assertNotIn("Haiku", report.lead_table(data, lambda _: True))

    def test_crashed_only_runs_do_not_crash_report_sections(self):
        data = records()
        for groups in data.values():
            run = groups[0][0]
            del run["transcript"]
            run["evaluation"] = {"success": False}
            run["crash"] = "authentication failed"
        self.assertNotIn("Haiku", report.subset_table(data, lambda _: True, "failed"))
        self.assertNotIn("Haiku", report.lead_table(data, lambda _: True))
        self.assertNotIn("Haiku", report.code_use_table(data))

    def test_zero_baselines_do_not_divide_by_zero(self):
        data = records()
        for groups in data.values():
            run = groups[0][0]
            run["transcript"] = []
            run["agent_seconds"] = 0
        for metric in ("cost", "time"):
            with self.subTest(metric=metric):
                self.assertIn("tied with", report.lead_table(data, lambda _: True, metric))
        self.assertNotIn("Haiku", report.code_use_table(data))
        data[("claude-haiku", "submilli")] = copy.deepcopy(records()[("claude-haiku", "submilli")])
        for metric in ("cost", "time"):
            with self.subTest(metric=metric):
                self.assertIn("zero baseline", report.lead_table(data, lambda _: True, metric))
        self.assertIn("zero baseline", report.margins_table(data))

    def test_missing_round_is_an_actionable_error(self):
        with patch("sys.argv", ["report.py", "--submilli", "missing", "--tool-calling", "missing"]), \
                patch.object(report, "load_runs", return_value={}), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as raised:
                report.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("no run records found", error.getvalue())


if __name__ == "__main__":
    unittest.main()
