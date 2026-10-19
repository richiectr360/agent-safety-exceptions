#!/usr/bin/env python3
"""Fetch pinned AgentDojo reference prompts without importing upstream code.

Standard library only. Existing source files are always hash-checked; no model
API, package installation, upstream imports, or upstream code execution occurs.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


REVISION = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
REPOSITORY = "https://github.com/ethz-spylab/agentdojo"
RAW_BASE = f"https://raw.githubusercontent.com/ethz-spylab/agentdojo/{REVISION}/"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "external" / "agentdojo"
SOURCE_PREFIX = "src/agentdojo/default_suites/v1/"
TIMEOUT_SECONDS = 30
MAX_SOURCE_BYTES = 1_000_000
# Hashes are pinned to reviewed bytes, not populated from the network at runtime.
SOURCES = (
    ("LICENSE", "4285a071f2d382338e52b4fb0a186d952984a34d43a33d8872e1a1d8cb43401e", 1161),
    ("README.md", "d8c6460ecce9bbf59ed300fbc74b4440188f74cd147a7611836270be49e7660e", 3184),
    (SOURCE_PREFIX + "banking/user_tasks.py", "37af838194f001af80cc040315bcb2d69d0112324d424f9a323473b41b317f82", 19450),
    (SOURCE_PREFIX + "slack/user_tasks.py", "25e43a0c58109765da090aa2f01bfb0892aaee70ca1622028074d7b49443a57b", 26012),
    (SOURCE_PREFIX + "travel/user_tasks.py", "757f0e28208f92c2082e016469654524cb1120ec10928ce229da15fe32f6d3ee", 76962),
    (SOURCE_PREFIX + "workspace/user_tasks.py", "d2a550b812b7f40ee2dea17ac19d44f2dd063d103524118216b563eca6e44171", 55415),
)
EXPECTED_COUNTS = {"banking": 16, "slack": 17, "travel": 20, "workspace": 33}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify(content: bytes, expected_hash: str, expected_size: int, label: str) -> None:
    if len(content) != expected_size or digest(content) != expected_hash:
        raise ValueError(f"Integrity check failed for {label}; existing data was not overwritten.")


def download(path: str) -> bytes:
    request = urllib.request.Request(RAW_BASE + path, headers={"User-Agent": "permission-thresholds-data/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = urllib.parse.urlparse(response.geturl())
        if final_url.scheme != "https" or final_url.hostname != "raw.githubusercontent.com":
            raise ValueError("Unexpected download redirect host or scheme")
        content = response.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError(f"Download exceeds {MAX_SOURCE_BYTES} bytes: {path}")
    return content


def static_value(node: ast.AST, names: dict):
    """Resolve the small literal-expression subset used by these pinned prompts.

    Deliberately rejects arbitrary calls, attributes, imports and comprehensions.
    A string-literal .join(list_of_strings) is interpreted explicitly below.
    Never uses eval/exec or imports a downloaded module.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.List):
        return [static_value(item, names) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(static_value(item, names) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {static_value(k, names): static_value(v, names) for k, v in zip(node.keys, node.values)}
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join" and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str) and len(node.args) == 1 and not node.keywords):
        items = static_value(node.args[0], names)
        if isinstance(items, (list, tuple)) and all(isinstance(item, str) for item in items):
            return node.func.value.value.join(items)
        raise ValueError("Static join requires a list or tuple of strings")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = static_value(node.left, names), static_value(node.right, names)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    if isinstance(node, ast.JoinedStr):
        return "".join(str(static_value(part, names)) for part in node.values)
    if isinstance(node, ast.FormattedValue):
        value = static_value(node.value, names)
        if node.conversion == 114:
            value = repr(value)
        elif node.conversion == 97:
            value = ascii(value)
        elif node.conversion == 115:
            value = str(value)
        elif node.conversion != -1:
            raise ValueError("Unsupported string conversion")
        spec = static_value(node.format_spec, names) if node.format_spec else ""
        return format(value, spec)
    raise ValueError(f"Unsupported static expression: {type(node).__name__}")


def assignments(nodes: list[ast.stmt], initial: dict | None = None) -> dict:
    names = dict(initial or {})
    for node in nodes:
        if isinstance(node, ast.Assign):
            targets, expression = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, expression = [node.target], node.value
        else:
            continue
        try:
            value = static_value(expression, names)
        except (ValueError, KeyError, TypeError):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names[target.id] = value
    return names


def extract_records(source_path: str, content: bytes) -> list[dict]:
    text = content.decode("utf-8")
    module = ast.parse(text, filename=source_path)
    global_names = assignments(module.body)
    suite = source_path.split("/")[-2]
    records = []
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("UserTask"):
            continue
        # Include only individually declared user tasks. Do not execute dynamic
        # TaskCombinator construction, graders, reference solutions or tools.
        prompt_assignments = [
            item for item in node.body
            if isinstance(item, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PROMPT" for target in item.targets)
        ]
        if not prompt_assignments:
            continue
        values = assignments(node.body, global_names)
        if not isinstance(values.get("PROMPT"), str):
            raise ValueError(f"Cannot statically extract prompt for {suite}/{node.name}")
        task_number = int(node.name.removeprefix("UserTask"))
        difficulty = None
        for item in node.body:
            if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DIFFICULTY" for t in item.targets):
                if isinstance(item.value, ast.Attribute):
                    difficulty = item.value.attr.lower()
        records.append({
            "task_id": f"agentdojo_v1/{suite}/user_task_{task_number}",
            "suite": suite,
            "source_class": node.name,
            "source_path": source_path,
            "source_line": node.lineno,
            "source_commit": REVISION,
            "source_url": f"{REPOSITORY}/blob/{REVISION}/{source_path}#L{node.lineno}",
            "difficulty": difficulty,
            "prompt": values["PROMPT"],
            "role": "auxiliary_task_reference_not_threshold_ground_truth",
        })
    return sorted(records, key=lambda record: int(record["source_class"].removeprefix("UserTask")))


def write_or_check(path: Path, content: bytes, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(f"Missing or stale derived artifact: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Require cached source files; no network access")
    parser.add_argument("--check", action="store_true", help="Verify all cached and derived files without changing files or accessing the network")
    args = parser.parse_args()
    records, source_manifest = [], []
    for path, expected_hash, expected_size in SOURCES:
        local = OUTPUT_DIR / path
        if local.exists():
            content = local.read_bytes()
        elif args.offline or args.check:
            raise ValueError(f"Source missing in offline mode: {local}")
        else:
            content = download(path)
            verify(content, expected_hash, expected_size, path)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
        verify(content, expected_hash, expected_size, path)
        source_manifest.append({"path": path, "url": RAW_BASE + path, "sha256": expected_hash, "size_bytes": expected_size})
        if path.endswith("user_tasks.py"):
            records.extend(extract_records(path, content))
    counts = dict(sorted(Counter(record["suite"] for record in records).items()))
    if counts != EXPECTED_COUNTS or len({record["task_id"] for record in records}) != len(records):
        raise ValueError(f"Unexpected extraction counts or duplicate task IDs: {counts}")
    jsonl = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records).encode("utf-8")
    manifest = {
        "schema_version": 1,
        "dataset": "AgentDojo v1 directly declared user-task prompts",
        "repository": REPOSITORY,
        "revision": REVISION,
        "retrieved_date": "2026-10-18",
        "license": "MIT",
        "license_file": "LICENSE",
        "paper": "https://arxiv.org/abs/2406.13352",
        "purpose": "Auxiliary task-design reference; not a runnable AgentDojo benchmark or evidence for permission-threshold effects.",
        "extraction": "Static AST literal and f-string resolution; no upstream imports or execution; dynamic composed tasks excluded.",
        "source_files": source_manifest,
        "derived_files": [{"path": "tasks.jsonl", "sha256": digest(jsonl), "size_bytes": len(jsonl), "record_count": len(records)}],
        "counts_by_suite": counts,
    }
    write_or_check(OUTPUT_DIR / "tasks.jsonl", jsonl, args.check)
    write_or_check(OUTPUT_DIR / "manifest.json", (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"), args.check)
    print(json.dumps({"status": "verified" if args.check else "ready", "records": len(records), "counts_by_suite": counts, "source_bytes": sum(s[2] for s in SOURCES), "revision": REVISION, "output": str(OUTPUT_DIR)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"Dataset preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
