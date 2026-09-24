import json
import os
from pathlib import Path
import tempfile

from .model import Post, timestamp


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_posts(path: Path) -> list[Post]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"履歴が配列ではありません: {path}")
    return [Post(**entry) for entry in raw]


def merge_posts(old: list[Post], new: list[Post], limit: int) -> tuple[list[Post], int]:
    by_id = {post.id: post for post in old}
    new_count = len({post.id for post in new} - by_id.keys())
    by_id.update({post.id: post for post in new})
    merged = sorted(by_id.values(), key=lambda post: (timestamp(post.created_at), int(post.id)), reverse=True)
    return merged[:limit], new_count
