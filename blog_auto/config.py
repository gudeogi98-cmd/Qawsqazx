"""설정 로딩: config.yaml + 환경 변수."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass
class Config:
    model: str = "claude-opus-5-5"
    effort: str = "medium"  # low / medium / high / xhigh / max
    language: str = "한국어"
    tone: str = "친근하고 이해하기 쉬운"
    target_length: int = 2000  # 본문 목표 글자 수(대략)
    topics_file: str = "topics.csv"
    drafts_dir: str = "drafts"
    posts_dir: str = "posts"
    posts_per_run: int = 1
    auto_publish: bool = False  # True면 생성 즉시 posts/로 발행
    webhook_url: str = ""  # 발행 시 JSON을 POST할 URL (선택)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        data: dict = {}
        path = Path(path)
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"config.yaml에 알 수 없는 키가 있습니다: {', '.join(sorted(unknown))}")

        cfg = cls(**data)
        # 웹훅 URL은 비밀일 수 있으므로 환경 변수가 우선
        cfg.webhook_url = os.environ.get("BLOG_WEBHOOK_URL", cfg.webhook_url)
        return cfg
