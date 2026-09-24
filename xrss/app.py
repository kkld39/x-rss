import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time

from .config import Config, load_config, validate_site_url
from .render import index, rss
from .source import Source, SyndicationSource
from .storage import atomic_write, json_bytes, load_posts, merge_posts

LOG = logging.getLogger("xrss")


def run(config: Config, source: Source, data_dir: Path, output: Path, site_url: str,
        *, pause=time.sleep, now=None) -> int:
    now = now or datetime.now(timezone.utc).isoformat()
    state_path = data_dir / "_meta" / "status.json"
    statuses = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    if not isinstance(statuses, dict) or not all(isinstance(x, dict) for x in statuses.values()):
        raise ValueError("status.json が壊れています。既存データを保持して停止します")
    successes = 0
    reports = []
    for number, handle in enumerate(config.accounts):
        if number:
            pause(2)
        state = dict(statuses.get(handle.lower(), {}))
        state.update(last_attempt=now, ok=False, new_count=0)
        try:
            history_path = data_dir / f"{handle}.json"
            # Preserve histories if only the capitalization of a configured handle changes.
            if not history_path.exists():
                matches = [p for p in data_dir.glob("*.json") if p.stem.lower() == handle.lower()]
                if matches:
                    history_path = matches[0]
            old = load_posts(history_path)
            incoming = source.fetch(handle)
            if not incoming:
                raise ValueError("取得元が空の投稿リストを返しました")
            merged, new_count = merge_posts(old, incoming, config.max_posts)
            visible = [p for p in merged if (config.include_reposts or not p.is_repost)
                       and (config.include_replies or not p.is_reply)]
            xml = rss(handle, visible, site_url, now)
            history = json_bytes([p.to_dict() for p in merged])
            # Nothing is touched until fetching, validation, merging and rendering complete.
            atomic_write(history_path, history)
            atomic_write(output / "feeds" / f"{handle}.xml", xml)
            state.update(ok=True, last_success=now, new_count=new_count,
                         fetched_count=len(incoming), saved_count=len(merged), feed_count=len(visible), error=None)
            successes += 1
            message = f"成功 @{handle}: 取得={len(incoming)}, 新規={new_count}, 保存={len(merged)}, RSS={len(visible)}"
            LOG.info(message)
        except Exception as exc:
            # Isolation boundary: one provider/account failure must not stop other accounts.
            error = f"{type(exc).__name__}: {exc}"
            state["error"] = error
            message = f"失敗 @{handle}: {error}（既存JSON/RSSを保持）"
            LOG.error(message)
        statuses[handle.lower()] = state
        reports.append(message)
    atomic_write(state_path, json_bytes(statuses))
    atomic_write(output / "index.html", index(config.accounts, statuses, output, now))
    atomic_write(output / ".nojekyll", b"")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        import html
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## X RSS 取得結果\n\n<pre>" + html.escape("\n".join(reports)) + "</pre>\n")
    if gh_output := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_output, "a", encoding="utf-8") as stream:
            stream.write(f"ready=true\nsuccesses={successes}\n")
    if not successes:
        LOG.error("全%dアカウントの取得に失敗しました", len(config.accounts))
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Xの公開SyndicationタイムラインをRSS化")
    parser.add_argument("--config", type=Path, default=Path("accounts.yml"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", ""))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        site_url = validate_site_url(config.site_url or args.site_url)
        return run(config, SyndicationSource(), args.data_dir, args.output, site_url)
    except Exception as exc:
        LOG.error("実行を開始・完了できませんでした: %s: %s", type(exc).__name__, exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
