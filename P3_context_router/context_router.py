#!/usr/bin/env python3
"""
context_router.py — Recommend which docs files to load based on task text or task type.

Always includes AGENTS-CORE.md. Maps keywords/types to relevant packs.

Usage:
    python3 tools/context_router.py --task "check ads anomaly for facebook"
    python3 tools/context_router.py --type seo
    python3 tools/context_router.py --type marketing
    python3 tools/context_router.py --task "review prompt injection risk in external skill"
    python3 tools/context_router.py --task "check ads anomaly for facebook" --json
    python3 tools/context_router.py --type marketing --root /path/to/workspace --json
"""

import sys
import re
import json
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ALWAYS_INCLUDE = ["AGENTS-CORE.md"]

# Keywords use word-boundary matching via _kw_match() below.
# Short tokens like "api" are matched with \b...\b to avoid false-positives
# inside longer words (e.g. "api" won't match "capitalism").
KEYWORD_MAP = [
    {
        "keywords": ["ads", "campaign", "facebook", "google", "tiktok", "advertising", "audience", "lead", "kpi", "report", "budget", "spend", "cpm", "cpc", "ctr", "creative", "anomaly"],
        "pack": "packs/marketing.md",
        "type_aliases": ["marketing"]
    },
    {
        "keywords": ["seo", "article", "outline", "content", "blog", "keyword", "serp", "ranking", "landing", "copy", "headline", "youtube", "sumvid"],
        "pack": "packs/content-seo.md",
        "type_aliases": ["seo", "content"]
    },
    {
        "keywords": ["script", "code", "automation", "workflow", "python", "api", "pipeline", "automate", "cron", "schedule", "tool", "script", "deploy", "webhook"],
        "pack": "packs/automation.md",
        "type_aliases": ["automation"]
    },
    {
        "keywords": ["security", "prompt injection", "token", "credential", "risk",
                     "injection", "vulnerability", "pentest", "auth"],
        "pack": "packs/security.md",
        "type_aliases": ["security"]
    },
    {
        "keywords": ["heartbeat", "cron", "reminder", "status", "monitor", "uptime", "ops", "health"],
        "pack": "packs/ops-heartbeat.md",
        "type_aliases": ["heartbeat", "ops"]
    },
    {
        "keywords": ["memory", "kb", "knowledge base", "recall", "save mem", "persistent", "rag", "ingest", "index"],
        "pack": "packs/memory-context.md",
        "type_aliases": ["memory", "kb"]
    },
]

# Pre-compile word-boundary patterns for every keyword
_KW_PATTERNS = {}
for _entry in KEYWORD_MAP:
    for _kw in _entry["keywords"]:
        if " " in _kw:
            _KW_PATTERNS[_kw] = re.compile(re.escape(_kw), re.IGNORECASE)
        else:
            _KW_PATTERNS[_kw] = re.compile(r'\b' + re.escape(_kw) + r'\b', re.IGNORECASE)


def _kw_match(kw, text):
    return bool(_KW_PATTERNS[kw].search(text))


def resolve_root(root_override=None):
    if root_override:
        p = Path(root_override).resolve()
        if not p.exists():
            return None, f"--root path does not exist: {root_override}"
        if not p.is_dir():
            return None, f"--root path is not a directory: {root_override}"
        return p, None
    return SCRIPT_DIR.parent, None


def check_root_warnings(workspace_root):
    """Return list of warning strings about the workspace root."""
    warnings = []
    core = workspace_root / "AGENTS-CORE.md"
    if not core.exists():
        warnings.append(f"AGENTS-CORE.md not found in root ({workspace_root}) — context may be incomplete")
    return warnings


def route(task_text=None, task_type=None):
    recommended = list(ALWAYS_INCLUDE)
    matched_packs = []

    if task_type:
        task_type_lower = task_type.lower().strip()
        for entry in KEYWORD_MAP:
            if task_type_lower in entry["type_aliases"]:
                if entry["pack"] not in matched_packs:
                    matched_packs.append(entry["pack"])

    if task_text:
        for entry in KEYWORD_MAP:
            for kw in entry["keywords"]:
                if _kw_match(kw, task_text):
                    if entry["pack"] not in matched_packs:
                        matched_packs.append(entry["pack"])
                    break

    recommended.extend(matched_packs)
    return recommended


def main():
    parser = argparse.ArgumentParser(
        description="context_router — Recommend docs files to load based on task"
    )
    parser.add_argument("--task", type=str, default=None,
                        help="Free-text task description")
    parser.add_argument("--type", dest="task_type", type=str, default=None,
                        choices=["marketing", "seo", "content", "automation",
                                 "security", "heartbeat", "ops", "memory", "kb"],
                        help="Task type shorthand")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--root", type=str, default=None,
                        help="Workspace root path — validated and checked for AGENTS-CORE.md presence")
    args = parser.parse_args()

    if not args.task and not args.task_type:
        parser.print_help()
        sys.exit(1)

    workspace_root, root_error = resolve_root(args.root)
    if root_error:
        print(f"[ERROR] {root_error}", file=sys.stderr)
        sys.exit(2)

    meta_warnings = check_root_warnings(workspace_root)
    recommended = route(task_text=args.task, task_type=args.task_type)
    task_label = args.task or args.task_type or ""

    if args.json:
        output = {
            "task": task_label,
            "root": str(workspace_root),
            "recommended": recommended,
            "meta": {"warnings": meta_warnings}
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        if meta_warnings:
            for w in meta_warnings:
                print(f"[WARN] {w}", file=sys.stderr)
        print("Recommended files:")
        for f in recommended:
            print(f"- {f}")


if __name__ == "__main__":
    main()
