"""Cache-preserving collection and network-free Pages rendering."""
from datetime import datetime, timedelta, timezone
import html
import json
import logging
import os
from pathlib import Path
from xml.etree import ElementTree as ET

from .config import Config
from .model import timestamp
from .render import index, rss
from .source import FetchError, Source
from .storage import atomic_write, json_bytes, load_posts, merge_posts

LOG = logging.getLogger("xrss")


def load_status(data_dir):
    path = data_dir / "_meta/status.json"
    states = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(states, dict) or not all(isinstance(x, dict) for x in states.values()):
        raise ValueError("status.json が壊れています。既存データを保持して停止します")
    return states


def account_file(directory: Path, handle: str, suffix: str):
    path = directory / f"{handle}{suffix}"
    if not path.exists():
        matches = [p for p in directory.glob(f"*{suffix}") if p.stem.lower() == handle.lower()]
        if matches:
            return matches[0]
    return path


def check_feed(path):
    root = ET.parse(path).getroot()
    if root.tag != "rss" or root.get("version") != "2.0" or root.find("channel") is None:
        raise ValueError(f"保存済みRSSが不正です: {path}")


def publish_cached(config, data_dir, output, now=None):
    """Never constructs a source, changes RSS, or changes the last fetch time."""
    states = load_status(data_dir)
    for handle in config.accounts:
        load_posts(account_file(data_dir, handle, ".json"))
        feed = account_file(output / "feeds", handle, ".xml")
        if feed.exists():
            check_feed(feed)
    now = now or datetime.now(timezone.utc).isoformat()
    atomic_write(output / "index.html", index(config.accounts, states, output, now))
    atomic_write(output / ".nojekyll", b"")
    LOG.info("保存済みRSSを変更せずにPagesを構築しました（Xへのリクエスト0件）")
    return 0


def annotation(level, message):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        safe = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level} title=X RSS::{safe}", flush=True)


def record_attempt(data_dir, handle, record):
    path = data_dir / "_meta/requests" / f"{handle}.json"
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if not isinstance(history, list):
        raise ValueError(f"取得診断履歴が壊れています: {path}")
    atomic_write(path, json_bytes((history + [record])[-120:]))


def run(config: Config, source: Source, data_dir: Path, output: Path, site_url: str,
        *, pause=None, now=None, render_accounts=None) -> int:
    now = now or datetime.now(timezone.utc).isoformat()
    current = timestamp(now)
    states = load_status(data_dir)
    successes = warnings = errors = 0
    reports = []
    for handle in config.accounts:
        state = dict(states.get(handle.lower(), {}))
        state.update(last_check=now, new_count=0, request_count=0)
        cached = False
        diagnostics = {}
        try:
            history_path = account_file(data_dir, handle, ".json")
            feed_path = account_file(output / "feeds", handle, ".xml")
            old = load_posts(history_path)
            if feed_path.exists():
                check_feed(feed_path)
                cached = bool(old)
            if state.get("next_request_at") and timestamp(state["next_request_at"]) > current:
                diagnostics = state.get("response", {})
                raise FetchError(f"次回取得可能時刻まで待機: {state['next_request_at']}",
                                 transient=True, diagnostics=diagnostics)
            state.update(last_attempt=now, request_count=1)
            incoming = source.fetch(handle)
            diagnostics = getattr(source, "last_response", {})
            if not incoming:
                raise FetchError("取得元が空の投稿リストを返しました。仕様変更・制限を確認してください")
            merged, new_count = merge_posts(old, incoming, config.max_posts)
            visible = [p for p in merged if (config.include_reposts or not p.is_repost)
                       and (config.include_replies or not p.is_reply)]
            xml = rss(handle, visible, site_url, now)
            history = json_bytes([p.to_dict() for p in merged])
            # Fetch/schema/render failures cannot overwrite either saved artifact.
            atomic_write(history_path, history)
            atomic_write(output / "feeds" / f"{handle}.xml", xml)
            state.update(ok=True, health="success", last_success=now, new_count=new_count,
                         fetched_count=len(incoming), saved_count=len(merged), feed_count=len(visible),
                         response=diagnostics, error=None, next_request_at=None, consecutive_failures=0)
            successes += 1
            message = f"成功 @{handle}: HTTP={diagnostics.get('http_status', '不明')}, リクエスト=1, 取得={len(incoming)}, 新規={new_count}, 保存={len(merged)}, RSS={len(visible)}"
            LOG.info(message)
        except FetchError as exc:
            diagnostics = (exc.diagnostics or getattr(source, "last_response", {})) if state["request_count"] else diagnostics
            state.update(ok=False, error=str(exc), response=diagnostics)
            if state["request_count"]:
                state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
                if exc.transient:
                    # No repeat requests in this run; also persist cooldown across runners.
                    until = current + timedelta(hours=1)
                    for key in ("reset_at", "retry_at"):
                        if diagnostics.get(key):
                            until = max(until, timestamp(diagnostics[key]))
                    state["next_request_at"] = until.isoformat()
            temporary = exc.transient and cached
            state["health"] = "warning" if temporary else "error"
            if temporary:
                warnings += 1
                message = f"警告 @{handle}: {exc}。既存JSON/RSSを維持。リクエスト={state['request_count']}"
                LOG.warning(message)
                annotation("warning", message)
            else:
                errors += 1
                reason = "（配信可能な保存済み履歴・RSSなし）" if exc.transient else ""
                message = f"要対応 @{handle}: {exc}{reason}。リクエスト={state['request_count']}"
                LOG.error(message)
                annotation("error", message)
        except Exception as exc:
            errors += 1
            state.update(ok=False, health="error", error=f"{type(exc).__name__}: {exc}")
            message = f"要対応 @{handle}: {state['error']}"
            LOG.exception(message)
            annotation("error", message)
        states[handle.lower()] = state
        reports.append(message)
        record_attempt(data_dir, handle, {
            "checked_at": now, "request_count": state["request_count"], "health": state["health"],
            "response": diagnostics, "error": state.get("error"),
            "next_request_at": state.get("next_request_at"),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        })
    atomic_write(data_dir / "_meta/status.json", json_bytes(states))
    atomic_write(output / "index.html", index(render_accounts or config.accounts, states, output, now))
    atomic_write(output / ".nojekyll", b"")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"## X RSS 取得結果\n\n成功 {successes} / 警告 {warnings} / 要対応 {errors}\n\n")
            if warnings:
                stream.write("> ⚠️ 一時的な取得失敗があります。保存済みRSSを配信し、再試行はしていません。\n\n")
            stream.write("<pre>" + html.escape("\n".join(reports)) + "</pre>\n")
    if gh_output := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_output, "a", encoding="utf-8") as stream:
            stream.write(f"ready=true\nsuccesses={successes}\nwarnings={warnings}\nerrors={errors}\n")
    return 1 if errors else 0
