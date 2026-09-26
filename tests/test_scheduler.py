from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_system as support
from test_system import Config, FakeSource, post
from xrss.scheduler import run_scheduled, select_account
from xrss.source import FetchError

START = datetime(2026, 9, 26, 0, 7, tzinfo=timezone.utc)


class SelectionTests(unittest.TestCase):
    def test_five_ten_twenty_accounts_rotate_without_starvation(self):
        for count in (1, 4, 5, 10, 20):
            accounts = [f"example_{i}" for i in range(count)]
            states, visits = {}, {a: [] for a in accounts}
            for slot in range(max(4, count) * 3):
                now = START + timedelta(minutes=15 * slot)
                selected, _ = select_account(accounts, states, now.isoformat())
                if selected:
                    visits[selected].append(now)
                    states[selected] = {"last_attempt": now.isoformat()}
            for times in visits.values():
                self.assertEqual(len(times), 3)
                self.assertEqual(times[1] - times[0], timedelta(minutes=max(60, count * 15)))

    def test_manual_and_delayed_runs_cannot_burst(self):
        accounts = [f"example_{i}" for i in range(20)]
        states, contacted = {}, []
        for minute in range(60):
            now = START + timedelta(minutes=minute)
            selected, _ = select_account(accounts, states, now.isoformat())
            if selected:
                contacted.append(minute)
                states[selected] = {"last_attempt": now.isoformat()}
        self.assertEqual(contacted, [0, 15, 30, 45])

    def test_cooldown_excludes_account_even_when_oldest(self):
        states = {"example_a": {"last_attempt": (START - timedelta(hours=5)).isoformat(),
                                 "next_request_at": (START + timedelta(hours=2)).isoformat()}}
        self.assertEqual(select_account(["example_a", "example_b"], states, START.isoformat())[0], "example_b")
        self.assertIsNone(select_account(["example_a"], states, START.isoformat())[0])
        self.assertEqual(select_account(["example_a"], states, (START + timedelta(hours=2)).isoformat())[0], "example_a")

    def test_removed_accounts_still_protect_global_gap_and_clock_skew(self):
        states = {"removed": {"last_attempt": START.isoformat()}}
        self.assertIsNone(select_account(["new_account"], states, START.isoformat())[0])
        self.assertIsNone(select_account(["new_account"], states, (START - timedelta(minutes=1)).isoformat())[0])
        self.assertEqual(select_account(["new_account"], states, (START + timedelta(minutes=15)).isoformat())[0], "new_account")

    def test_priority_is_attempt_not_success_and_ties_use_config_order(self):
        old = (START - timedelta(hours=3)).isoformat()
        older = (START - timedelta(hours=4)).isoformat()
        states = {"example_a": {"last_attempt": old, "last_success": older},
                  "example_b": {"last_attempt": older, "last_success": old}}
        self.assertEqual(select_account(["example_a", "example_b"], states, START.isoformat())[0], "example_b")
        self.assertEqual(select_account(["example_b", "example_a"], {}, START.isoformat())[0], "example_b")


class ScheduledRunnerTests(unittest.TestCase):
    setUp = support.RunnerTests.setUp

    def invoke(self, source, now=START, accounts=None):
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.root / "outputs"),
                                     "GITHUB_STEP_SUMMARY": str(self.root / "summary")}):
            return run_scheduled(Config(accounts or ["example_a", "example_b"]), source,
                                 self.data, self.output, "https://example.org", now=now.isoformat())

    def test_one_request_preserves_unselected_and_renders_all_accounts(self):
        a = FakeSource({"example_a": [post("1", author="example_a")]})
        self.assertEqual(self.invoke(a), 0)
        self.assertEqual(a.calls, ["example_a"])
        before = (self.data / "example_a.json").read_bytes()
        rss = (self.output / "feeds/example_a.xml").read_bytes()
        state = json.loads((self.data / "_meta/status.json").read_text(encoding="utf-8"))["example_a"]
        b = FakeSource({"example_b": [post("2", author="example_b")]})
        self.assertEqual(self.invoke(b, START + timedelta(minutes=15)), 0)
        self.assertEqual(b.calls, ["example_b"])
        self.assertEqual((self.data / "example_a.json").read_bytes(), before)
        self.assertEqual((self.output / "feeds/example_a.xml").read_bytes(), rss)
        self.assertEqual(json.loads((self.data / "_meta/status.json").read_text(encoding="utf-8"))["example_a"], state)
        page = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn('feeds/example_a.xml', page)
        self.assertIn('feeds/example_b.xml', page)

    def test_zero_request_run_preserves_status_and_skips_deployment(self):
        self.invoke(FakeSource({"example_a": [post("1")]}))
        before = (self.data / "_meta/status.json").read_bytes()
        source = FakeSource({})
        self.assertEqual(self.invoke(source, START + timedelta(minutes=1)), 0)
        self.assertEqual(source.calls, [])
        self.assertEqual((self.data / "_meta/status.json").read_bytes(), before)
        self.assertIn("ready=false", (self.root / "outputs").read_text())

    def test_429_warning_survives_restart_and_other_account_continues(self):
        self.invoke(FakeSource({"example_a": [post("1")]}), accounts=["example_a"])
        before = (self.output / "feeds/example_a.xml").read_bytes()
        reset = START + timedelta(hours=5)
        failure = FakeSource({"example_a": FetchError("HTTP 429", transient=True,
                              diagnostics={"http_status": 429, "reset_at": reset.isoformat()})})
        self.assertEqual(self.invoke(failure, START + timedelta(hours=1), ["example_a"]), 0)
        self.assertEqual((self.output / "feeds/example_a.xml").read_bytes(), before)
        other = FakeSource({"example_b": [post("2")]})
        self.assertEqual(self.invoke(other, START + timedelta(hours=1, minutes=15)), 0)
        self.assertEqual(other.calls, ["example_b"])
        source = FakeSource({})
        self.assertEqual(self.invoke(source, START + timedelta(hours=2), ["example_a"]), 0)
        self.assertEqual(source.calls, [])
        self.assertIn("⚠️", (self.root / "summary").read_text(encoding="utf-8"))

    def test_fatal_account_does_not_block_other_accounts_next_slot(self):
        self.assertEqual(self.invoke(FakeSource({"example_a": ValueError("bug")})), 1)
        other = FakeSource({"example_b": [post("2")]})
        self.assertEqual(self.invoke(other, START + timedelta(minutes=15)), 0)
        self.assertEqual(other.calls, ["example_b"])

    def test_cli_uses_scheduler_and_publish_only_never_uses_it(self):
        with patch("xrss.app.load_config", return_value=Config(["example_a"])), \
             patch("xrss.app.run_scheduled", return_value=0) as scheduled, \
             patch("xrss.app.publish_cached", return_value=0) as publish, \
             patch("sys.argv", ["xrss", "--site-url", "https://example.org"]):
            from xrss.app import main
            self.assertEqual(main(), 0)
            scheduled.assert_called_once()
            with patch("sys.argv", ["xrss", "--publish-only"]):
                self.assertEqual(main(), 0)
            publish.assert_called_once()
            scheduled.assert_called_once()

    def test_corrupt_history_before_http_does_not_monopolize_selection(self):
        self.data.mkdir()
        (self.data / "example_a.json").write_text("broken", encoding="utf-8")
        source = FakeSource({})
        self.assertEqual(self.invoke(source), 1)
        self.assertEqual(source.calls, [])
        other = FakeSource({"example_b": [post("2")]})
        self.assertEqual(self.invoke(other, START + timedelta(minutes=15)), 0)
        self.assertEqual(other.calls, ["example_b"])
