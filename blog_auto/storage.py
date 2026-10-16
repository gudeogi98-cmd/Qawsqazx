"""Markdown 파일 저장과 발행(drafts/ → posts/, 웹훅)."""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

from .generator import Post


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:80].strip("-") or "post"


def render_markdown(post: Post, date: datetime) -> str:
    front = {
        "title": post.title,
        "date": date.strftime("%Y-%m-%d %H:%M:%S"),
        "description": post.summary,
        "tags": post.tags,
        "slug": slugify(post.slug),
    }
    header = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{header}\n---\n\n{post.body}\n"


def save_draft(post: Post, drafts_dir: str | Path, date: datetime | None = None) -> Path:
    date = date or datetime.now()
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)

    # Jekyll/Hugo 등 정적 사이트 생성기와 호환되는 파일명: YYYY-MM-DD-slug.md
    base = f"{date:%Y-%m-%d}-{slugify(post.slug)}"
    path = drafts_dir / f"{base}.md"
    n = 2
    while path.exists():
        path = drafts_dir / f"{base}-{n}.md"
        n += 1

    path.write_text(render_markdown(post, date), encoding="utf-8")
    return path


def read_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def publish(draft: str | Path, posts_dir: str | Path, webhook_url: str = "") -> Path:
    """초안을 posts/로 옮기고, 웹훅이 설정돼 있으면 글 내용을 POST합니다."""
    draft = Path(draft)
    posts_dir = Path(posts_dir)
    posts_dir.mkdir(parents=True, exist_ok=True)

    target = posts_dir / draft.name
    if target.exists():
        raise FileExistsError(f"이미 발행된 파일이 있습니다: {target}")

    # 웹훅이 실패하면 파일을 옮기지 않아 다음 실행에서 다시 시도할 수 있게 합니다.
    if webhook_url:
        meta, body = read_front_matter(draft)
        send_webhook(webhook_url, {**meta, "body": body, "file": draft.name})

    shutil.move(str(draft), target)
    return target


def send_webhook(url: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"웹훅 응답 오류: HTTP {resp.status}")
