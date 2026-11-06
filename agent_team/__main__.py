"""명령줄 인터페이스.

    python -m agent_team "작업 내용"          # 팀에게 일을 맡기고 결과를 team_outputs/에 저장
    python -m agent_team --task-file task.txt  # 긴 작업 지시는 파일로
    python -m agent_team --list                # 팀 구성 보기
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import TeamConfig
from .team import Team, TeamError, save_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_team", description="서로 협업하는 AI 에이전트 팀")
    parser.add_argument("task", nargs="?", default="", help="팀에게 맡길 작업")
    parser.add_argument("--task-file", help="작업 지시가 담긴 텍스트 파일")
    parser.add_argument("-c", "--config", default="team.yaml", help="팀 설정 파일 경로")
    parser.add_argument("-o", "--output-dir", help="결과 저장 폴더 (기본: 설정의 output_dir)")
    parser.add_argument("--list", action="store_true", help="팀 구성만 출력")
    args = parser.parse_args(argv)

    cfg = TeamConfig.load(args.config)

    if args.list:
        print(f"모델: {cfg.model} / 리더 effort: {cfg.lead_effort}")
        print("lead: 팀장. 계획을 세우고 일을 나눠 맡긴 뒤 최종 결과물을 완성합니다.")
        for a in cfg.agents:
            extra = " [웹 검색]" if a.web_search else ""
            print(f"{a.name}: {a.role}{extra}")
        return 0

    task = args.task
    if args.task_file:
        task = Path(args.task_file).read_text(encoding="utf-8")
    if not task.strip():
        parser.error("작업 내용을 입력하거나 --task-file을 지정해 주세요.")

    team = Team(cfg, on_event=lambda line: print(line, file=sys.stderr, flush=True))
    try:
        result = team.run(task)
    except TeamError as e:
        print(f"실패: {e}", file=sys.stderr)
        return 1

    path = save_result(result, args.output_dir or cfg.output_dir)
    print(result.final)
    print(f"\n저장됨: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
