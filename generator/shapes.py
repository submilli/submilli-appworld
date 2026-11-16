"""Response shapes: inferred from AppWorld's doc examples, widened by observed responses.

`json<T>()` checks a response against `T` on the host, so a type that is narrower than what
AppWorld returns (a field documented as a string that is sometimes null) would crash a program
that is otherwise right. The doc examples never show null, so nullability and optional fields
come from responses recorded by `bench/observe.py`.

A shape is a plain dict:
    {"k": "str" | "num" | "bool" | "null" | "any"}
    {"k": "never"}                       # the element of an empty array: no information yet
    {"k": "arr", "of": shape}
    {"k": "obj", "fields": {name: {"s": shape, "opt": bool}}}
    {"k": "union", "of": [shape, ...]}   # at most one obj and one arr; prims deduplicated
"""

from __future__ import annotations

import copy

STR = {"k": "str"}
NUM = {"k": "num"}
BOOL = {"k": "bool"}
NULL = {"k": "null"}
ANY = {"k": "any"}
NEVER = {"k": "never"}


def of_value(value) -> dict:
    """The shape of a JSON value, or of a doc example (where "string" stands for any string)."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, (int, float)):
        return NUM
    if isinstance(value, str):
        return STR
    if isinstance(value, list):
        if not value:
            return {"k": "arr", "of": NEVER}
        element = of_value(value[0])
        for item in value[1:]:
            element = merge(element, of_value(item))
        return {"k": "arr", "of": element}
    if isinstance(value, dict):
        if not value:
            return ANY
        return {"k": "obj", "fields": {k: {"s": of_value(v), "opt": False} for k, v in value.items()}}
    raise TypeError(f"not JSON: {value!r}")


def _members(shape: dict) -> list[dict]:
    return shape["of"] if shape["k"] == "union" else [shape]


def merge(a: dict, b: dict) -> dict:
    """The narrowest shape that admits both."""
    if a["k"] == "never":
        return copy.deepcopy(b)
    if b["k"] == "never":
        return copy.deepcopy(a)
    if a["k"] == "any" or b["k"] == "any":
        return ANY
    members: list[dict] = []
    for m in _members(a) + _members(b):
        members = _add(members, m)
    return members[0] if len(members) == 1 else {"k": "union", "of": members}


def _add(members: list[dict], m: dict) -> list[dict]:
    for i, existing in enumerate(members):
        if existing["k"] != m["k"]:
            continue
        if m["k"] == "obj":
            members[i] = _merge_obj(existing, m)
        elif m["k"] == "arr":
            members[i] = {"k": "arr", "of": merge(existing["of"], m["of"])}
        return members
    return members + [copy.deepcopy(m)]


def _merge_obj(a: dict, b: dict) -> dict:
    fields = {}
    for name in list(a["fields"]) + [n for n in b["fields"] if n not in a["fields"]]:
        fa, fb = a["fields"].get(name), b["fields"].get(name)
        if fa and fb:
            fields[name] = {"s": merge(fa["s"], fb["s"]), "opt": fa["opt"] or fb["opt"]}
        else:
            only = fa or fb
            fields[name] = {"s": only["s"], "opt": True}
    return {"k": "obj", "fields": fields}


def admits(shape: dict, value) -> list[str]:
    """Where `value` doesn't fit `shape`, as json<T>() would refuse it; empty when it fits.

    Extra object fields are fine; a missing field must be optional, and null must be admitted.
    """
    problems: list[str] = []
    _admits(shape, value, "$", problems)
    return problems


def _admits(shape, value, at, problems):
    k = shape["k"]
    if k in ("any", "never"):
        return
    if k == "union":
        if any(not admits(m, value) for m in shape["of"]):
            return
        problems.append(f"{at}: {type(value).__name__} fits none of the union")
        return
    if value is None:
        if k != "null":
            problems.append(f"{at}: null")
        return
    if k == "null":
        problems.append(f"{at}: expected null, got {type(value).__name__}")
    elif k == "str":
        if not isinstance(value, str):
            problems.append(f"{at}: expected string, got {type(value).__name__}")
    elif k == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{at}: expected number, got {type(value).__name__}")
    elif k == "bool":
        if not isinstance(value, bool):
            problems.append(f"{at}: expected boolean, got {type(value).__name__}")
    elif k == "arr":
        if not isinstance(value, list):
            problems.append(f"{at}: expected array, got {type(value).__name__}")
        else:
            for i, item in enumerate(value):
                _admits(shape["of"], item, f"{at}[{i}]", problems)
    elif k == "obj":
        if not isinstance(value, dict):
            problems.append(f"{at}: expected object, got {type(value).__name__}")
            return
        for name, f in shape["fields"].items():
            if name not in value:
                if not f["opt"]:
                    problems.append(f"{at}.{name}: missing")
            else:
                _admits(f["s"], value[name], f"{at}.{name}", problems)
