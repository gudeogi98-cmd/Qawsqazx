"""팀 설정 로딩: team.yaml (없으면 기본 팀 구성)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class AgentSpec:
    """팀원 한 명(에이전트)의 정의."""

    name: str  # 리더가 일을 맡길 때 부르는 이름 (영문 소문자 권장)
    role: str  # 한 줄 역할 설명. 리더가 누구에게 맡길지 고를 때 봅니다.
    instructions: str = ""  # 이 에이전트의 상세 작업 지침
    effort: str = "medium"  # low / medium / high / xhigh / max
    web_search: bool = False  # True면 웹 검색 도구 사용
    model: str = ""  # 비우면 팀 기본 모델


DEFAULT_AGENTS = [
    AgentSpec(
        name="researcher",
        role="자료 조사 담당. 사실, 수치, 사례, 출처를 찾아 정리합니다.",
        instructions=(
            "맡은 주제에 대해 핵심 사실과 근거를 조사해 글머리표로 정리하세요. "
            "웹 검색을 쓸 수 있으면 출처(URL)를 함께 적고, 확인하지 못한 내용은 '미확인'이라고 표시하세요."
        ),
        effort="medium",
        web_search=True,
    ),
    AgentSpec(
        name="writer",
        role="작성 담당. 조사 자료와 지시를 바탕으로 완성도 높은 결과물을 씁니다.",
        instructions=(
            "공유 노트의 조사 자료를 근거로 결과물을 작성하세요. 자료에 없는 사실은 지어내지 마세요. "
            "검토 의견이 있으면 하나도 빠짐없이 반영하고, 무엇을 고쳤는지 끝에 짧게 적으세요."
        ),
        effort="medium",
    ),
    AgentSpec(
        name="reviewer",
        role="검토 담당. 결과물의 오류, 빠진 내용, 개선점을 찾아 구체적으로 지적합니다.",
        instructions=(
            "결과물을 꼼꼼히 검토해 사실 오류, 논리 비약, 빠진 내용, 읽기 어려운 부분을 번호 목록으로 지적하세요. "
            "각 항목에 고칠 방법을 함께 적으세요. 고칠 것이 없으면 첫 줄에 '승인'이라고만 쓰세요."
        ),
        effort="medium",
    ),
]


@dataclass
class TeamConfig:
    model: str = "claude-opus-5-5"
    lead_effort: str = "high"  # 리더(팀장)의 생각 깊이
    language: str = "한국어"
    max_rounds: int = 15  # 리더가 도구를 부를 수 있는 최대 횟수(무한 루프 방지)
    output_dir: str = "team_outputs"
    agents: list[AgentSpec] = field(default_factory=lambda: list(DEFAULT_AGENTS))

    @classmethod
    def load(cls, path: str | Path = "team.yaml") -> "TeamConfig":
        path = Path(path)
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"team.yaml에 알 수 없는 키가 있습니다: {', '.join(sorted(unknown))}")

        raw_agents = data.pop("agents", None)
        cfg = cls(**data)
        if raw_agents is not None:
            agent_keys = {f.name for f in fields(AgentSpec)}
            agents = []
            for item in raw_agents:
                bad = set(item) - agent_keys
                if bad:
                    raise ValueError(f"에이전트 설정에 알 수 없는 키: {', '.join(sorted(bad))}")
                agents.append(AgentSpec(**item))
            cfg.agents = agents
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.agents:
            raise ValueError("팀원이 최소 한 명은 있어야 합니다.")
        names = [a.name for a in self.agents]
        if len(set(names)) != len(names):
            raise ValueError("에이전트 이름이 중복됩니다.")
        for name in names:
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
                raise ValueError(f"에이전트 이름은 영문 소문자/숫자/-/_ 로 써 주세요: {name!r}")
