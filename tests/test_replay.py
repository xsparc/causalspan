import asyncio
import json

import pytest

from causalspan import AgentTracer
from causalspan.replay import RecordedToolError, Replay, ReplayError


def test_replay_and_exhaustion(recording):
    replay = Replay(recording)
    assert replay.call("add", {"b": 3, "a": 2}) == {"sum": 5}
    replay.assert_complete()
    with pytest.raises(ReplayError, match="exhausted"):
        replay.call("add", {"a": 2, "b": 3})


def test_mismatch_does_not_consume_call(recording):
    replay = Replay(recording)
    with pytest.raises(ReplayError, match="do not match"):
        replay.call("add", {"a": 999, "b": 3})
    with pytest.raises(ReplayError, match="unused"):
        replay.assert_complete()
    assert replay.call("add", {"a": 2, "b": 3}) == {"sum": 5}


@pytest.mark.parametrize("capture,arguments", [(False, {"a": 2}), (True, {"token": "PRIVATE"})])
def test_unavailable_or_redacted_payload_rejected(tmp_path, capture, arguments):
    path = tmp_path / "run.jsonl"
    with AgentTracer(path, capture_payloads=capture) as tracer:
        tracer.call_tool("echo", lambda **kwargs: kwargs, arguments)
    with pytest.raises(ReplayError):
        Replay(path).call("echo", arguments)


def test_failed_recording_raises_safe_error(tmp_path):
    path = tmp_path / "error.jsonl"

    def fail():
        raise RuntimeError("PRIVATE")

    with AgentTracer(path, capture_payloads=True) as tracer, pytest.raises(RuntimeError):
        tracer.call_tool("fail", fail, {})
    replay = Replay(path)
    with pytest.raises(RecordedToolError, match="recorded tool call failed"):
        replay.call("fail", {})
    replay.assert_complete()


def test_multiple_calls_keep_order_and_return_new_data(tmp_path):
    path = tmp_path / "two.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.agent("run"):
            for value in [1, 2]:
                tracer.call_tool("step", lambda x: {"x": x}, {"x": value})
    replay = Replay(path)
    assert replay.call("step", {"x": 1}) == {"x": 1}
    assert replay.call("step", {"x": 2}) == {"x": 2}
    replay.assert_complete()


def test_overlapping_tool_calls_are_rejected(tmp_path):
    path = tmp_path / "overlap.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.tool("outer"):
            tracer.call_tool("inner", lambda: 1, {})
    with pytest.raises(ReplayError, match="overlapping"):
        Replay(path)


def test_replay_does_not_execute_code_in_payload(tmp_path):
    path = tmp_path / "code.jsonl"
    text = "__import__('os').system('THIS MUST REMAIN TEXT')"
    with AgentTracer(path, capture_payloads=True) as tracer:
        tracer.call_tool("text", lambda: {"content": text}, {})
    assert Replay(path).call("text", {}) == {"content": text}


def flatten_clock(path, *, omit_order=False):
    documents = [json.loads(line) for line in path.read_text().splitlines()]
    for document in documents:
        for resource in document["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    span["startTimeUnixNano"] = span["endTimeUnixNano"] = "1000"
                    if omit_order:
                        span["attributes"] = [
                            a
                            for a in span["attributes"]
                            if not a["key"].startswith("causalspan.tool.")
                        ]
    # Reverse file order as well, proving replay uses invocation sequence.
    path.write_text("\n".join(json.dumps(d) for d in reversed(documents)), encoding="utf-8")


def test_tied_timestamps_use_explicit_call_sequence(tmp_path):
    path = tmp_path / "coarse.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.agent("run"):
            for value in [1, 2, 3]:
                tracer.call_tool("step", lambda x: x, {"x": value})
    flatten_clock(path)
    replay = Replay(path)
    assert [replay.call("step", {"x": x}) for x in [1, 2, 3]] == [1, 2, 3]
    replay.assert_complete()


def test_external_tied_timestamps_are_ambiguous(tmp_path):
    path = tmp_path / "external.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.agent("run"):
            for value in [1, 2]:
                tracer.call_tool("step", lambda x: x, {"x": value})
    flatten_clock(path, omit_order=True)
    with pytest.raises(ReplayError, match="ambiguous"):
        Replay(path)


def test_nested_tool_parentage_rejects_zero_duration_overlap(tmp_path):
    path = tmp_path / "nested.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.tool("outer"), tracer.agent("delegate"):
            tracer.call_tool("inner", lambda: 1, {})
    flatten_clock(path, omit_order=True)
    with pytest.raises(ReplayError, match="overlapping"):
        Replay(path)


@pytest.mark.parametrize("value", [True, -1, "one"])
def test_invalid_sequence_is_rejected(tmp_path, value):
    path = tmp_path / "bad-order.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        with tracer.tool("bad") as span:
            span.set_attribute("causalspan.tool.sequence", value)
    with pytest.raises(ReplayError, match="ordering"):
        Replay(path)


def test_concurrent_siblings_rejected_even_with_coarse_clock(tmp_path):
    path = tmp_path / "siblings.jsonl"

    async def child(tracer, name):
        with tracer.tool(name):
            await asyncio.sleep(0)

    async def run(tracer):
        with tracer.agent("run"):
            await asyncio.gather(child(tracer, "one"), child(tracer, "two"))

    with AgentTracer(path) as tracer:
        asyncio.run(run(tracer))
    flatten_clock(path)
    with pytest.raises(ReplayError, match="overlapping"):
        Replay(path)
