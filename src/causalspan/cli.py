"""Offline command-line entry point."""

import argparse
import json
import sys
from pathlib import Path

from ._files import open_private
from .demo import create_demo
from .reader import MAX_FILE_BYTES, load_traces, select_trace
from .replay import Replay
from .report import compare, evaluate, summarize, timeline_html


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causalspan", description="Inspect local OTLP agent traces"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "timeline", "evaluate", "replay"):
        child = commands.add_parser(command)
        child.add_argument("trace_file", type=Path)
        child.add_argument("--trace-id")
        if command == "timeline":
            child.add_argument("--output", type=Path, required=True)
            child.add_argument(
                "--hide-identifiers",
                action="store_true",
                help="omit span names, span IDs, and the trace ID from the report",
            )
        elif command == "evaluate":
            child.add_argument("--max-tokens", type=int)
            child.add_argument("--max-errors", type=int, default=0)
            child.add_argument("--max-duration-ms", type=float)
        elif command == "replay":
            child.add_argument(
                "--calls", type=Path, required=True, help="JSON array of {name, arguments} calls"
            )
    diff = commands.add_parser("compare")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    diff.add_argument("--before-trace-id")
    diff.add_argument("--after-trace-id")
    demo = commands.add_parser("demo")
    demo.add_argument("--output-dir", type=Path, default=Path("traces/demo"))
    return parser


def _calls(path: Path) -> list[dict]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("replay request exceeds the size limit")
    calls = json.loads(raw)
    if not isinstance(calls, list) or not all(
        isinstance(c, dict)
        and isinstance(c.get("name"), str)
        and isinstance(c.get("arguments"), dict)
        and set(c) == {"name", "arguments"}
        for c in calls
    ):
        raise ValueError("expected an array of tool calls with name and arguments")
    return calls


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "demo":
            result = create_demo(args.output_dir)
        elif args.command == "compare":
            result = compare(
                select_trace(load_traces(args.before), args.before_trace_id),
                select_trace(load_traces(args.after), args.after_trace_id),
            )
        elif args.command == "replay":
            replay = Replay(args.trace_file, trace_id=args.trace_id)
            result = {
                "results": [replay.call(c["name"], c["arguments"]) for c in _calls(args.calls)]
            }
            replay.assert_complete()
        else:
            spans = load_traces(args.trace_file)
            if args.command == "inspect" and args.trace_id is None:
                result = {
                    "runs": [
                        summarize(select_trace(spans, trace_id))
                        for trace_id in sorted({s.trace_id for s in spans})
                    ]
                }
            else:
                spans = select_trace(spans, args.trace_id)
                if args.command == "inspect":
                    result = summarize(spans)
                elif args.command == "evaluate":
                    result = evaluate(
                        spans,
                        max_tokens=args.max_tokens,
                        max_errors=args.max_errors,
                        max_duration_ms=args.max_duration_ms,
                    )
                else:
                    # Exclusive creation protects traces and existing reports.
                    with open(args.output, "x", encoding="utf-8", opener=open_private) as stream:
                        stream.write(timeline_html(spans, hide_identifiers=args.hide_identifiers))
                    result = {"written": True}
        print(json.dumps(result, indent=2, allow_nan=False))
        return 1 if args.command == "evaluate" and not result["passed"] else 0
    except OSError:
        print(
            "causalspan: file access failed; check paths, permissions, and existing outputs",
            file=sys.stderr,
        )
        return 2
    except (ValueError, TypeError, RecursionError):
        print(
            "causalspan: invalid input or recording mismatch; check the documented format",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
