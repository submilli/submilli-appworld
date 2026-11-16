"""Generates one Submilli Package per AppWorld app from `spec.load()`.

    python generator/gen_packages.py [--observed generator/observed.json]

Writes `packages/<app>/{src/client.ts, src/lib.ts, docs/readme.md, README.md}` and
`submilli.toml`. Each AppWorld API becomes one exported function with AppWorld's name and
parameters (one `params` object, snake_case keys), minus `access_token`: the Package adds the
supervisor's token, bound by the harness as a session secret. Every function asks the Blueprint
first, with each primitive parameter as a check field.
"""

from __future__ import annotations

import argparse
import json
import os
import re

import shapes
import spec

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
SCOPE = "@appworld"
NAMESPACE = "appworld"
ROUTER_BASE = "http://127.0.0.1:9000/"

PARAM_TYPES = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "list[string]": "string[]",
    "list[number]": "number[]",
    "number | integer | string": "number | string",
}
PRIMITIVE = {"string", "integer", "number", "boolean"}
IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part)


def singular(name: str) -> str:
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("sses") or name.endswith("ches") or name.endswith("shes"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def ts_literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value)


def key(name: str) -> str:
    return name if IDENT.match(name) else json.dumps(name)


NULLABLE_FIELDS: set[str] = set()  # field names seen null in any observed response
# (app, the entity's field names) → its fields seen null in any observed response of that app
ENTITY_NULLABLE: dict[tuple[str, frozenset], set[str]] = {}
CURRENT_APP = [""]  # the app being generated, for ENTITY_NULLABLE


def entity_nullable(app: str, shape: dict) -> None:
    if shape["k"] == "obj":
        seen = ENTITY_NULLABLE.setdefault((app, frozenset(shape["fields"])), set())
        for name, f in shape["fields"].items():
            if any(m["k"] == "null" for m in (f["s"]["of"] if f["s"]["k"] == "union" else [f["s"]])):
                seen.add(name)
            entity_nullable(app, f["s"])
    elif shape["k"] in ("arr",):
        entity_nullable(app, shape["of"])
    elif shape["k"] == "union":
        for m in shape["of"]:
            entity_nullable(app, m)


def nullable_names(shape: dict, out: set[str]) -> None:
    if shape["k"] == "obj":
        for name, f in shape["fields"].items():
            if any(m["k"] == "null" for m in (f["s"]["of"] if f["s"]["k"] == "union" else [f["s"]])):
                out.add(name)
            nullable_names(f["s"], out)
    elif shape["k"] == "arr":
        nullable_names(shape["of"], out)
    elif shape["k"] == "union":
        for m in shape["of"]:
            nullable_names(m, out)


def from_doc(doc: dict) -> dict:
    """A doc-only shape, with a field nullable wherever that field name was seen null elsewhere."""
    if doc["k"] == "obj":
        fields = {}
        for name, f in doc["fields"].items():
            inner = from_doc(f["s"])
            if name in NULLABLE_FIELDS:
                inner = shapes.merge(inner, shapes.NULL)
            fields[name] = {"s": inner, "opt": f["opt"]}
        return {"k": "obj", "fields": fields}
    if doc["k"] == "arr":
        return {"k": "arr", "of": from_doc(doc["of"])}
    return doc


def combine(doc: dict, observed: dict | None) -> dict:
    """The observed shape, with the doc's structure where nothing was observed."""
    if observed is None or observed["k"] in ("any", "never"):
        return from_doc(doc)
    if observed["k"] == "null" and doc["k"] not in ("null", "any"):
        # Only nulls seen: the documented type, or null.
        return shapes.merge(doc, observed)
    if observed["k"] == "union":
        return {"k": "union", "of": [combine(doc, m) if m["k"] == doc["k"] else m for m in observed["of"]]}
    if observed["k"] == "arr" and doc["k"] == "arr":
        return {"k": "arr", "of": combine(doc["of"], observed["of"])}
    if observed["k"] == "obj" and doc["k"] == "obj":
        fields = {}
        for name, f in observed["fields"].items():
            d = doc["fields"].get(name)
            inner = combine(d["s"], f["s"]) if d else f["s"]
            fields[name] = {"s": inner, "opt": f["opt"]}
        for name, d in doc["fields"].items():
            if name not in fields:
                fields[name] = {"s": from_doc(d["s"]), "opt": True}
        # The same entity from another API (the same fields, in this app) may send null where this
        # API's sampled responses never did: `show_group`'s `description`, seen null in `show_groups`.
        for name in ENTITY_NULLABLE.get((CURRENT_APP[0], frozenset(fields)), ()):
            if fields[name]["s"]["k"] in ("str", "num", "bool"):
                fields[name] = {"s": shapes.merge(fields[name]["s"], shapes.NULL), "opt": fields[name]["opt"]}
        return {"k": "obj", "fields": fields}
    return observed


class Types:
    """The interfaces of one Package, deduplicated by structure."""

    def __init__(self):
        self.by_body: dict[tuple[str, str], str] = {}
        self.by_name: dict[str, str] = {}
        self.order: list[str] = []

    def render(self, shape: dict, name: str, fallback: str | None = None) -> str:
        """`name` is the suggested name. When a different structure already took it, `fallback` names
        this one by where it appears (`PlaylistSong`, `PlaylistDetails`); a number is the last resort."""
        k = shape["k"]
        if k == "str":
            return "string"
        if k == "num":
            return "number"
        if k == "bool":
            return "boolean"
        if k == "null":
            return "null"
        if k in ("any", "never"):
            return "unknown"
        if k == "arr":
            inner = self.render(shape["of"], name, fallback)
            return f"({inner})[]" if " | " in inner else f"{inner}[]"
        if k == "union":
            members = sorted(shape["of"], key=lambda m: m["k"] == "null")
            return " | ".join(self.render(m, name, fallback) for m in members)
        lines = []
        for field_name, f in shape["fields"].items():
            child = pascal(singular(field_name))
            t = self.render(f["s"], child, child if child.startswith(name) else name + child)
            lines.append(f"    {key(field_name)}{'?' if f['opt'] else ''}: {t};")
        body = "\n".join(lines)
        if body == "    message: string;":
            name = "Message"
        # The same structure under the same suggested name is one interface; a receiver is not
        # typed as a `Sender` just because the two look alike.
        cache = (name, body)
        if cache in self.by_body:
            return self.by_body[cache]
        final = name
        if final in self.by_name and self.by_name[final] != body and fallback:
            final = fallback
        n = 2
        while final in self.by_name and self.by_name[final] != body:
            final = f"{fallback or name}{n}"
            n += 1
        self.by_body[cache] = final
        if final not in self.by_name:
            self.by_name[final] = body
            self.order.append(final)
        return final

    def declarations(self) -> str:
        out = []
        for name in self.order:
            out.append(f"/** A `{name}` as AppWorld returns it. */\nexport interface {name} {{\n{self.by_name[name]}\n}}")
        return "\n\n".join(out)


def result_name(api: spec.Api) -> str:
    stem = re.sub(r"^(show|search|get)_", "", api.name)
    if api.method == "GET":
        return pascal(singular(stem))
    return pascal(api.name) + "Result"


def param_doc(p: spec.Param) -> str:
    text = p.description.strip().rstrip(".") + "."
    if p.constraints:
        text += " Constraints: " + "; ".join(p.constraints) + "."
    if not p.required and p.default is not None:
        text += f" Defaults to {ts_literal(p.default)}."
    return text.replace("*/", "* /")


def local(name: str) -> str:
    """The local that holds a parameter, read once so the checked value is the one sent."""
    return "a_" + name


def check_fields(api: spec.Api) -> list[tuple[str, str, str]]:
    """(name, type, expression) of every primitive parameter that always has a value."""
    fields = []
    for p in api.params:
        if p.type not in PRIMITIVE:
            continue
        if p.required:
            fields.append((p.name, PARAM_TYPES[p.type], local(p.name)))
        elif p.default is not None:
            fields.append((p.name, PARAM_TYPES[p.type], f"{local(p.name)} ?? {ts_literal(p.default)}"))
    return fields


FINAL_SHAPES: dict[str, dict] = {}  # app.api → the shape its return type declares


def function(api: spec.Api, types: Types, observed: dict) -> str:
    doc_shape = shapes.of_value(api.success)
    obs = observed.get(f"{api.app}.{api.name}")
    shape = combine(doc_shape, obs["shape"] if obs else None)
    FINAL_SHAPES[f"{api.app}.{api.name}"] = shape
    stem = pascal(singular(re.sub(r"^(show|search|get)_", "", api.name)))
    if shape["k"] == "arr":
        returns = types.render(shape, stem, pascal(api.name) + "Item")
    else:
        returns = types.render(shape, result_name(api), stem + "Details")
    capability = f"{api.app}.{NAMESPACE}/{api.name}"
    fields = check_fields(api)
    binding = "{ " + ", ".join(f"{n}: {t}" for n, t, _ in fields) + " }" if fields else "{}"
    payload = "{ " + ", ".join(f"{key(n)}: {e}" for n, _, e in fields) + " }" if fields else "{}"
    description = api.description.strip().replace("*/", "* /")
    out = []
    if api.params:
        params_name = pascal(api.name) + "Params"
        members = []
        for p in api.params:
            members.append(f"    /** {param_doc(p)} */\n    {key(p.name)}{'' if p.required else '?'}: {PARAM_TYPES[p.type]};")
        out.append(f"/** The arguments of `{api.name}`. */\nexport interface {params_name} {{\n" + "\n".join(members) + "\n}")
        all_optional = all(not p.required for p in api.params)
        signature = f"params: {params_name}{' = {}' if all_optional else ''}"
        reads = "\n".join(f"    const {local(p.name)} = params.{p.name};" for p in api.params)
        sets = "\n".join(f"    args.set({json.dumps(p.name)}, {local(p.name)});" for p in api.params)
        param_tag = f" * @param params The arguments, keyed by AppWorld's parameter names.\n"
    else:
        signature = ""
        reads = ""
        sets = ""
        param_tag = ""
    out.append(
        f"/**\n * {description}\n{param_tag} * @returns AppWorld's response.\n"
        f" * @capability {capability} {binding}\n */\n"
        f"export function {api.name}({signature}): {returns} {{\n"
        + (reads + "\n" if reads else "")
        + f"    check({json.dumps(capability)}, {payload});\n"
        f"    const args = new Map<string, Value>();\n"
        + (sets + "\n" if sets else "")
        + ('    args.set("file_system_access_token", fileSystemToken());\n' if api.file_system_token else "")
        + f"    return call({json.dumps(api.method)}, {json.dumps(api.path)}, args).json<{returns}>();\n}}"
    )
    return "\n\n".join(out)


def client_ts(app: str) -> str:
    token = f"APPWORLD_{app.upper()}_TOKEN"
    if app in spec.AUTHENTICATED:
        auth = f'''    const token = secrets.get("{token}");
    if (token === undefined) {{
        throw new AppWorldError("{token} is not bound for this session", 0);
    }}
    result.set("Authorization", "Bearer " + token);
'''
    else:
        auth = ""
    return f'''// Generated by generator/gen_packages.py. Do not edit.
import {{ get, post, put, patch, request, Response }} from "submilli:http";
import secrets from "submilli:secrets";
import {{ encodeComponent }} from "submilli:url";

// The benchmark's router, which forwards `w/<worker>/…` to that worker's AppWorld API server.
const BASE = "{ROUTER_BASE}";

/** A failed call to an AppWorld API: AppWorld's message and the HTTP status. */
export class AppWorldError extends Error {{
    /** The HTTP status; 0 when the call was not sent. */
    status: number;
    constructor(message: string, status: number) {{
        super(message);
        this.name = "AppWorldError";
        this.status = status;
    }}
}}

/** A parameter value as AppWorld's APIs take it. */
export type Value = string | number | boolean | string[] | number[] | undefined;

interface ErrorBody {{
    message: string;
}}

function headers(): Map<string, string> {{
    const result = new Map<string, string>();
{auth}    result.set("Content-Type", "application/json");
    return result;
}}

/** The supervisor's file system token, for an API that attaches or saves a file. */
export function fileSystemToken(): string {{
    const token = secrets.get("APPWORLD_FILE_SYSTEM_TOKEN");
    if (token === undefined) {{
        throw new AppWorldError("APPWORLD_FILE_SYSTEM_TOKEN is not bound for this session", 0);
    }}
    return token;
}}

function worker(): string {{
    const id = secrets.get("APPWORLD_WORKER");
    if (id === undefined) {{
        throw new AppWorldError("APPWORLD_WORKER is not bound for this session", 0);
    }}
    return id;
}}

function text(value: string | number | boolean): string {{
    return typeof value === "string" ? value : value.toString();
}}

function query(rest: Map<string, Value>): string {{
    const parts: string[] = [];
    for (const [name, value] of rest) {{
        if (value === undefined) continue;
        if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {{
            parts.push(encodeComponent(name) + "=" + encodeComponent(text(value)));
        }} else {{
            for (const item of value) parts.push(encodeComponent(name) + "=" + encodeComponent(text(item)));
        }}
    }}
    return parts.join("&");
}}

function send(method: string, rel: string, rest: Map<string, Value>): Response {{
    if (method === "GET" || method === "DELETE") {{
        const q = query(rest);
        const target = q.length > 0 ? rel + "?" + q : rel;
        if (method === "GET") return get(BASE + target, headers());
        return request("DELETE", BASE + target, null, headers());
    }}
    const body: {{ [key: string]: unknown }} = {{}};
    for (const [name, value] of rest) {{
        if (value !== undefined) body[name] = value;
    }}
    if (method === "POST") return post(BASE + rel, body, headers());
    if (method === "PUT") return put(BASE + rel, body, headers());
    return patch(BASE + rel, body, headers());
}}

function message(response: Response): string {{
    try {{
        return response.json<ErrorBody>().message;
    }} catch (e) {{
        return response.body;
    }}
}}

/**
 * Call one AppWorld API: fill `{{name}}` path segments, send the rest as the query (GET, DELETE)
 * or as a JSON body (POST, PUT, PATCH).
 * @param method The HTTP method.
 * @param path The API's path, with `{{name}}` placeholders.
 * @param params The arguments; undefined ones are left out.
 * @returns The response, when it succeeded.
 */
export function call(method: string, path: string, params: Map<string, Value>): Response {{
    let filled = path;
    const rest = new Map<string, Value>();
    for (const [name, value] of params) {{
        const placeholder = "{{" + name + "}}";
        if (filled.includes(placeholder) && (typeof value === "string" || typeof value === "number")) {{
            filled = filled.replace(placeholder, encodeComponent(text(value)));
        }} else {{
            rest.set(name, value);
        }}
    }}
    const response = send(method, "w/" + worker() + filled, rest);
    if (!response.ok) {{
        throw new AppWorldError(message(response), response.status);
    }}
    return response;
}}
'''


def lib_ts(app: str, apis: list[spec.Api], observed: dict) -> str:
    types = Types()
    functions = [function(api, types, observed) for api in apis]
    return (
        "// Generated by generator/gen_packages.py. Do not edit.\n"
        'import { check } from "submilli:security";\n'
        'import { call, fileSystemToken, Value } from "./client";\n\n'
        'export { AppWorldError } from "./client";\n\n'
        + types.declarations() + "\n\n" + "\n\n".join(functions) + "\n"
    )


def readme(app: str) -> str:
    signed_in = (
        "You are signed in to this app as the supervisor: every function acts on their account, "
        "and none takes an access token."
        if app in spec.AUTHENTICATED
        else "It needs no sign-in."
    )
    return (
        f"# {SCOPE}/{app}\n\n"
        f"{spec.APP_DESCRIPTIONS[app]}\n\n"
        f"{signed_in} Each function is one of AppWorld's `{app}` APIs, with its name and its "
        "parameters as one object keyed by AppWorld's parameter names. A call that AppWorld refuses throws "
        "`AppWorldError`, with AppWorld's message and the HTTP status.\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed", default=os.path.join(ROOT, "generator", "observed.json"))
    args = parser.parse_args()
    observed = {}
    if os.path.exists(args.observed):
        with open(args.observed) as file:
            observed = json.load(file)["observed"]
    for api_key, entry in observed.items():
        nullable_names(entry["shape"], NULLABLE_FIELDS)
        entity_nullable(api_key.split(".")[0], entry["shape"])
    apis = spec.load(DATA)
    manifest = []
    for app, app_apis in apis.items():
        CURRENT_APP[0] = app
        base = os.path.join(ROOT, "packages", app)
        os.makedirs(os.path.join(base, "src"), exist_ok=True)
        os.makedirs(os.path.join(base, "docs"), exist_ok=True)
        with open(os.path.join(base, "src", "client.ts"), "w") as file:
            file.write(client_ts(app))
        with open(os.path.join(base, "src", "lib.ts"), "w") as file:
            file.write(lib_ts(app, app_apis, observed))
        with open(os.path.join(base, "docs", "readme.md"), "w") as file:
            file.write(readme(app))
        with open(os.path.join(base, "README.md"), "w") as file:
            file.write(
                f"# {SCOPE}/{app}\n\nGenerated from AppWorld's `{app}` API docs by `generator/gen_packages.py`. "
                f"Grant it with `submilli blueprint add-package {SCOPE}/{app} --all-capabilities`; the Package "
                f"needs the harness secrets `APPWORLD_WORKER`"
                + (f" and `APPWORLD_{app.upper()}_TOKEN`" if app in spec.AUTHENTICATED else "")
                + ".\n"
            )
        manifest.append(
            f'[[package]]\nname = "{SCOPE}/{app}"\nversion = "0.1.0"\n'
            f"description = {json.dumps(spec.APP_DESCRIPTIONS[app])}\n"
            f'keywords = ["appworld", {json.dumps(app)}]\npath = "packages/{app}"\n'
        )
        print(f"{app}: {len(app_apis)} functions")
    with open(os.path.join(ROOT, "generator", "types.json"), "w") as file:
        json.dump(FINAL_SHAPES, file, indent=1, sort_keys=True)
    with open(os.path.join(ROOT, "submilli.toml"), "w") as file:
        file.write("# Generated by generator/gen_packages.py. Do not edit.\n\n" + "\n".join(manifest))


if __name__ == "__main__":
    main()
