import pytest

from causalspan import AgentTracer


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "run.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.agent("planner"):
            with tracer.model("model", provider="example") as model:
                tracer.usage(model, input_tokens=10, output_tokens=5)
            tracer.call_tool("add", lambda a, b: {"sum": a + b}, {"a": 2, "b": 3})
    return path
