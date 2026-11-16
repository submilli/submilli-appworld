"""`appworld …`, with every server it starts listening on 127.0.0.1 instead of 0.0.0.0.

AppWorld hardcodes 0.0.0.0 for the environment and MCP servers, with no option to change it. The
environment server runs the Python code it is sent (`POST /execute`), so it must not be reachable
from the network.

    python bench/serve_local.py serve environment --port 9300 --no-show-usage
"""

import uvicorn

_run = uvicorn.run


def run(app, *args, **kwargs):
    kwargs["host"] = "127.0.0.1"
    return _run(app, *args, **kwargs)


uvicorn.run = run

from appworld.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
