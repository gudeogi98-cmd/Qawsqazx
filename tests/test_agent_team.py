import threading
from types import SimpleNamespace as NS

import pytest

from agent_team.config import AgentSpec, TeamConfig
from agent_team.team import Team, TeamError, save_result


def text(t):
    return NS(type="text", text=t)


def tool_use(id, name, **inp):
    return NS(type="tool_use", id=id, name=name, input=inp)


def msg(*content, stop="end_turn"):
    return NS(content=list(content), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """리더 요청에는 미리 정한 응답을 순서대로, 팀원 요청에는 이름이 들어간 결과를 돌려줍니다."""

    def __init__(self, lead_script, worker_reply=None):
        self.lead_script = list(lead_script)
        self.worker_reply = worker_reply or (lambda name, params: msg(text(f"{name} 결과")))
        self.calls = []
        self.lock = threading.Lock()
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **params):
        params["messages"] = list(params["messages"])  # 실제 SDK처럼 호출 시점의 대화를 기록
        with self.lock:
            self.calls.append(params)
        system = params["system"]
        if system.startswith("당신은 AI 에이전트 팀의 팀장"):
            with self.lock:
                return FakeStream(self.lead_script.pop(0))
        name = system.split("'")[1]
        return FakeStream(self.worker_reply(name, params))


@pytest.fixture
def cfg():
    return TeamConfig()


def test_lead_delegates_and_workers_share_notes(cfg):
    client = FakeClient([
        msg(tool_use("t1", "save_note", title="계획", content="조사 후 작성"), stop="tool_use"),
        msg(tool_use("t2", "delegate", agent="researcher", task="자료 조사"), stop="tool_use"),
        msg(tool_use("t3", "delegate", agent="writer", task="초안 작성"), stop="tool_use"),
        msg(text("최종 완성본")),
    ])
    result = Team(cfg, client=client).run("블로그 글 써줘")

    assert result.final == "최종 완성본"
    assert [n.author for n in result.notes] == ["lead", "researcher", "writer"]
    # writer는 researcher가 남긴 노트를 보고 일함
    writer_call = next(c for c in client.calls if "'writer'" in c["system"])
    assert "researcher 결과" in writer_call["messages"][0]["content"]
    # 웹 검색은 researcher에게만
    researcher_call = next(c for c in client.calls if "'researcher'" in c["system"])
    assert researcher_call["tools"][0]["type"].startswith("web_search")
    assert "tools" not in writer_call
    # 리더에게 도구 결과가 tool_use_id와 함께 돌아감
    lead_last = client.calls[-1]["messages"]
    assert lead_last[-1]["content"][0]["tool_use_id"] == "t3"
    assert result.input_tokens == 10 * len(client.calls)


def test_parallel_delegation_returns_all_results_in_one_message(cfg):
    started = []
    barrier = threading.Barrier(2, timeout=5)

    def worker(name, params):
        started.append(name)
        barrier.wait()  # 둘이 동시에 실행되지 않으면 타임아웃
        return msg(text(f"{name} 결과"))

    client = FakeClient([
        msg(
            tool_use("a", "delegate", agent="researcher", task="A 조사"),
            tool_use("b", "delegate", agent="reviewer", task="B 검토"),
            stop="tool_use",
        ),
        msg(text("끝")),
    ], worker_reply=worker)
    Team(cfg, client=client).run("작업")

    results = client.calls[-1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert sorted(started) == ["researcher", "reviewer"]


def test_bad_tool_input_is_reported_as_error(cfg):
    client = FakeClient([
        msg(tool_use("x", "delegate", agent="nobody", task="뭔가"), stop="tool_use"),
        msg(text("대안으로 직접 마무리")),
    ])
    result = Team(cfg, client=client).run("작업")
    err = client.calls[-1]["messages"][-1]["content"][0]
    assert err["is_error"] is True
    assert result.final == "대안으로 직접 마무리"


def test_worker_failure_does_not_crash_team(cfg):
    client = FakeClient(
        [msg(tool_use("x", "delegate", agent="writer", task="쓰기"), stop="tool_use"), msg(text("완료"))],
        worker_reply=lambda name, p: msg(stop="refusal"),
    )
    result = Team(cfg, client=client).run("작업")
    assert client.calls[-1]["messages"][-1]["content"][0]["is_error"] is True
    assert result.final == "완료"


def test_worker_continues_after_pause_turn(cfg):
    replies = iter([msg(text("검색 중"), stop="pause_turn"), msg(text("조사 끝"))])
    client = FakeClient(
        [msg(tool_use("x", "delegate", agent="researcher", task="조사"), stop="tool_use"), msg(text("완료"))],
        worker_reply=lambda name, p: next(replies),
    )
    result = Team(cfg, client=client).run("작업")
    assert result.notes[0].content == "조사 끝"


def test_round_limit_forces_final_answer():
    cfg = TeamConfig(max_rounds=2)
    loop = [msg(tool_use(f"t{i}", "delegate", agent="writer", task="또"), stop="tool_use") for i in range(2)]
    client = FakeClient(loop + [msg(text("한도 내 최종본"))])
    result = Team(cfg, client=client).run("작업")
    assert result.final == "한도 내 최종본"
    assert "한도에 도달" in client.calls[-1]["messages"][-1]["content"]


def test_lead_refusal_raises(cfg):
    with pytest.raises(TeamError):
        Team(cfg, client=FakeClient([msg(stop="refusal")])).run("작업")


def test_config_load_and_validation(tmp_path):
    p = tmp_path / "team.yaml"
    p.write_text(
        "model: claude-opus-5-5\nagents:\n  - name: coder\n    role: 개발\n    effort: high\n",
        encoding="utf-8",
    )
    cfg = TeamConfig.load(p)
    assert [a.name for a in cfg.agents] == ["coder"]
    assert cfg.agents[0].effort == "high"
    assert TeamConfig.load(tmp_path / "missing.yaml").agents[0].name == "researcher"

    p.write_text("agents:\n  - name: Bad Name\n    role: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        TeamConfig.load(p)
    p.write_text("oops: 1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        TeamConfig.load(p)


def test_repo_team_yaml_is_valid():
    cfg = TeamConfig.load("team.yaml")
    assert {"researcher", "writer", "reviewer"} <= {a.name for a in cfg.agents}


def test_save_result(tmp_path):
    cfg = TeamConfig(agents=[AgentSpec(name="writer", role="작성")])
    client = FakeClient([
        msg(tool_use("t", "delegate", agent="writer", task="쓰기"), stop="tool_use"),
        msg(text("완성본")),
    ])
    result = Team(cfg, client=client).run("작업")
    path = save_result(result, tmp_path)
    body = path.read_text(encoding="utf-8")
    assert "완성본" in body and "writer 결과" in body and "lead → writer" in body
    assert save_result(result, tmp_path) != path  # 같은 시각이어도 덮어쓰지 않음
