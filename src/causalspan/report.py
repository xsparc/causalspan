"""Observed run metrics and an offline, parent-linked HTML timeline."""

import html
import math
from collections import Counter

from .reader import SpanRecord, select_trace

_MODEL_OPS = {"chat", "generate_content", "text_completion", "embeddings"}


def summarize(spans: list[SpanRecord]) -> dict:
    spans = select_trace(spans)
    ids = {s.span_id for s in spans}
    models = [
        s
        for s in spans
        if s.operation not in {"invoke_agent", "invoke_workflow", "execute_tool"}
        and (s.operation in _MODEL_OPS or "gen_ai.request.model" in s.attributes)
    ]
    missing = sum(
        any(
            key not in s.attributes
            for key in (
                "gen_ai.usage.input_tokens",
                "gen_ai.usage.output_tokens",
            )
        )
        for s in models
    )
    input_tokens = sum(s.attributes.get("gen_ai.usage.input_tokens", 0) for s in models)
    output_tokens = sum(s.attributes.get("gen_ai.usage.output_tokens", 0) for s in models)
    events = [event for s in spans for event in s.events]
    return {
        "trace_id": spans[0].trace_id,
        "spans": len(spans),
        "duration_ms": (max(s.end_ns for s in spans) - min(s.start_ns for s in spans)) / 1e6,
        "errors": sum(s.status == 2 for s in spans),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model_spans_missing_usage": missing,
        "missing_parents": sum(s.parent_id is not None and s.parent_id not in ids for s in spans),
        "dropped_items": sum(s.dropped for s in spans),
        "retries": sum(e["name"] == "causalspan.retry" for e in events),
        "policy_denials": sum(
            e["name"] == "causalspan.policy"
            and e["attributes"].get("causalspan.policy.allowed") is False
            for e in events
        ),
        "operations": dict(sorted(Counter(s.operation for s in spans).items())),
    }


def summarize_counts(spans: list[SpanRecord]) -> dict[str, int]:
    """Return only explicitly selected numeric counts for one trace."""
    summary = summarize(spans)
    return {
        key: summary[key]
        for key in (
            "spans",
            "errors",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "model_spans_missing_usage",
            "dropped_items",
            "retries",
            "policy_denials",
        )
    }


def compare(before: list[SpanRecord], after: list[SpanRecord]) -> dict:
    left, right = summarize(before), summarize(after)
    return {
        "before": left,
        "after": right,
        "delta": {key: right[key] - left[key] for key in left if type(left[key]) in {int, float}},
    }


def evaluate(
    spans: list[SpanRecord],
    *,
    max_tokens: int | None = None,
    max_errors: int = 0,
    max_duration_ms: float | None = None,
) -> dict:
    limits = {"total_tokens": max_tokens, "errors": max_errors, "duration_ms": max_duration_ms}
    for limit in limits.values():
        if limit is not None and (
            type(limit) not in {int, float}
            or (type(limit) is float and not math.isfinite(limit))
            or limit < 0
        ):
            raise ValueError("thresholds must be finite nonnegative numbers")
    summary = summarize(spans)
    failures = [
        f"{key} exceeds threshold"
        for key, limit in limits.items()
        if limit is not None and summary[key] > limit
    ]
    if max_tokens is not None and summary["model_spans_missing_usage"]:
        failures.append("model token usage is incomplete")
    if summary["missing_parents"] or summary["dropped_items"]:
        failures.append("trace is incomplete")
    return {"passed": not failures, "failures": failures, "summary": summary, "limits": limits}


def timeline_html(spans: list[SpanRecord], *, hide_identifiers: bool = False) -> str:
    summary = summarize(spans)
    ids = {s.span_id for s in spans}
    children = {}
    for span in sorted(spans, key=lambda s: (s.start_ns, s.span_id)):
        parent = span.parent_id if span.parent_id in ids else None
        children.setdefault(parent, []).append(span)
    ordered = []
    stack = [(s, 0) for s in reversed(children.get(None, []))]
    while stack:
        span, depth = stack.pop()
        ordered.append((span, depth))
        stack.extend((s, depth + 1) for s in reversed(children.get(span.span_id, [])))
    start = min(s.start_ns for s in spans)
    duration = max(max(s.end_ns for s in spans) - start, 1)
    rows = []
    for index, (span, depth) in enumerate(ordered, 1):
        offset = 100 * (span.start_ns - start) / duration
        width = max(0.15, 100 * (span.end_ns - span.start_ns) / duration)
        label = f"Span {index}" if hide_identifiers else html.escape(span.name)
        missing = "missing parent" if span.parent_id and span.parent_id not in ids else ""
        details = " · ".join(
            value
            for value in ("" if hide_identifiers else html.escape(span.span_id), missing)
            if value
        )
        state = {0: "unset", 1: "ok", 2: "error"}[span.status]
        rows.append(
            f'<tr><td style="padding-left:{min(depth, 20) * 16 + 16}px">{label}'
            f"<small>{details}</small></td>"
            f'<td><div class="track"><div class="bar {state}" '
            f'style="left:{offset:.4f}%;width:{width:.4f}%"></div></div></td>'
            f"<td>{span.duration_ms:.3f} ms</td><td>{state}</td></tr>"
        )
    metrics = "".join(
        f'<div class="metric"><strong>{summary[key]}</strong><span>{label}</span></div>'
        for key, label in (
            ("spans", "spans"),
            ("total_tokens", "observed tokens"),
            ("errors", "error spans"),
            ("retries", "retry events"),
        )
    )
    if hide_identifiers:
        trace_label = (
            "<small>Trace and span identifiers hidden. Review metrics before sharing.</small>"
        )
        span_header = "SPAN"
    else:
        trace_label = f"<small>Trace {html.escape(summary['trace_id'])}</small>"
        span_header = "OPERATION / SPAN ID"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>CausalSpan · Run timeline</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#10151b;
color:#e6edf3;font:15px system-ui,sans-serif}}
main{{max-width:1200px;margin:48px auto;padding:0 24px}}
.eyebrow{{color:#5ee0b8;letter-spacing:.14em;font-size:12px}}h1{{font-size:36px;margin:12px 0}}
p,small{{color:#9aa9b8}}small{{display:block;font:11px monospace;margin-top:6px}}
.metrics{{display:flex;gap:16px;margin:32px 0;flex-wrap:wrap}}.metric{{background:#1b242e;
padding:20px 28px;border-radius:8px;flex:1}}.metric strong{{display:block;font-size:28px}}
.metric span{{color:#9aa9b8}}.table{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;
background:#151d26}}th,td{{text-align:left;padding:16px;border-bottom:1px solid #293544}}
th{{font-size:12px;color:#9aa9b8}}td:first-child{{max-width:420px;overflow-wrap:anywhere}}
td:nth-child(2){{width:40%;min-width:200px}}.track{{height:12px;position:relative;background:#243140;
overflow:hidden;border-radius:4px}}.bar{{position:absolute;height:100%;border-radius:4px}}
.ok,.unset{{background:#4bbaa0}}.error{{background:#ed7a7a}}
footer{{margin:24px 0;color:#9aa9b8;font-size:13px}}
</style></head><body><main><div class="eyebrow">CAUSALSPAN / LOCAL TRACE</div>
<h1>Follow the run.</h1><p>Parent-linked spans · {summary["duration_ms"]:.3f} ms elapsed</p>
{trace_label}<section class="metrics">{metrics}</section>
<div class="table"><table><thead><tr><th>{span_header}</th><th>RELATIVE TIMING</th>
<th>DURATION</th><th>STATUS</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<footer>Missing parents: {summary["missing_parents"]} · Model spans missing usage:
{summary["model_spans_missing_usage"]} · Dropped items: {summary["dropped_items"]}.<br>
Tokens are observed model counters. Error counts include propagation through parent spans.
This report contains no tool payloads, scripts, or external assets.</footer>
</main></body></html>"""
