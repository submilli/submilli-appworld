"""Checks the Packages' return types against responses the generator never saw.

Crawls the GET APIs of test tasks outside `observe.py`'s sample and reports every response that
`json<T>()` would refuse under `generator/types.json` (written by `gen_packages.py`).

    python bench/audit_types.py --apis-url http://127.0.0.1:9150 --sample 20
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict

import observe
import shapes


class Auditor(observe.Observer):
    def __init__(self, apis_url: str, types: dict):
        super().__init__(apis_url)
        self.types = types
        self.checked: dict[str, int] = defaultdict(int)
        self.refused: dict[str, list[str]] = defaultdict(list)

    def record(self, api, value):
        key = f"{api.app}.{api.name}"
        self.checked[key] += 1
        problems = shapes.admits(self.types[key], value)
        if problems and len(self.refused[key]) < 5:
            self.refused[key].append("; ".join(problems[:3]))
        self._harvest(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apis-url", default="http://127.0.0.1:9150")
    parser.add_argument("--sample", type=int, default=20, help="tasks per test split")
    args = parser.parse_args()
    with open(os.path.join(observe.ROOT, "generator", "types.json")) as file:
        types = json.load(file)
    # The tasks observe.py crawled (same seed and order), to leave them out.
    rng0 = random.Random(0)
    seen = set()
    for split in ("train", "dev", "test_normal", "test_challenge"):
        ids = observe.task_ids(split)
        seen.update(rng0.sample(ids, min(40, len(ids))))
    auditor = Auditor(args.apis_url, types)
    rng = random.Random(1)
    for split in ("test_normal", "test_challenge"):
        fresh = [t for t in observe.task_ids(split) if t not in seen]
        for task_id in rng.sample(fresh, min(args.sample, len(fresh))):
            n = auditor.crawl(task_id, rng)
            print(f"audit {split} {task_id}: {n} responses", flush=True)
    total = sum(auditor.checked.values())
    bad = {k: v for k, v in auditor.refused.items() if v}
    print(f"\n{total} responses over {len(auditor.checked)} APIs; {len(bad)} APIs with refused responses")
    for key, examples in sorted(bad.items()):
        print(f"  {key}: {examples[0]}")


if __name__ == "__main__":
    main()
