"""One due account per invocation; persisted timestamps, no sleeping or catch-up bursts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import os

from .model import timestamp
from .runtime import load_status, publish_cached, run

LOG = logging.getLogger("xrss")
GLOBAL_GAP = timedelta(minutes=15)
ACCOUNT_GAP = timedelta(hours=1)


def select_account(accounts, states, now):
    current = timestamp(now)
    attempts = [timestamp(s["last_attempt"]) for s in states.values() if s.get("last_attempt")]
    # Include removed accounts: editing configuration must not reset the global budget.
    if attempts and current < max(attempts) + GLOBAL_GAP:
        return None, "全体の最終アクセスから15分未満のため待機"
    eligible = []
    earliest = datetime.min.replace(tzinfo=timezone.utc)
    for position, handle in enumerate(accounts):
        state = states.get(handle.lower(), {})
        last = timestamp(state["last_attempt"]) if state.get("last_attempt") else earliest
        # A corrupt account can fail before HTTP; do not let it monopolize selection.
        checked = timestamp(state["last_check"]) if state.get("last_check") else earliest
        priority = max(last, checked)
        due = max(priority + ACCOUNT_GAP,
                  timestamp(state["next_request_at"]) if state.get("next_request_at") else earliest)
        if due <= current:
            eligible.append((priority, position, handle))
    if not eligible:
        return None, "全アカウントが最短更新間隔または取得待機期限内のため待機"
    return min(eligible)[2], "未取得を優先し、最終アクセスが古い順に1件選択"


def run_scheduled(config, source, data_dir, output, site_url, *, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    states = load_status(data_dir)
    selected, reason = select_account(config.accounts, states, now)
    message = f"取得割当: {selected or 'なし'} / 登録{len(config.accounts)}件。{reason}"
    LOG.info(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"## アクセス分散\n\n{message}\n\n1回最大1リクエスト、全体で最低15分間隔。\n\n")
            if any(s.get("health") == "warning" or (s.get("error") and not s.get("ok")) for s in states.values()):
                stream.write("> ⚠️ 前回の取得失敗が残っているアカウントがあります。待機中も保存済みRSSを維持します。\n\n")
    if selected:
        return run(replace(config, accounts=[selected]), source, data_dir, output, site_url,
                   now=now, render_accounts=config.accounts)
    # No fake success/attempt time and no new journal entry for accounts not contacted.
    publish_cached(config, data_dir, output, now=now)
    if gh_output := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_output, "a", encoding="utf-8") as stream:
            stream.write("ready=false\nsuccesses=0\nwarnings=0\nerrors=0\n")
    return 0
