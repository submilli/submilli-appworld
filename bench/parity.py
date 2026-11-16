"""Checks that the `submilli` and `tools` arms expose the same API surface.

For every app: the Package's exported functions against the tool arm's tools (`<app>__<api>`),
and each function's parameter names against its tool's schema.

    python bench/parity.py
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import harness  # noqa: E402
import spec  # noqa: E402
from arms.tools import schema  # noqa: E402

FUNCTION = re.compile(r"^export function (\w+)\((?:params: (\w+))?", re.M)
INTERFACE = re.compile(r"^export interface (\w+) \{\n(.*?)^\}", re.M | re.S)
MEMBER = re.compile(r"^    (\w+)\??: ", re.M)


def main() -> int:
    problems = []
    apis = spec.load(harness.DATA)
    for app, app_apis in apis.items():
        with open(os.path.join(harness.ROOT, "packages", app, "src", "lib.ts")) as file:
            source = file.read()
        interfaces = {name: set(MEMBER.findall(body)) for name, body in INTERFACE.findall(source)}
        functions = {name: params for name, params in FUNCTION.findall(source)}
        tools = {api.name: api for api in app_apis}
        for name in sorted(set(functions) ^ set(tools)):
            problems.append(f"{app}.{name}: only in the {'Package' if name in functions else 'tools'}")
        for name in sorted(set(functions) & set(tools)):
            package_params = interfaces.get(functions[name], set()) if functions[name] else set()
            tool_params = set(schema(tools[name])["properties"])
            if package_params != tool_params:
                problems.append(f"{app}.{name}: Package {sorted(package_params)} vs tool {sorted(tool_params)}")
    total = sum(len(a) for a in apis.values())
    if problems:
        print("\n".join(problems))
        print(f"{len(problems)} differences over {total} APIs")
        return 1
    print(f"parity: {total} APIs, same names and parameters in both arms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
