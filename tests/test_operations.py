from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import yaml

from test_system import Config, FakeSource, NOW, document, post, tweet
import test_system as support
from xrss.runtime import publish_cached
from xrss.source import DirectOnlyRedirect, FetchError, SyndicationSource, response_details


class OperationsTests(unittest.TestCase):
    setUp = support.RunnerTests.setUp
    run_app = support.RunnerTests.run_app
    seed = support.RunnerTests.seed
    def test_all_429_are_warnings_with_exact_cache_preservation_and_cooldown(self):
        history, feed = self.seed()
        info = {"http_status": 429, "reset_at": "2026-09-24T17:00:00+00:00", "x_rate_limit_reset": "1790269200"}
        source = FakeSource({"example_account": FetchError("HTTP 429", transient=True, diagnostics=info)})
        self.assertEqual(self.run_app(Config(["example_account"]), source), 0)
        self.assertEqual((self.data / "example_account.json").read_bytes(), history)
        self.assertEqual((self.output / "feeds/example_account.xml").read_bytes(), feed)
        state = json.loads((self.data / "_meta/status.json").read_text(encoding="utf-8"))["example_account"]
        self.assertEqual(state["health"], "warning")
        self.assertEqual(state["last_success"], NOW)
        self.assertEqual(state["next_request_at"], info["reset_at"])
        source2 = FakeSource({"example_account": AssertionError("should never fetch during cooldown")})
        self.assertEqual(self.run_app(Config(["example_account"]), source2), 0)
        self.assertEqual(source2.calls, [])
        events = json.loads((self.data / "_meta/requests/example_account.json").read_text(encoding="utf-8"))
        self.assertEqual(events[-1]["request_count"], 0)
        self.assertEqual(events[-2]["response"]["http_status"], 429)
        page = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn("<details>", page)
        self.assertNotIn("<details open", page)
        self.assertIn("2026/09/25 02:00:00 JST", page)

    def test_network_and_503_warnings_but_programming_errors_fail(self):
        for error, expected in ((FetchError("timeout", transient=True), 0),
                                (FetchError("HTTP 503", transient=True), 0),
                                (ValueError("bug"), 1)):
            with self.subTest(error=error):
                self.seed()
                result = self.run_app(Config(["example_account"]), FakeSource({"example_account": error}))
                self.assertEqual(result, expected)
                # Clear cooldown for the next independent subcase.
                (self.data / "_meta/status.json").unlink()

    def test_initial_429_without_cached_rss_needs_attention(self):
        self.assertEqual(self.run_app(Config(["example_account"]), FakeSource({
            "example_account": FetchError("HTTP 429", transient=True)})), 1)
        self.assertFalse((self.output / "feeds/example_account.xml").exists())

    def test_render_failure_is_failure_not_warning_and_preserves_files(self):
        history, feed = self.seed()
        with patch("xrss.runtime.rss", side_effect=ValueError("cannot render")):
            result = self.run_app(Config(["example_account"]), FakeSource({"example_account": [post("123")]}))
        self.assertEqual(result, 1)
        self.assertEqual((self.data / "example_account.json").read_bytes(), history)
        self.assertEqual((self.output / "feeds/example_account.xml").read_bytes(), feed)

    def test_publish_only_never_fetches_or_changes_history_rss_or_success_time(self):
        history, feed = self.seed()
        state = (self.data / "_meta/status.json").read_bytes()
        with patch("xrss.source.SyndicationSource.fetch", side_effect=AssertionError("network forbidden")):
            self.assertEqual(publish_cached(Config(["example_account"]), self.data, self.output), 0)
        self.assertEqual((self.data / "example_account.json").read_bytes(), history)
        self.assertEqual((self.output / "feeds/example_account.xml").read_bytes(), feed)
        self.assertEqual((self.data / "_meta/status.json").read_bytes(), state)

    def test_summary_warning_and_fatal_even_when_other_account_succeeds(self):
        self.seed()
        source = FakeSource({"example_account": FetchError("429", transient=True), "Other": [post("123", author="Other")]})
        summary = self.root / "summary.md"
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": ""}):
            from xrss.runtime import run
            self.assertEqual(run(Config(["example_account", "Other"]), source, self.data, self.output,
                                 "https://example.org", now=NOW, pause=lambda _: None), 0)
        self.assertIn("⚠️", summary.read_text(encoding="utf-8"))
        self.assertEqual(self.run_app(Config(["Other", "Broken"]), FakeSource({
            "Other": [post("123", author="Other")], "Broken": RuntimeError("code bug")})), 1)


class NetworkBudgetTests(unittest.TestCase):
    def test_success_uses_one_open_and_records_only_safe_headers(self):
        response = Mock()
        response.status = 200
        response.headers = {"x-rate-limit-remaining": "29", "set-cookie": "secret"}
        response.read.return_value = document([tweet()]).encode()
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        source = SyndicationSource(opener=opener)
        self.assertEqual(len(source.fetch("example_account")), 1)
        opener.open.assert_called_once()
        self.assertEqual(source.last_response["http_status"], 200)
        self.assertNotIn("secret", json.dumps(source.last_response))

    def test_5xx_is_not_retried_and_redirect_is_not_followed(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://syndication.twitter.com/", 503, "Unavailable", {}, io.BytesIO())
        with self.assertRaises(FetchError) as caught:
            SyndicationSource(opener=opener).fetch("example_account")
        self.assertTrue(caught.exception.transient)
        opener.open.assert_called_once()
        self.assertIsNone(DirectOnlyRedirect().redirect_request(None, None, 302, "", {}, "https://syndication.twitter.com/next"))

    def test_reset_retry_after_seconds_date_and_invalid_headers(self):
        now = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
        d = response_details(429, {"retry-after": "120", "x-rate-limit-reset": "invalid"}, now)
        self.assertEqual(d["retry_at"], "2026-09-24T14:02:00+00:00")
        self.assertNotIn("reset_at", d)
        d = response_details(429, {"retry-after": "Thu, 24 Sep 2026 16:00:00 GMT"}, now)
        self.assertEqual(d["retry_at"], "2026-09-24T16:00:00+00:00")
        self.assertNotIn("retry_at", response_details(429, {"retry-after": "bad"}, now))

    def test_workflow_triggers_prevent_push_from_accessing_x(self):
        base = Path(".github/workflows")
        update = yaml.load((base / "update-feeds.yml").read_text(), Loader=yaml.BaseLoader)
        probe = yaml.load((base / "probe.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        publish = yaml.load((base / "publish-pages.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(update["on"]), {"schedule", "workflow_dispatch"})
        self.assertEqual(update["on"]["schedule"][0]["cron"], "7,22,37,52 * * * *")
        self.assertEqual(set(probe["on"]), {"workflow_dispatch"})
        self.assertIn("push", publish["on"])
        commands = [step.get("run", "") for step in publish["jobs"]["publish"]["steps"]]
        self.assertIn("python -m xrss.app --publish-only", commands)
        self.assertNotIn("python -m xrss.app", commands)


if __name__ == "__main__":
    unittest.main()
