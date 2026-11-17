"""Run from the repository after installing the package. No network or API keys."""

from pathlib import Path

from causalspan import AgentTracer
from causalspan.replay import Replay

directory = Path("traces")
directory.mkdir(exist_ok=True)
path = directory / "example.otlp.jsonl"
if path.exists():
    raise SystemExit("Choose a fresh output file before running this example again.")

with AgentTracer(path, capture_payloads=True) as tracer:
    with tracer.agent("calculator"):
        with tracer.model("example-model", provider="example") as model:
            tracer.usage(model, input_tokens=12, output_tokens=5)
        value = tracer.call_tool("add", lambda a, b: {"sum": a + b}, {"a": 2, "b": 3})

recording = Replay(path)
assert recording.call("add", {"a": 2, "b": 3}) == value
recording.assert_complete()
print("Recorded and replayed a synthetic tool call.")
