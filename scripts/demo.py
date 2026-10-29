"""``make demo``: start the mock upstream, the pii-guard API and the UI, print where to go.

Fast mode by default: rules + the NER model (the public fallback is downloaded once into
~/.cache/pii-guard/models; needs the ``ner`` extra). ``--mode rules`` is rules only, offline,
nothing downloaded. Mock upstream unless one is configured. See docs/operations.md.

    uv run --extra ner python scripts/demo.py [--mode fast|rules] [--no-ui] [--mock]
        [--traffic-log masked|full]
"""

from __future__ import annotations

import argparse
import signal
import sys

from demo_stack import MODES, Stack, banner, plan, prepare_ner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="fast",
        help="fast: rules + NER (default); rules: rules only, offline, no model download",
    )
    parser.add_argument("--no-ui", action="store_true", help="API and mock upstream only")
    parser.add_argument("--mock", action="store_true", help="mock upstream even with a key set")
    parser.add_argument("--traffic-log", choices=["masked", "full"], help="default masked")
    parser.add_argument("--api-port", type=int, default=8787)
    parser.add_argument("--mock-port", type=int, default=8790)
    parser.add_argument("--ui-port", type=int, default=5173)
    args = parser.parse_args(argv)
    p = plan(
        force_mock=args.mock,
        ui=not args.no_ui,
        traffic_log=args.traffic_log,
        api_port=args.api_port,
        mock_port=args.mock_port,
        mode=args.mode,
    )
    p.ui_port = args.ui_port

    def interrupt(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)  # stop the stack on `kill` too, not only Ctrl-C
    signal.signal(signal.SIGINT, interrupt)
    try:
        prepare_ner(p)
        with Stack(p) as stack:
            print(banner(p), flush=True)
            return stack.wait()
    except RuntimeError as exc:
        print(f"demo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
