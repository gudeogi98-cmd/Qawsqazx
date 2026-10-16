import json

import pytest

from blog_auto import storage
from blog_auto.config import Config
from blog_auto.generator import GenerationError, Post, parse_post
from blog_auto.pipeline import publish_drafts, run_batch
from blog_auto.topics import load_topics


class FakeGenerator:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.calls = []

    def generate(self, topic, keywords=""):
        self.calls.append(topic)
        if topic in self.fail_on:
            raise GenerationError("boom")
        return Post(
            title=f"{topic} 제목",
            slug="My Post: Hello World!",
            summary="요약",
            body="## 소제목\n\n본문",
            tags=["태그1", "태그2"],
        )


@pytest.fixture
def cfg(tmp_path):
    topics = tmp_path / "topics.csv"
    topics.write_text(
        "topic,keywords,status,file,updated_at\n"
        "주제A,키워드,pending,,\n"
        "주제B,,pending,,\n"
        "주제C,,failed,,\n",
        encoding="utf-8",
    )
    return Config(
        topics_file=str(topics),
        drafts_dir=str(tmp_path / "drafts"),
        posts_dir=str(tmp_path / "posts"),
    )


def test_slugify():
    assert storage.slugify("My Post: Hello World!") == "my-post-hello-world"
    assert storage.slugify("한글만") == "post"


def test_parse_post_rejects_bad_json():
    with pytest.raises(GenerationError):
        parse_post("not json")
    post = parse_post(json.dumps({"title": " T ", "slug": "s", "summary": "x", "body": "b", "tags": ["a", " "]}))
    assert post.title == "T" and post.tags == ["a"]


def test_run_batch_creates_drafts_and_updates_csv(cfg, tmp_path):
    gen = FakeGenerator()
    done = run_batch(cfg, gen, limit=5)

    assert gen.calls == ["주제A", "주제B"]  # failed는 기본적으로 건너뜀
    assert [t.status for t in done] == ["drafted", "drafted"]
    drafts = [tmp_path / "drafts" / f"{t.file.rsplit('/', 1)[-1]}" for t in done]
    assert drafts[0].name.endswith("my-post-hello-world.md")
    assert drafts[1].name.endswith("my-post-hello-world-2.md")
    assert all(d.exists() for d in drafts)

    meta, body = storage.read_front_matter(drafts[0])
    assert meta["tags"] == ["태그1", "태그2"] and body.startswith("## 소제목")

    statuses = {t.topic: t.status for t in load_topics(cfg.topics_file)}
    assert statuses == {"주제A": "drafted", "주제B": "drafted", "주제C": "failed"}


def test_run_batch_limit_publish_and_failure(cfg, tmp_path):
    done = run_batch(cfg, FakeGenerator(fail_on={"주제A"}), limit=2, publish_now=True)
    assert [t.status for t in done] == ["failed", "published"]
    assert len(list((tmp_path / "posts").glob("*.md"))) == 1
    assert not list((tmp_path / "drafts").glob("*.md"))

    gen = FakeGenerator()
    run_batch(cfg, gen, limit=5, retry_failed=True)
    assert gen.calls == ["주제A", "주제C"]


def test_publish_drafts_moves_files_and_sends_webhook(cfg, tmp_path, monkeypatch):
    run_batch(cfg, FakeGenerator(), limit=1)
    sent = []
    monkeypatch.setattr(storage, "send_webhook", lambda url, payload: sent.append((url, payload)))
    cfg.webhook_url = "https://example.invalid/hook"

    published = publish_drafts(cfg)

    assert len(published) == 1 and published[0].exists()
    assert sent[0][1]["title"] == "주제A 제목" and "본문" in sent[0][1]["body"]
    assert load_topics(cfg.topics_file)[0].status == "published"


def test_webhook_failure_keeps_draft(cfg, tmp_path, monkeypatch):
    run_batch(cfg, FakeGenerator(), limit=1)

    def boom(url, payload):
        raise RuntimeError("down")

    monkeypatch.setattr(storage, "send_webhook", boom)
    cfg.webhook_url = "https://example.invalid/hook"
    with pytest.raises(RuntimeError):
        publish_drafts(cfg)
    assert len(list((tmp_path / "drafts").glob("*.md"))) == 1
    assert load_topics(cfg.topics_file)[0].status == "drafted"
