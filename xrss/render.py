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
    add(channel, "ttl", "60")
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


def display_time(value):
    if not value:
        return "未取得"
    try:
        from datetime import timedelta, timezone
        return timestamp(value).astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M:%S JST")
    except (TypeError, ValueError, OverflowError):
        return str(value)


def index(accounts: list[str], statuses: dict, output: Path, updated: str) -> bytes:
    cards = []
    esc = html.escape
    for handle in accounts:
        status = statuses.get(handle.lower(), {})
        feed = f"feeds/{handle}.xml"
        if not (output / feed).is_file():
            existing = [p for p in (output / "feeds").glob("*.xml") if p.stem.lower() == handle.lower()]
            if existing:
                feed = f"feeds/{existing[0].name}"
        available = (output / feed).is_file()
        link = (f'<a class="subscribe" type="application/rss+xml" href="{feed}" aria-label="@{handle} のRSSを購読">RSSを購読 <span aria-hidden="true">↗</span></a>'
                if available else '<span class="pending">初回取得待ち</span>')
        error = str(status.get("error") or "")
        response = status.get("response") or {}
        http_status = response.get("http_status")
        if http_status is None and (match := re.search(r"HTTP (\d{3})", error)):
            http_status = int(match[1])
        health = status.get("health") or ("success" if status.get("ok") else "warning" if available else "pending")
        label = {"success": "取得成功", "warning": "更新待ち・保存済みRSSを配信", "error": "要確認", "pending": "初回取得待ち"}.get(health, "要確認")
        detail = ""
        reset = response.get("reset_at")
        if not reset and (match := re.search(r"reset Unix秒=(\d+)", error)):
            try:
                from datetime import datetime, timezone
                reset = datetime.fromtimestamp(int(match[1]), timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                pass
        times = (f'<div><dt>最終取得成功</dt><dd>{esc(display_time(status.get("last_success")))}</dd></div>'
                 f'<div><dt>最終アクセス</dt><dd>{esc(display_time(status.get("last_attempt")))}</dd></div>')
        if reset and not status.get("ok"):
            times += f'<div><dt>Xのreset時刻</dt><dd>{esc(display_time(reset))}<small>この時刻での制限解除は保証されません</small></dd></div>'
        if status.get("next_request_at"):
            times += f'<div><dt>次回アクセスはこの時刻以降</dt><dd>{esc(display_time(status["next_request_at"]))}</dd></div>'
        if error:
            http_label = f"HTTP {http_status}" if http_status else "通信・取得エラー"
            diagnostics = "\n".join(f"{key}: {response.get(key, '未通知')}" for key in (
                "http_status", "date", "x_rate_limit_limit", "x_rate_limit_remaining",
                "x_rate_limit_reset", "reset_at", "retry_after", "retry_at"))
            cache_note = "保存済みRSSの内容は維持しています。" if available else "保存済みRSSがありません。初回取得の成功が必要です。"
            detail = (f'<details><summary>{esc(http_label)} — 詳細を表示</summary>'
                      f'<p>{esc(error)}</p><pre>{esc(diagnostics)}</pre>'
                      f'<p>{cache_note}取得元への連続リトライは行いません。</p></details>')
        cards.append(f'''<article class="account"><header><h2><a href="https://x.com/{handle}">@{handle}</a></h2>{link}</header>
<p class="badge {esc(health)}">{esc(label)}</p><dl>{times}</dl>
<p class="counts">RSS {esc(str(status.get('feed_count', 0)))}件 · 履歴 {esc(str(status.get('saved_count', 0)))}件 · 前回の新規取得 {esc(str(status.get('new_count', 0)))}件</p>{detail}</article>''')
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>X RSS フィード</title><style>
*{{box-sizing:border-box}}body{{font-family:system-ui,-apple-system,sans-serif;max-width:1056px;margin:0 auto;padding:40px 24px;color:#223044;background:#f3f6fa;line-height:1.65}}
a{{color:#0752ad}}h1{{font-size:clamp(1.8rem,5vw,2.5rem);line-height:1.2;letter-spacing:-.035em;margin:8px 0 16px}}h2{{font-size:1.2rem;margin:0;overflow-wrap:anywhere}}
.eyebrow{{color:#526779;font-size:.8rem;font-weight:700;letter-spacing:.1em}}.intro{{max-width:650px;color:#526174}}.updated{{font-size:.8rem;color:#607083;margin:20px 0}}
.accounts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px}}.account{{min-width:0;background:white;border:1px solid #dce4ed;border-radius:16px;padding:24px;box-shadow:0 3px 10px #22304405}}
header{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}header h2 a{{text-decoration:none;color:inherit}}.subscribe{{display:inline-flex;align-items:center;gap:14px;background:#0752ad;color:white;text-decoration:none;padding:10px 16px;border-radius:8px;font-size:.9rem;font-weight:600;white-space:nowrap;min-height:44px}}
.badge{{display:inline-block;max-width:100%;font-size:.8rem;font-weight:650;border-radius:6px;padding:5px 10px;overflow-wrap:anywhere}}.success{{color:#17643b;background:#e8f5ec}}.warning,.pending{{color:#805000;background:#fff2d9}}.error{{color:#a52b31;background:#fdebed}}
dl{{margin:16px 0}}dl div{{margin:0 0 12px}}dt{{font-size:.76rem;color:#607083}}dd{{margin:2px 0 0;font-variant-numeric:tabular-nums;font-size:.9rem;overflow-wrap:anywhere}}small{{display:block;font-size:.72rem;color:#68788a}}.counts{{font-size:.8rem;color:#607083;margin:16px 0 0}}
details{{border-top:1px solid #e4eaf1;margin-top:20px;padding-top:14px;font-size:.82rem;min-width:0}}summary{{cursor:pointer;font-weight:600;min-height:32px;color:#805000}}details p,pre{{overflow-wrap:anywhere;white-space:pre-wrap;max-width:100%}}pre{{background:#f5f7fa;padding:12px;border-radius:8px;font-size:.72rem}}footer{{margin-top:30px;color:#607083;font-size:.78rem}}a:focus-visible,summary:focus-visible{{outline:3px solid #80b9ff;outline-offset:4px}}
@media(max-width:480px){{body{{padding:24px 16px}}.account{{padding:20px 16px}}.accounts{{gap:16px}}.subscribe{{padding:10px 12px}}}}
</style></head><body><main><p class="eyebrow">PERSONAL RSS READER</p><h1>X RSS フィード</h1>
<p class="intro">「RSSを購読」のリンク先をInoreaderに登録してください。毎時7・22・37・52分に、順番待ちのアカウントを最大1件だけ確認します。取得できない場合も保存済みの投稿を配信します。</p>
<p class="updated">ページ更新: <time datetime="{esc(updated)}">{esc(display_time(updated))}</time></p>
<h2>現在の監視対象（{len(accounts)}件）</h2><p class="intro">更新間隔の目安: 約{max(60, 15 * len(accounts))}分／アカウント。実行遅延や待機期限により長くなります。</p>
<section class="accounts" aria-label="監視アカウント">{''.join(cards)}</section></main>
<footer>非公式の個人用フィードです。Xや各投稿者とは無関係です。取得成功は全投稿の網羅を保証しません。
GitHubの共有IP帯などに対する制限やX側の仕様変更により、長時間更新できない場合があります。画像はXの配信元を参照します。</footer></body></html>'''
    return page.encode("utf-8")


