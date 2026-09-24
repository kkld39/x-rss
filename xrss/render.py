from email.utils import format_datetime
import html
from pathlib import Path
import re
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from .model import Post, timestamp

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/elements/1.1/"
ET.register_namespace("atom", ATOM)
ET.register_namespace("dc", DC)


def xml_text(value: str) -> str:
    # XML 1.0 cannot represent these codepoints even when escaped.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", value)


def safe_url(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def description(post: Post) -> str:
    body = "<p>" + html.escape(post.text).replace("\n", "<br />") + "</p>"
    if safe_url(post.quote_url):
        body += f'<p><a href="{html.escape(post.quote_url, quote=True)}">引用元の投稿</a></p>'
    for image in post.images:
        if safe_url(image):
            body += f'<p><img src="{html.escape(image, quote=True)}" alt="投稿画像" /></p>'
    body += f'<p><a href="{post.url}">Xで元の投稿を開く</a></p>'
    return xml_text(body)


def rss(handle: str, posts: list[Post], site_url: str, updated: str) -> bytes:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    def add(parent, tag, text):
        ET.SubElement(parent, tag).text = xml_text(text)
    add(channel, "title", f"@{handle} / X")
    add(channel, "link", f"https://x.com/{handle}")
    add(channel, "description", f"@{handle} の公開投稿。個人用の非公式RSSフィード。")
    add(channel, "language", "ja")
    add(channel, "lastBuildDate", format_datetime(timestamp(updated), usegmt=True))
    add(channel, "ttl", "30")
    ET.SubElement(channel, f"{{{ATOM}}}link", {
        "href": f"{site_url}/feeds/{handle}.xml", "rel": "self", "type": "application/rss+xml",
    })
    for post in posts:
        item = ET.SubElement(channel, "item")
        prefix = "[リポスト] " if post.is_repost else ""
        add(item, "title", prefix + (post.text.replace("\n", " ")[:140] or f"投稿 {post.id}"))
        add(item, "link", post.url)
        ET.SubElement(item, "guid", isPermaLink="false").text = f"urn:twitter:status:{post.id}"
        add(item, "pubDate", format_datetime(timestamp(post.created_at), usegmt=True))
        # RSS author requires an email address. Use Dublin Core for display names.
        add(item, f"{{{DC}}}creator", f"{post.author_name} (@{post.author})")
        add(item, "description", description(post))
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def index(accounts: list[str], statuses: dict, output: Path, updated: str) -> bytes:
    rows = []
    esc = html.escape
    for handle in accounts:
        status = statuses.get(handle.lower(), {})
        feed = f"feeds/{handle}.xml"
        if not (output / feed).is_file():
            existing = [p for p in (output / "feeds").glob("*.xml") if p.stem.lower() == handle.lower()]
            if existing:
                feed = f"feeds/{existing[0].name}"
        link = f'<a href="{feed}">RSSを購読</a>' if (output / feed).is_file() else "初回取得待ち"
        result = "成功" if status.get("ok") else "取得失敗（既存フィードを保持）"
        error = f'<small>{esc(str(status.get("error", "")))}</small>'
        rows.append(f'<tr><td><a href="https://x.com/{handle}">@{handle}</a></td>'
                    f'<td>{link}</td><td>{result}{error}</td>'
                    f'<td>{status.get("new_count", 0)}</td>'
                    f'<td>{esc(status.get("last_success") or "未取得")}</td></tr>')
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>X RSS フィード</title><style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:3rem auto;padding:0 1.2rem;color:#243245;background:#f7f9fc}}
h1{{font-size:2rem}}a{{color:#075bb8}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%;background:white}}
th,td{{text-align:left;border-bottom:1px solid #dbe2eb;padding:1rem;vertical-align:top}}small{{display:block;max-width:32rem;margin-top:.5rem;overflow-wrap:anywhere}}
p{{line-height:1.7}}footer{{margin-top:2rem;color:#526174}}</style></head>
<body><h1>X RSS フィード</h1><p>各RSSリンクのURLをInoreaderに登録してください。</p>
<p>最終更新日時（実行時刻・UTC）: <time>{esc(updated)}</time></p>
<div class="table"><table><thead><tr><th>監視アカウント</th><th>フィード</th><th>取得結果</th><th>新規取得</th><th>最終取得成功日時（UTC）</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<footer>非公式の個人用フィードです。Xや各投稿者とは無関係です。取得成功は全投稿の網羅を保証しません。
X側の制限・仕様変更で更新が停止することがあります。画像はXの配信元から読み込みます。</footer></body></html>'''
    return page.encode("utf-8")
