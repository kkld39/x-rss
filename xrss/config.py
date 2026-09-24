from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .model import HANDLE


@dataclass(frozen=True)
class Config:
    accounts: list[str]
    include_reposts: bool = False
    include_replies: bool = False
    max_posts: int = 300
    site_url: str = ""


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("accounts.yml はマッピングにしてください")
    unknown = set(raw) - set(Config.__dataclass_fields__)
    if unknown:
        raise ValueError(f"未知の設定キー: {sorted(unknown)}")
    accounts = raw.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError("accounts に1件以上のアカウントを指定してください")
    seen = set()
    for account in accounts:
        if not isinstance(account, str) or not HANDLE.fullmatch(account):
            raise ValueError(f"不正なアカウント名: {account!r}（@なしの英数字・_、最大15文字）")
        if account.lower() in seen:
            raise ValueError(f"アカウントが重複しています: {account}")
        seen.add(account.lower())
    for key in ("include_reposts", "include_replies"):
        if key in raw and type(raw[key]) is not bool:
            raise ValueError(f"{key} は true または false にしてください")
    count = raw.get("max_posts", 300)
    if type(count) is not int or not 200 <= count <= 500:
        raise ValueError("max_posts は200〜500の整数にしてください")
    url = raw.get("site_url", "")
    if not isinstance(url, str):
        raise ValueError("site_url は文字列にしてください")
    if url:
        validate_site_url(url)
    return Config(**raw)


def validate_site_url(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("site_url はクエリ・フラグメントなしの公開URLにしてください")
    return url.rstrip("/")
