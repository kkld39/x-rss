import argparse
import logging
import os
from pathlib import Path
import sys

from .config import load_config, validate_site_url
from .runtime import publish_cached, run
from .source import SyndicationSource

LOG = logging.getLogger("xrss")


def main():
    parser = argparse.ArgumentParser(description="Xの公開SyndicationタイムラインをRSS化")
    parser.add_argument("--config", type=Path, default=Path("accounts.yml"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("public"))
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", ""))
    parser.add_argument("--publish-only", action="store_true", help="Xに接続せず、保存済みRSSと状態からPagesのみ構築")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load_config(args.config)
        if args.publish_only:
            return publish_cached(config, args.data_dir, args.output)
        site_url = validate_site_url(config.site_url or args.site_url)
        return run(config, SyndicationSource(), args.data_dir, args.output, site_url)
    except Exception as exc:
        LOG.error("実行を開始・完了できませんでした: %s: %s", type(exc).__name__, exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
