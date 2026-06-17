"""Offline eval harness for InfraPilot.

For each scenario we stub the tool layer with canned outputs (so the agent runs
end-to-end without touching real infra), run the agent, then use Claude as a
judge to score the diagnosis against the expected root cause.

    python -m evals.run_evals          # from the agent/ directory
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic
import yaml

# Import the package and monkeypatch its tool dispatcher.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import infrapilot.tools as tools  # noqa: E402
from infrapilot.agent import diagnose  # noqa: E402
from infrapilot.config import config  # noqa: E402

JUDGE_PROMPT = """You are grading an SRE agent's diagnosis.

SYMPTOM:
{symptom}

EXPECTED ROOT CAUSE (rubric):
{expects}

AGENT'S ANSWER:
{answer}

Did the agent correctly identify the root cause and propose a sensible fix that
matches the rubric? Reply with a single line: "PASS: <reason>" or "FAIL: <reason>".
"""


def _stub_dispatch(fixtures: dict[str, str]):
    def dispatch(name: str, args: dict) -> str:  # noqa: ARG001
        return fixtures.get(name, f"(no fixture for {name})")

    return dispatch


def judge(client: anthropic.Anthropic, symptom: str, expects: str, answer: str) -> str:
    resp = client.messages.create(
        model=config.model,
        max_tokens=500,
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    symptom=symptom, expects=expects.strip(), answer=answer
                ),
            }
        ],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def main() -> int:
    scenarios = yaml.safe_load(
        (Path(__file__).parent / "scenarios.yaml").read_text()
    )
    client = anthropic.Anthropic()
    passed = 0
    for s in scenarios:
        tools.dispatch = _stub_dispatch(s["fixtures"])  # monkeypatch
        answer = diagnose(s["symptom"])
        verdict = judge(client, s["symptom"], s["expects"], answer)
        ok = verdict.upper().startswith("PASS")
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {s['name']}: {verdict}")

    print(f"\n{passed}/{len(scenarios)} scenarios passed")
    return 0 if passed == len(scenarios) else 1


if __name__ == "__main__":
    os.environ.setdefault("INFRAPILOT_EFFORT", "medium")  # cheaper for evals
    raise SystemExit(main())
