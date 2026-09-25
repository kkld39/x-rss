"""Replaceable source boundary: fetch(handle) -> list[Post], or FetchError.

Only direct, cookie-free requests to X's embedded timeline service are made.
An empty upstream response is ambiguous and MUST NOT count as a success.
"""
import html
from html.parser import HTMLParser
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import HANDLE, Post, timestamp

ENDPOINT = "https://syndication.twitter.com/srv/timeline-profile/screen-name/"


class FetchError(RuntimeError):
    def __init__(self, message, *, transient=False, diagnostics=None):
        super().__init__(message)
        self.transient = transient
        self.diagnostics = diagnostics or {}


def response_details(status, headers, now=None):
    """Keep only diagnostic headers, never cookies or authentication data."""
    now = now or datetime.now(timezone.utc)
    result = {"http_status": status, "observed_at": now.isoformat()}
    for header in ("date", "retry-after", "x-rate-limit-limit", "x-rate-limit-remaining",
                   "x-rate-limit-reset", "x-transaction-id", "cf-ray"):
        value = headers.get(header)
        if value is not None:
            result[header.replace("-", "_")] = str(value)[:256]
    try:
        result["reset_at"] = datetime.fromtimestamp(int(headers.get("x-rate-limit-reset")), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    retry = headers.get("retry-after")
    if retry is not None:
        try:
            from datetime import timedelta
            retry_at = now + timedelta(seconds=max(0, int(retry)))
        except (ValueError, OverflowError):
            try:
                retry_at = parsedate_to_datetime(retry)
            except (TypeError, ValueError, OverflowError):
                retry_at = None
        if retry_at is not None and retry_at.tzinfo is not None:
            result["retry_at"] = retry_at.astimezone(timezone.utc).isoformat()
    return result


class Source(Protocol):
    def fetch(self, handle: str) -> list[Post]: ...


class NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False


def normalize(tweet: dict, handle: str) -> Post:
    user = tweet["user"]
    post_id = str(tweet.get("id_str") or tweet["id"])
    text = tweet.get("full_text", tweet.get("text"))
    if not isinstance(text, str):
        raise ValueError("本文フィールドがありません")
    for entity in tweet.get("entities", {}).get("urls", []):
        if entity.get("url") and entity.get("expanded_url"):
            text = text.replace(entity["url"], entity["expanded_url"])
    media = (tweet.get("extended_entities", {}).get("media", [])
             or tweet.get("entities", {}).get("media", [])
             or tweet.get("mediaDetails", []))
    images = []
    for item in media:
        image = item.get("media_url_https")
        if image and image.startswith("https://") and image not in images:
            images.append(image)
    for item in tweet.get("photos", []):
        image = item.get("url")
        if image and image.startswith("https://") and image not in images:
            images.append(image)
    author = user["screen_name"]
    is_repost = bool(tweet.get("retweeted_status") or tweet.get("retweeted_status_id_str")
                     or author.lower() != handle.lower() or text.startswith("RT @"))
    # `retweeted` means the viewer's interaction state, NOT a repost marker.
    is_reply = bool(tweet.get("in_reply_to_status_id_str") or tweet.get("in_reply_to_status_id")
                    or tweet.get("in_reply_to_user_id_str") or tweet.get("in_reply_to_screen_name"))
    if tweet.get("conversation_id_str") and str(tweet["conversation_id_str"]) != post_id:
        is_reply = True
    quote = tweet.get("quoted_status") or tweet.get("quoted_tweet") or {}
    quote_id = tweet.get("quoted_status_id_str") or quote.get("id_str")
    quote_url = f"https://x.com/i/web/status/{quote_id}" if quote_id and str(quote_id).isdigit() else None
    if isinstance(tweet.get("retweeted_status"), dict):
        original = normalize(tweet["retweeted_status"], tweet["retweeted_status"]["user"]["screen_name"])
        text = f"RT @{original.author}: {original.text}\n\n{original.url}"
        images = original.images
        quote_url = original.quote_url
    return Post(post_id, html.unescape(text), timestamp(tweet["created_at"]).isoformat(),
                author, user["name"], images, is_repost, is_reply, quote_url)


def parse_timeline(document: str, handle: str) -> list[Post]:
    parser = NextDataParser()
    parser.feed(document)
    if not parser.parts:
        raise FetchError("__NEXT_DATA__ がありません（ログイン要求・遮断・Xの仕様変更の可能性）")
    try:
        data = json.loads("".join(parser.parts))
        entries = data["props"]["pageProps"]["timeline"]["entries"]
        if not isinstance(entries, list):
            raise ValueError("entries が配列ではありません")
        posts = []
        for entry in entries:
            tweet = entry.get("content", {}).get("tweet")
            if tweet is not None:
                posts.append(normalize(tweet, handle))
            elif entry.get("type", "").lower() == "tweet":
                raise ValueError("tweet entry に投稿データがありません")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise FetchError(f"タイムライン構造を解釈できません: {exc}") from exc
    if not posts:
        raise FetchError("投稿を取得できませんでした。空の応答は正常取得とみなしません")
    return posts


class DirectOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even an in-domain redirect would cause a second request.
        return None


class SyndicationSource:
    def __init__(self, timeout=25, opener=None):
        self.timeout = timeout
        self.opener = opener or build_opener(DirectOnlyRedirect())
        self.last_response = {}

    def fetch(self, handle: str) -> list[Post]:
        self.last_response = {}
        if not HANDLE.fullmatch(handle):
            raise FetchError("不正なアカウント名")
        request = Request(ENDPOINT + handle, headers={
            "User-Agent": "Mozilla/5.0 (compatible; X-RSS/1.0)",
            "Accept": "text/html", "Accept-Language": "ja,en;q=0.8",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                self.last_response = response_details(response.status, response.headers)
                content = response.read(8 * 1024 * 1024 + 1)
                if len(content) > 8 * 1024 * 1024:
                    raise FetchError("応答サイズが8MiBを超えました")
                return parse_timeline(content.decode("utf-8"), handle)
        except HTTPError as exc:
            self.last_response = response_details(exc.code, exc.headers)
            detail = f"HTTP {exc.code} (reset={self.last_response.get('reset_at', '不明')}, "
            detail += f"Retry-After={self.last_response.get('retry_after', '不明')})"
            exc.close()
            raise FetchError(detail, transient=exc.code in (408, 425, 429) or 500 <= exc.code <= 599,
                             diagnostics=self.last_response) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FetchError(f"通信失敗: {exc}", transient=True, diagnostics=self.last_response) from exc
