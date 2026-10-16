"""명령줄 인터페이스.

    python -m blog_auto run [--limit N] [--publish] [--retry-failed]
    python -m blog_auto write "주제" [--keywords "..."] [--publish]
    python -m blog_auto publish [파일 ...]
    python -m blog_auto status
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from . import storage
from .config import Config
from .generator import ClaudeGenerator
from .pipeline import publish_drafts, run_batch
from .topics import FAILED, load_topics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blog_auto", description="AI 블로그 자동화")
    parser.add_argument("-c", "--config", default="config.yaml", help="설정 파일 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="topics.csv의 대기 주제를 일괄 처리")
    p_run.add_argument("--limit", type=int, help="이번에 처리할 글 수 (기본: posts_per_run)")
    p_run.add_argument("--publish", action="store_true", help="생성 즉시 발행")
    p_run.add_argument("--retry-failed", action="store_true", help="실패한 주제도 다시 시도")

    p_write = sub.add_parser("write", help="주제 하나로 글 생성")
    p_write.add_argument("topic")
    p_write.add_argument("--keywords", default="")
    p_write.add_argument("--publish", action="store_true", help="생성 즉시 발행")

    p_pub = sub.add_parser("publish", help="drafts/의 초안 발행 (파일 미지정 시 전부)")
    p_pub.add_argument("files", nargs="*")

    sub.add_parser("status", help="주제 처리 현황 보기")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load(args.config)

    if args.command == "run":
        done = run_batch(
            cfg,
            ClaudeGenerator(cfg),
            limit=args.limit,
            publish_now=args.publish or None,
            retry_failed=args.retry_failed,
        )
        return 1 if any(t.status == FAILED for t in done) else 0

    if args.command == "write":
        post = ClaudeGenerator(cfg).generate(args.topic, args.keywords)
        path = storage.save_draft(post, cfg.drafts_dir)
        if args.publish or cfg.auto_publish:
            path = storage.publish(path, cfg.posts_dir, cfg.webhook_url)
        print(path)
        return 0

    if args.command == "publish":
        published = publish_drafts(cfg, args.files)
        if not published:
            print("발행할 초안이 없습니다.")
        return 0

    if args.command == "status":
        topics = load_topics(cfg.topics_file)
        counts = Counter(t.status for t in topics)
        print(f"전체 {len(topics)}개: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        for t in topics:
            print(f"  [{t.status:9}] {t.topic}" + (f"  → {t.file}" if t.file else ""))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
