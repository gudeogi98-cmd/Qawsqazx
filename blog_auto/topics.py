"""주제 목록(CSV) 읽기/쓰기."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path

FIELDS = ["topic", "keywords", "status", "file", "updated_at"]

PENDING = "pending"
DRAFTED = "drafted"
PUBLISHED = "published"
FAILED = "failed"


@dataclass
class Topic:
    topic: str
    keywords: str = ""
    status: str = PENDING
    file: str = ""
    updated_at: str = ""


def load_topics(path: str | Path) -> list[Topic]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            topic = (row.get("topic") or "").strip()
            if not topic:
                continue
            rows.append(
                Topic(
                    topic=topic,
                    keywords=(row.get("keywords") or "").strip(),
                    status=(row.get("status") or PENDING).strip() or PENDING,
                    file=(row.get("file") or "").strip(),
                    updated_at=(row.get("updated_at") or "").strip(),
                )
            )
        return rows


def save_topics(path: str | Path, topics: list[Topic]) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for t in topics:
            writer.writerow(asdict(t))
    tmp.replace(path)
