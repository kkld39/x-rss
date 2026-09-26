from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET

from xrss.app import run
from xrss.config import Config, load_config
from xrss.model import Post
from xrss.render import DC, rss
from xrss.source import DirectOnlyRedirect, FetchError, SyndicationSource, parse_timeline, response_details
from xrss.runtime import publish_cached
from xrss.storage import json_bytes, load_posts, merge_posts

NOW = "2026-09-24T14:39:05+00:00"


def post(id="2103031729787445314", **kwargs):
    return replace(Post(id, "日本語 & <script>alert(1)</script>\n😀", NOW,
                        "example_account", "表示名", ["https://pbs.twimg.com/a.jpg?x=1&y=2"]), **kwargs)


def tweet(**kwargs):
    # Synthetic content with the field layout observed in the 2026-09-24 response.
    value = {"id": 0, "id_str": "2103031729787445314", "full_text": "本文 &amp; 🐈",
             "created_at": "Thu Sep 24 08:00:11 +0000 2026", "conversation_id_str": "2103031729787445314",
             "user": {"screen_name": "example_account", "name": "表示名"},
             "entities": {"urls": [], "media": []}, "retweeted": False}
    value.update(kwargs)
    return value


def document(tweets):
    data = {"props": {"pageProps": {"timeline": {"entries": [
        {"type": "tweet", "content": {"tweet": t}} for t in tweets]}}}}
    return '<html><script type="application/json" id="__NEXT_DATA__">' + json.dumps(data) + '</script></html>'


class FakeSource:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, handle):
        self.calls.append(handle)
        result = self.responses[handle]
        if isinstance(result, Exception):
            raise result
        return result


class ParserTests(unittest.TestCase):
    def test_live_shaped_normal_reply_repost_quote(self):
        image = {"type": "photo", "media_url_https": "https://pbs.twimg.com/test.jpg"}
        normal = tweet(extended_entities={"media": [image]}, retweeted=True)
        reply = tweet(id_str="2103032068364292161")
        original = tweet(user={"screen_name": "Other", "name": "別の投稿者"},
                         full_text="省略されていない本文", extended_entities={"media": [image]})
        repost = tweet(id_str="2103032068364292162", retweeted_status=original)
        quote = tweet(quoted_status_id_str="2000000000000000000")
        a, b, c, d = parse_timeline(document([normal, reply, repost, quote]), "example_account")
        self.assertEqual(a.id, "2103031729787445314")  # Never use rounded/numeric id=0.
        self.assertEqual(a.text, "本文 & 🐈")
        self.assertEqual(a.images, [image["media_url_https"]])
        self.assertFalse(a.is_repost)  # `retweeted: true` is not a repost.
        self.assertTrue(b.is_reply)
        self.assertTrue(c.is_repost)
        self.assertIn("省略されていない本文", c.text)
        self.assertTrue(c.images)
        self.assertFalse(d.is_repost)
        self.assertIn("2000000000000000000", d.quote_url)

    def test_empty_login_error_and_schema_change_fail(self):
        for body in ("<html>Login</html>", document([]),
                     '<script id="__NEXT_DATA__">{"props":{}}</script>',
                     document([tweet(created_at="invalid")]),
                     document([{"id_str": "123"}])):
            with self.subTest(body=body), self.assertRaises(FetchError):
                parse_timeline(body, "example_account")

    def test_429_is_not_retried(self):
        error = HTTPError("https://syndication.twitter.com/", 429, "limited",
                          {"x-rate-limit-reset": "1234"}, io.BytesIO(b"Rate limit exceeded"))
        with patch("xrss.source.build_opener") as make:
            make.return_value.open.side_effect = error
            with self.assertRaises(FetchError) as caught:
                SyndicationSource().fetch("example_account")
            self.assertTrue(caught.exception.transient)
            self.assertEqual(caught.exception.diagnostics["x_rate_limit_reset"], "1234")
            self.assertEqual(make.return_value.open.call_count, 1)

    def test_transient_network_error_is_never_retried(self):
        with patch("xrss.source.build_opener") as make:
            make.return_value.open.side_effect = URLError("timeout")
            with self.assertRaises(FetchError) as caught:
                SyndicationSource().fetch("example_account")
            self.assertTrue(caught.exception.transient)
            self.assertEqual(make.return_value.open.call_count, 1)
            request = make.return_value.open.call_args.args[0]
            self.assertFalse(request.has_header("Cookie"))
            self.assertFalse(request.has_header("Authorization"))


class RssTests(unittest.TestCase):
    def test_rss_unicode_guid_dates_author_images_and_escaping(self):
        value = post(text=post().text + "\x00", quote_url="https://x.com/i/web/status/123")
        root = ET.fromstring(rss("example_account", [value], "https://example.github.io/repo", NOW))
        self.assertEqual(root.attrib["version"], "2.0")
        item = root.find("channel/item")
        self.assertEqual(item.findtext("guid"), "urn:twitter:status:" + value.id)
        self.assertEqual(item.findtext("pubDate"), "Thu, 24 Sep 2026 14:39:05 GMT")
        self.assertIn("表示名", item.findtext(f"{{{DC}}}creator"))
        body = item.findtext("description")
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>", body)
        self.assertIn("<img", body)
        self.assertNotIn("\x00", body)
        self.assertIn("引用元", body)

    def test_unsafe_image_not_embedded(self):
        xml = rss("example_account", [post(images=["javascript:alert(1)"])], "https://example.org", NOW)
        self.assertNotIn(b"javascript:", xml)


class StorageTests(unittest.TestCase):
    def test_deduplicate_update_order_and_retention(self):
        old = [post(str(i), created_at="2026-09-01T00:00:00+00:00") for i in range(1, 301)]
        merged, count = merge_posts(old, [post("301"), post("300", text="編集"), post("301")], 300)
        self.assertEqual(count, 1)
        self.assertEqual(len(merged), 300)
        self.assertEqual(merged[0].id, "301")
        self.assertEqual(merged[1].text, "編集")
        self.assertNotIn("1", [p.id for p in merged])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        # Expected failures in tests must not emit production Actions annotations.
        environment = patch.dict(os.environ, {"GITHUB_ACTIONS": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.output = self.root / "public"

    def run_app(self, config, source):
        with patch.dict(os.environ, {"GITHUB_OUTPUT": "", "GITHUB_STEP_SUMMARY": ""}):
            return run(config, source, self.data, self.output, "https://example.github.io/repo",
                       pause=lambda seconds: None, now=NOW)

    def seed(self):
        self.run_app(Config(["example_account"]), FakeSource({"example_account": [post()]}))
        return (self.data / "example_account.json").read_bytes(), (self.output / "feeds/example_account.xml").read_bytes()

    def test_partial_failure_preserves_old_files_and_continues(self):
        history, feed = self.seed()
        source = FakeSource({"example_account": FetchError("HTTP 429", transient=True, diagnostics={"http_status": 429}), "Other": [post("123", author="Other")]})
        self.assertEqual(self.run_app(Config(["example_account", "Other"]), source), 0)
        self.assertEqual(source.calls, ["example_account", "Other"])
        self.assertEqual((self.data / "example_account.json").read_bytes(), history)
        self.assertEqual((self.output / "feeds/example_account.xml").read_bytes(), feed)
        self.assertTrue((self.output / "feeds/Other.xml").exists())
        state = json.loads((self.data / "_meta/status.json").read_text())
        self.assertEqual(state["example_account"]["last_success"], NOW)
        self.assertFalse(state["example_account"]["ok"])

    def test_all_failure_returns_nonzero_and_updates_status_page(self):
        history, feed = self.seed()
        result = self.run_app(Config(["example_account"]), FakeSource({"example_account": FetchError("HTTP 403")}))
        self.assertEqual(result, 1)
        self.assertEqual((self.data / "example_account.json").read_bytes(), history)
        self.assertEqual((self.output / "feeds/example_account.xml").read_bytes(), feed)
        self.assertIn("HTTP 403", (self.output / "index.html").read_text(encoding="utf-8"))

    def test_first_failure_does_not_create_empty_feed_or_history(self):
        self.assertEqual(self.run_app(Config(["example_account"]), FakeSource({"example_account": []})), 1)
        self.assertFalse((self.data / "example_account.json").exists())
        self.assertFalse((self.output / "feeds/example_account.xml").exists())

    def test_filter_changes_apply_to_history_and_quotes_remain(self):
        incoming = [post("1"), post("2", is_repost=True), post("3", is_reply=True),
                    post("4", quote_url="https://x.com/i/web/status/9")]
        source = FakeSource({"example_account": incoming})
        self.run_app(Config(["example_account"]), source)
        self.assertEqual(len(load_posts(self.data / "example_account.json")), 4)
        path = self.output / "feeds/example_account.xml"
        self.assertEqual(len(ET.parse(path).findall("channel/item")), 2)
        self.run_app(Config(["example_account"], include_reposts=True, include_replies=True),
                     FakeSource({"example_account": [post("1")]}))
        self.assertEqual(len(ET.parse(path).findall("channel/item")), 4)
        self.assertEqual(json.loads((self.data / "_meta/status.json").read_text())["example_account"]["new_count"], 0)

    def test_corrupt_history_is_not_overwritten(self):
        self.data.mkdir()
        path = self.data / "example_account.json"
        path.write_text("broken", encoding="utf-8")
        self.assertEqual(self.run_app(Config(["example_account"]), FakeSource({"example_account": [post()]})), 1)
        self.assertEqual(path.read_text(), "broken")


class ConfigTests(unittest.TestCase):
    def test_invalid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.yml"
            for content in ("accounts: []", "accounts: [../bad]", "accounts: [example_account, EXAMPLE_ACCOUNT]",
                            'accounts: [example_account]\ninclude_replies: "false"',
                            "accounts: [example_account]\nmax_posts: 2", "accounts: [example_account]\nwrong: true"):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
