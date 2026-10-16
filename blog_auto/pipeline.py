"""주제 목록 일괄 처리: 생성 → 초안 저장 → (선택) 발행."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Protocol

from . import storage
from .config import Config
from .generator import Post
from .topics import DRAFTED, FAILED, PENDING, PUBLISHED, Topic, load_topics, save_topics

log = logging.getLogger(__name__)


class Generator(Protocol):
    def generate(self, topic: str, keywords: str = "") -> Post: ...


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_batch(
    cfg: Config,
    generator: Generator,
    limit: int | None = None,
    publish_now: bool | None = None,
    retry_failed: bool = False,
) -> list[Topic]:
    """대기 중인 주제를 limit개까지 처리하고, 처리한 주제 목록을 돌려줍니다."""
    limit = cfg.posts_per_run if limit is None else limit
    publish_now = cfg.auto_publish if publish_now is None else publish_now
    wanted = {PENDING, FAILED} if retry_failed else {PENDING}

    topics = load_topics(cfg.topics_file)
    targets = [t for t in topics if t.status in wanted][:limit]
    if not targets:
        log.info("처리할 주제가 없습니다. (%s)", cfg.topics_file)
        return []

    for t in targets:
        log.info("글 생성 중: %s", t.topic)
        try:
            post = generator.generate(t.topic, t.keywords)
            path = storage.save_draft(post, cfg.drafts_dir)
            t.status, t.file = DRAFTED, str(path)
            if publish_now:
                path = storage.publish(path, cfg.posts_dir, cfg.webhook_url)
                t.status, t.file = PUBLISHED, str(path)
            log.info("완료 [%s]: %s", t.status, t.file)
        except Exception as e:  # 한 글이 실패해도 나머지는 계속 처리
            log.error("실패: %s (%s)", t.topic, e)
            if t.status != DRAFTED:
                t.status = FAILED
        t.updated_at = _now()
        # 중간에 중단돼도 진행 상황이 남도록 매 글마다 저장
        save_topics(cfg.topics_file, topics)

    return targets


def publish_drafts(cfg: Config, files: list[str] | None = None) -> list[Path]:
    """drafts/의 초안을 발행합니다. files가 없으면 전부 발행합니다."""
    drafts = [Path(f) for f in files] if files else sorted(Path(cfg.drafts_dir).glob("*.md"))
    topics = load_topics(cfg.topics_file)
    by_file = {Path(t.file).name: t for t in topics if t.file}

    published = []
    try:
        for d in drafts:
            target = storage.publish(d, cfg.posts_dir, cfg.webhook_url)
            published.append(target)
            if t := by_file.get(d.name):
                t.status, t.file, t.updated_at = PUBLISHED, str(target), _now()
            log.info("발행: %s", target)
    finally:
        # 중간에 실패해도 이미 발행한 글의 상태는 기록
        if topics:
            save_topics(cfg.topics_file, topics)
    return published
