from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re

HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = parsedate_to_datetime(value)
    if result.tzinfo is None:
        raise ValueError("投稿日時にタイムゾーンがありません")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Post:
    id: str
    text: str
    created_at: str
    author: str
    author_name: str
    images: list[str]
    is_repost: bool = False
    is_reply: bool = False
    quote_url: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(r"[0-9]+", self.id):
            raise ValueError("投稿IDが不正です")
        if not isinstance(self.author, str) or not HANDLE.fullmatch(self.author):
            raise ValueError("投稿者名が不正です")
        if not isinstance(self.text, str) or not isinstance(self.author_name, str):
            raise ValueError("投稿本文・表示名が不正です")
        timestamp(self.created_at)
        if not isinstance(self.images, list) or not all(isinstance(x, str) for x in self.images):
            raise ValueError("画像リストが不正です")
        if type(self.is_repost) is not bool or type(self.is_reply) is not bool:
            raise ValueError("投稿種別が不正です")

    @property
    def url(self):
        return f"https://x.com/{self.author}/status/{self.id}"

    def to_dict(self):
        return asdict(self)
