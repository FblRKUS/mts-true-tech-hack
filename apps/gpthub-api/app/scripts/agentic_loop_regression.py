from __future__ import annotations

from app.agents.output_contract import parse_file_map
from app.agents.nodes.qa_tester import _build_acceptance_feedback
from app.agents.supervisor import _allowed_agents_for_profile, _infer_task_profile, _qa_acceptance_passed


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_output_contract_parser() -> None:
    payload = """```json
{
  "main.py": "print('ok')",
  "requirements.txt": "fastapi==0.109.0"
}
```"""
    files = parse_file_map(payload)
    _assert(files["main.py"].strip() == "print('ok')", "main.py content mismatch")
    _assert("requirements.txt" in files, "requirements.txt missing")


def test_qa_acceptance_rejects_hello_world() -> None:
    state = {"user_request": "Сделай игру змейка на python"}
    workspace = {"main.py": 'return {"message": "Hello World"}'}
    passed, feedback = _build_acceptance_feedback(state=state, workspace=workspace)
    _assert(not passed, "hello-world fallback should fail acceptance")
    _assert(feedback.get("acceptance_passed") is False, "acceptance flag must be false")


def test_qa_acceptance_snake_positive() -> None:
    state = {"user_request": "Сделай игру змейка на python"}
    workspace = {
        "main.py": """
import pygame

snake = [(5, 5)]
food = (10, 10)
print('snake game boot')
""",
    }
    passed, feedback = _build_acceptance_feedback(state=state, workspace=workspace)
    _assert(passed, "snake-like implementation should pass heuristic acceptance")
    _assert(feedback.get("execution_passed") is True, "execution flag must be true")
    _assert(feedback.get("acceptance_passed") is True, "acceptance flag must be true")


def test_task_profile_routing_policy() -> None:
    profile = _infer_task_profile("Сделай игру змейка на python")
    _assert(profile == "script_game", "snake request should map to script_game")
    allowed = _allowed_agents_for_profile(profile)
    _assert("backend_dev" in allowed, "backend_dev must be allowed for script_game")
    _assert("frontend_dev" not in allowed, "frontend_dev must be disallowed for script_game")


def test_qa_gate_requires_both_dimensions() -> None:
    state_ok = {"qa_feedback": [{"execution_passed": True, "acceptance_passed": True}]}
    state_bad = {"qa_feedback": [{"execution_passed": True, "acceptance_passed": False}]}
    _assert(_qa_acceptance_passed(state_ok), "qa gate should pass only when both dimensions are true")
    _assert(not _qa_acceptance_passed(state_bad), "qa gate should fail when acceptance is false")


def main() -> None:
    test_output_contract_parser()
    test_qa_acceptance_rejects_hello_world()
    test_qa_acceptance_snake_positive()
    test_task_profile_routing_policy()
    test_qa_gate_requires_both_dimensions()
    print("agentic_loop_regression: all checks passed")


if __name__ == "__main__":
    main()
