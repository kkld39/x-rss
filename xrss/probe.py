"""Read-only live connectivity check. No cookies, credentials or history writes."""
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

from .config import load_config
from .source import ENDPOINT, SyndicationSource


def main():
    config = load_config(Path("accounts.yml"))
    source = SyndicationSource()
    reports = []
    for position, account in enumerate(config.accounts):
        if position:
            time.sleep(2)
        report = {"account": account, "endpoint": ENDPOINT + account,
                  "checked_at": datetime.now(timezone.utc).isoformat(),
                  "github_actions": os.environ.get("GITHUB_ACTIONS") == "true"}
        try:
            posts = source.fetch(account)
            report.update(ok=True, count=len(posts),
                          newest_post=max(p.created_at for p in posts),
                          reposts=sum(p.is_repost for p in posts),
                          replies=sum(p.is_reply for p in posts),
                          posts_with_images=sum(bool(p.images) for p in posts))
        except Exception as exc:
            report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        import html
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("## 認証不要の実接続テスト\n\n<pre>" +
                         html.escape(json.dumps(reports, ensure_ascii=False, indent=2)) + "</pre>\n")
    return 0 if any(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
