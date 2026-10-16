"""Claude API로 블로그 글 생성."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic

from .config import Config


@dataclass
class Post:
    title: str
    slug: str
    summary: str
    body: str
    tags: list[str] = field(default_factory=list)


class GenerationError(RuntimeError):
    pass


POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "검색에 잘 걸리는 매력적인 글 제목"},
        "slug": {
            "type": "string",
            "description": "URL용 영문 소문자 kebab-case (예: how-to-start-running)",
        },
        "summary": {"type": "string", "description": "1~2문장 요약 (메타 설명용)"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "body": {
            "type": "string",
            "description": "Markdown 본문. 제목(H1)은 넣지 말고 ## 소제목부터 시작",
        },
    },
    "required": ["title", "slug", "summary", "tags", "body"],
    "additionalProperties": False,
}


def build_system_prompt(cfg: Config) -> str:
    return (
        "당신은 경험 많은 블로그 작가입니다. 독자가 끝까지 읽고 실제로 도움을 받는 글을 씁니다.\n"
        f"- 언어: {cfg.language}\n"
        f"- 어조: {cfg.tone}\n"
        f"- 본문 분량: 약 {cfg.target_length}자\n"
        "- 도입부에서 독자의 문제를 짚고, ## 소제목으로 구조화하고, 마지막에 핵심 정리를 넣으세요.\n"
        "- 확실하지 않은 수치나 사실은 지어내지 말고 일반적인 설명으로 표현하세요.\n"
        "- 태그는 3~6개로 하세요."
    )


def build_user_prompt(topic: str, keywords: str = "") -> str:
    prompt = f"다음 주제로 블로그 글을 작성해 주세요.\n\n주제: {topic}"
    if keywords:
        prompt += f"\n자연스럽게 포함할 키워드: {keywords}"
    return prompt


class ClaudeGenerator:
    def __init__(self, cfg: Config, client: anthropic.Anthropic | None = None):
        self.cfg = cfg
        # 자격 증명은 ANTHROPIC_API_KEY 등 환경에서 자동으로 읽습니다.
        self.client = client or anthropic.Anthropic()

    def generate(self, topic: str, keywords: str = "") -> Post:
        # 긴 출력이므로 스트리밍으로 받아 타임아웃을 피합니다.
        # fallbacks="default": 안전 분류기가 요청을 거절하면 서버가 다른 모델로 자동 재시도합니다.
        with self.client.beta.messages.stream(
            model=self.cfg.model,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            system=build_system_prompt(self.cfg),
            messages=[{"role": "user", "content": build_user_prompt(topic, keywords)}],
            output_config={
                "effort": self.cfg.effort,
                "format": {"type": "json_schema", "schema": POST_SCHEMA},
            },
            extra_body={"fallbacks": "default"},
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            raise GenerationError(f"모델이 이 주제의 작성을 거절했습니다: {topic}")
        if message.stop_reason == "max_tokens":
            raise GenerationError(f"출력이 max_tokens에서 잘렸습니다: {topic}")

        text = next((b.text for b in message.content if b.type == "text"), None)
        if text is None:
            raise GenerationError("응답에 텍스트가 없습니다.")
        return parse_post(text)


def parse_post(text: str) -> Post:
    try:
        data = json.loads(text)
        return Post(
            title=data["title"].strip(),
            slug=data["slug"].strip(),
            summary=data["summary"].strip(),
            body=data["body"].strip(),
            tags=[t.strip() for t in data.get("tags", []) if t.strip()],
        )
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        raise GenerationError(f"응답 JSON을 해석하지 못했습니다: {e}") from e
