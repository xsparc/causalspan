"""A synthetic demonstration that never calls a model or remote tool."""

import json
from pathlib import Path

from .reader import load_traces
from .replay import Replay
from .report import compare, timeline_html
from .tracing import AgentTracer


def create_demo(directory: str | Path) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = ("baseline.otlp.jsonl", "candidate.otlp.jsonl", "timeline.html", "calls.json")
    if any((directory / name).exists() for name in names):
        raise ValueError("demo output already exists; choose a new directory")
    for name, input_tokens, output_tokens in ((names[0], 120, 60), (names[1], 95, 35)):
        with AgentTracer(directory / name, service_name="weather-demo", capture_payloads=True) as t:
            with t.agent("travel-planner") as run:
                t.policy(run, name="synthetic-tools-only", allowed=True)
                with t.agent("weather-assistant"):
                    with t.model("example-model", provider="example") as model:
                        t.usage(model, input_tokens=input_tokens, output_tokens=output_tokens)
                        if input_tokens == 120:
                            t.retry(model, attempt=1)
                    t.call_tool(
                        "weather", lambda city: {"city": city, "celsius": 21}, {"city": "Sydney"}
                    )
    calls = [{"name": "weather", "arguments": {"city": "Sydney"}}]
    (directory / "calls.json").write_text(json.dumps(calls, indent=2) + "\n", encoding="utf-8")
    before, after = load_traces(directory / names[0]), load_traces(directory / names[1])
    (directory / "timeline.html").write_text(timeline_html(after), encoding="utf-8")
    replay = Replay(directory / names[0])
    result = replay.call("weather", {"city": "Sydney"})
    replay.assert_complete()
    return {"comparison": compare(before, after), "replayed_result": result}
