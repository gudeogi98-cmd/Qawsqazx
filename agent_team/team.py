"""에이전트 팀 실행.

구조:
    사용자 작업 ──▶ 리더(lead) ──delegate──▶ researcher / writer / reviewer ...
                     ▲    │                         │
                     │    └──save_note──▶ 공유 노트 ◀┘ (모든 팀원이 읽고 결과를 남김)
                     └──────── 결과 보고 ─────────────┘

- 리더는 Claude 도구 사용(tool use)으로 팀원에게 일을 맡깁니다. 한 번에 여러 명에게 맡기면 동시에 실행됩니다.
- 팀원은 일을 시작할 때 공유 노트(지금까지 팀이 만든 결과)를 받아 보고, 끝나면 결과를 노트에 남깁니다.
  그래서 writer는 researcher의 조사 결과를, reviewer는 writer의 초안을 보고 일할 수 있습니다.
- 리더가 더 맡길 일이 없다고 판단하면 최종 결과물을 작성하고 끝냅니다.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic

from .config import AgentSpec, TeamConfig

# 안전 분류기가 요청을 거절하면 서버가 다른 모델로 이어서 처리하도록 합니다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
MAX_PAUSE_CONTINUES = 5


class TeamError(RuntimeError):
    pass


@dataclass
class Note:
    author: str
    title: str
    content: str


class Board:
    """팀 공유 노트. 여러 에이전트가 동시에 쓰므로 잠금을 사용합니다."""

    def __init__(self) -> None:
        self._notes: list[Note] = []
        self._lock = threading.Lock()

    def add(self, author: str, title: str, content: str) -> None:
        with self._lock:
            self._notes.append(Note(author, title, content))

    @property
    def notes(self) -> list[Note]:
        with self._lock:
            return list(self._notes)

    def render(self) -> str:
        notes = self.notes
        if not notes:
            return "(아직 비어 있음)"
        return "\n\n".join(
            f"### [{i}] {n.author}: {n.title}\n{n.content}" for i, n in enumerate(notes, 1)
        )


@dataclass
class TeamResult:
    task: str
    final: str
    notes: list[Note]
    log: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def _text_of(message: Any) -> str:
    return "\n".join(b.text for b in message.content if b.type == "text").strip()


class Team:
    def __init__(
        self,
        cfg: TeamConfig,
        client: anthropic.Anthropic | None = None,
        on_event: Callable[[str], None] | None = None,
    ):
        cfg.validate()
        self.cfg = cfg
        # 자격 증명은 ANTHROPIC_API_KEY 등 환경에서 자동으로 읽습니다.
        self.client = client or anthropic.Anthropic()
        self.agents = {a.name: a for a in cfg.agents}
        self._on_event = on_event
        self._usage_lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        self.board = Board()
        self.log: list[str] = []
        self.input_tokens = 0
        self.output_tokens = 0

    # ---- 공통 ---------------------------------------------------------------

    def _event(self, text: str) -> None:
        self.log.append(text)
        if self._on_event:
            self._on_event(text)

    def _call(self, *, model: str, effort: str, system: str, messages: list, tools: list) -> Any:
        params: dict[str, Any] = dict(
            model=model,
            max_tokens=64000,
            system=system,
            messages=messages,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if tools:
            params["tools"] = tools
        with self.client.beta.messages.stream(**params) as stream:
            message = stream.get_final_message()
        with self._usage_lock:
            self.input_tokens += getattr(message.usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(message.usage, "output_tokens", 0) or 0
        return message

    # ---- 팀원 ---------------------------------------------------------------

    def _worker_system(self, spec: AgentSpec) -> str:
        teammates = "\n".join(
            f"- {a.name}: {a.role}" for a in self.cfg.agents if a.name != spec.name
        ) or "- (없음)"
        return (
            f"당신은 AI 에이전트 팀의 팀원 '{spec.name}'입니다.\n"
            f"역할: {spec.role}\n\n"
            f"작업 지침:\n{spec.instructions or '맡은 일을 성실하게 끝까지 수행하세요.'}\n\n"
            f"다른 팀원:\n{teammates}\n\n"
            "팀장(lead)이 일을 맡깁니다. 공유 노트에는 지금까지 팀원들이 남긴 결과가 있으니 "
            "필요한 내용을 활용하세요. 결과물은 다른 팀원이 바로 이어서 쓸 수 있게 완성된 형태로 작성하고, "
            "인사말이나 군더더기 없이 결과만 쓰세요. 질문으로 되묻지 말고, 정보가 부족하면 합리적으로 가정한 뒤 "
            f"그 가정을 적으세요.\n언어: {self.cfg.language}"
        )

    def run_agent(self, name: str, task: str) -> str:
        """팀원 한 명에게 일을 맡기고 결과를 공유 노트에 남깁니다."""
        spec = self.agents[name]
        self._event(f"▶ lead → {name}: {task}")
        messages: list = [
            {
                "role": "user",
                "content": f"[팀 공유 노트]\n{self.board.render()}\n\n[팀장이 맡긴 일]\n{task}",
            }
        ]
        tools = [WEB_SEARCH_TOOL] if spec.web_search else []

        for _ in range(MAX_PAUSE_CONTINUES + 1):
            message = self._call(
                model=spec.model or self.cfg.model,
                effort=spec.effort,
                system=self._worker_system(spec),
                messages=messages,
                tools=tools,
            )
            if message.stop_reason != "pause_turn":
                break
            # 웹 검색 등 서버 도구가 길어져 잠시 멈춘 경우: 그대로 이어서 진행
            messages.append({"role": "assistant", "content": message.content})

        if message.stop_reason == "refusal":
            raise TeamError(f"{name} 에이전트가 이 작업을 거절했습니다.")
        text = _text_of(message)
        if message.stop_reason == "max_tokens":
            text += "\n\n(주의: 출력 길이 한도에 걸려 결과가 잘렸습니다.)"
        if not text:
            raise TeamError(f"{name} 에이전트가 빈 결과를 냈습니다.")

        self.board.add(name, task[:80], text)
        self._event(f"✔ {name} 완료 ({len(text)}자)")
        return text

    # ---- 리더 ---------------------------------------------------------------

    def _lead_tools(self) -> list[dict]:
        names = list(self.agents)
        return [
            {
                "name": "delegate",
                "description": (
                    "팀원 한 명에게 일을 맡기고 그 결과를 받습니다. 결과는 공유 노트에도 자동으로 기록되어 "
                    "다른 팀원이 볼 수 있습니다. 서로 의존하지 않는 일은 한 번에 여러 개 호출하면 동시에 진행됩니다."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "enum": names, "description": "일을 맡길 팀원 이름"},
                        "task": {
                            "type": "string",
                            "description": "구체적인 작업 지시. 목표, 범위, 결과물 형식을 포함하세요.",
                        },
                    },
                    "required": ["agent", "task"],
                    "additionalProperties": False,
                },
                "strict": True,
                "eager_input_streaming": True,
            },
            {
                "name": "save_note",
                "description": "계획, 결정 사항, 요구 조건 등을 공유 노트에 적어 모든 팀원이 보게 합니다.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["title", "content"],
                    "additionalProperties": False,
                },
                "strict": True,
                "eager_input_streaming": True,
            },
        ]

    def _lead_system(self) -> str:
        roster = "\n".join(f"- {a.name}: {a.role}" for a in self.cfg.agents)
        return (
            "당신은 AI 에이전트 팀의 팀장(lead)입니다. 사용자의 작업을 계획하고, 팀원들에게 나눠 맡기고, "
            "결과를 검토해 최종 결과물을 완성합니다.\n\n"
            f"팀원:\n{roster}\n\n"
            "일하는 방식:\n"
            "1. 먼저 작업을 단계로 나누고, 필요하면 save_note로 계획과 요구 조건을 공유하세요.\n"
            "2. delegate로 각 단계를 가장 알맞은 팀원에게 맡기세요. 팀원은 공유 노트를 보고 일하므로 "
            "앞 단계의 결과를 지시에 다시 붙여 넣을 필요는 없습니다. 서로 의존하지 않는 일은 동시에 맡기세요.\n"
            "3. 결과물이 나오면 검토 담당이 있는 경우 검토를 맡기고, 지적 사항이 있으면 작성 담당에게 수정을 맡기세요. "
            "수정-검토는 최대 2번까지만 반복하세요.\n"
            "4. 충분히 완성되면 도구를 더 부르지 말고 최종 결과물 전체를 답변으로 작성하세요. "
            "요약이나 '위 결과를 참고하세요' 같은 말 대신 사용자가 바로 쓸 수 있는 완성본을 쓰세요.\n"
            "팀원의 결과를 그대로 믿지 말고 사용자의 요구와 맞는지 직접 확인하세요.\n"
            f"언어: {self.cfg.language}"
        )

    def _run_tool(self, block: Any) -> dict:
        result: dict = {"type": "tool_result", "tool_use_id": block.id}
        args = block.input if isinstance(block.input, dict) else {}
        try:
            if block.name == "delegate":
                agent, task = args.get("agent"), args.get("task")
                if agent not in self.agents or not isinstance(task, str) or not task.strip():
                    raise ValueError(f"잘못된 delegate 입력입니다. agent는 {list(self.agents)} 중 하나, task는 비어 있지 않은 문자열이어야 합니다.")
                result["content"] = self.run_agent(agent, task.strip())
            elif block.name == "save_note":
                title, content = args.get("title"), args.get("content")
                if not isinstance(title, str) or not isinstance(content, str):
                    raise ValueError("save_note에는 title과 content 문자열이 필요합니다.")
                self.board.add("lead", title, content)
                self._event(f"📝 lead 노트: {title}")
                result["content"] = "공유 노트에 기록했습니다."
            else:
                raise ValueError(f"알 수 없는 도구: {block.name}")
        except Exception as e:  # 팀원 실패를 리더에게 알려 다른 방법을 찾게 함
            self._event(f"✖ {block.name} 실패: {e}")
            result["content"] = f"오류: {e}"
            result["is_error"] = True
        return result

    def run(self, task: str) -> TeamResult:
        task = task.strip()
        if not task:
            raise ValueError("작업 내용을 입력해 주세요.")
        self._reset()
        self._event(f"■ 작업 시작: {task}")

        system = self._lead_system()
        tools = self._lead_tools()
        messages: list = [{"role": "user", "content": task}]
        final = ""

        for round_no in range(self.cfg.max_rounds + 1):
            last_round = round_no == self.cfg.max_rounds
            if last_round:
                messages.append({
                    "role": "user",
                    "content": "작업 횟수 한도에 도달했습니다. 도구를 더 부르지 말고 지금까지의 결과로 최종 결과물을 작성하세요.",
                })
            message = self._call(
                model=self.cfg.model,
                effort=self.cfg.lead_effort,
                system=system,
                messages=messages,
                tools=tools,
            )
            if message.stop_reason == "refusal":
                raise TeamError("리더 에이전트가 이 작업을 거절했습니다.")
            messages.append({"role": "assistant", "content": message.content})

            if message.stop_reason == "pause_turn":
                continue
            calls = [b for b in message.content if b.type == "tool_use"]
            if message.stop_reason == "tool_use" and calls and not last_round:
                # 여러 팀원에게 동시에 맡긴 경우 병렬로 실행하고, 결과는 한 메시지로 돌려줍니다.
                with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                    results = list(pool.map(self._run_tool, calls))
                messages.append({"role": "user", "content": results})
                continue

            final = _text_of(message)
            if message.stop_reason == "max_tokens":
                final += "\n\n(주의: 출력 길이 한도에 걸려 결과가 잘렸습니다.)"
            break

        if not final:
            raise TeamError("리더가 최종 결과물을 만들지 못했습니다.")
        self._event(f"■ 완료 (입력 {self.input_tokens:,} / 출력 {self.output_tokens:,} 토큰)")
        return TeamResult(
            task=task,
            final=final,
            notes=self.board.notes,
            log=list(self.log),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


def save_result(result: TeamResult, output_dir: str | Path, now: datetime | None = None) -> Path:
    """최종 결과와 팀 작업 기록을 Markdown 파일로 저장합니다."""
    now = now or datetime.now()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{now:%Y-%m-%d-%H%M%S}.md"
    n = 1
    while path.exists():
        path = out / f"{now:%Y-%m-%d-%H%M%S}-{n}.md"
        n += 1

    parts = [
        f"# 팀 작업 결과\n\n- 작업: {result.task}\n- 시각: {now:%Y-%m-%d %H:%M}\n"
        f"- 토큰: 입력 {result.input_tokens:,} / 출력 {result.output_tokens:,}\n",
        "## 최종 결과물\n\n" + result.final + "\n",
        "## 진행 기록\n\n" + "\n".join(f"- {line}" for line in result.log) + "\n",
        "## 팀 공유 노트\n",
    ]
    for i, note in enumerate(result.notes, 1):
        parts.append(f"<details><summary>[{i}] {note.author}: {note.title}</summary>\n\n{note.content}\n\n</details>\n")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path
