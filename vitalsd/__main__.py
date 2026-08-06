from __future__ import annotations

import argparse
import sys

from .collectors import probe_all
from .server import VitalsServer
from .state import State


def main():
    ap = argparse.ArgumentParser(prog="vitalsd")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=9877, help="bind port (default 9877)")
    args = ap.parse_args()

    state = State(probe_all())
    caps = ", ".join(c.name for c in state.collectors) or "none"
    n_gpus = len(state.info_payload().get("gpus", []))
    sys.stderr.write(
        f"vitalsd on {state.host}: {n_gpus} GPU(s), collectors: {caps}, "
        f"listening on {args.host}:{args.port}\n"
    )
    srv = VitalsServer((args.host, args.port), state)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
