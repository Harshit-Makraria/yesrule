"""Command line: yesrule serve | hook pre|post | install claude-code | mcp | audit verify | import | demo."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def _session():
    from yesrule.db import make_session_factory

    return make_session_factory()()


def cmd_install(args: argparse.Namespace) -> int:
    from yesrule.adapters.claude_code import install, settings_path

    path = settings_path(args.scope)
    current = json.loads(path.read_text()) if path.exists() else {}
    command = args.command or ("yesrule" if shutil.which("yesrule") else f"{sys.executable} -m yesrule")
    new = install(current, command=command, remove=args.remove)
    text = json.dumps(new, indent=2) + "\n"
    if args.dry_run:
        print(f"# would write {path}\n{text}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(".json.yesrule-backup")
        backup.write_text(path.read_text())
        print(f"backup: {backup}")
    path.write_text(text)
    print(("removed Yesrule hooks from " if args.remove else "installed Yesrule hooks in ") + str(path))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="yesrule", description="Approval layer for AI agents that learns rules.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)

    h = sub.add_parser("hook", help="Claude Code hook entry point (reads stdin)")
    h.add_argument("kind", choices=["pre", "post"])

    i = sub.add_parser("install", help="install integrations")
    i.add_argument("target", choices=["claude-code"])
    i.add_argument("--scope", choices=["user", "project"], default="user")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--remove", action="store_true")
    i.add_argument("--command", help="command Claude Code should run (default: auto-detect)")

    sub.add_parser("mcp", help="run the MCP server over stdio")

    a = sub.add_parser("audit", help="audit log tools")
    a.add_argument("action", choices=["verify"])

    im = sub.add_parser("import", help="import past decisions (generic JSON or n8n executions export)")
    im.add_argument("file", type=Path)

    sub.add_parser("demo", help="seed 30 days of demo data")
    m = sub.add_parser("mine", help="propose rules from history now")
    m.add_argument("--min-confidence", type=float, default=0.90)

    args = p.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("yesrule.api:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "hook":
        from yesrule.adapters.claude_code import main as hook_main

        return hook_main(args.kind)
    if args.cmd == "install":
        return cmd_install(args)
    if args.cmd == "mcp":
        from yesrule.adapters.mcp_server import main as mcp_main

        mcp_main()
        return 0
    if args.cmd == "audit":
        from yesrule.service import verify_audit

        ok, bad, n = verify_audit(_session())
        print(f"{n} entries: " + ("chain OK" if ok else f"TAMPERED at seq {bad}"))
        return 0 if ok else 1
    if args.cmd == "import":
        from yesrule.importer import detect_and_parse, import_decisions

        n = import_decisions(_session(), detect_and_parse(json.loads(args.file.read_text())))
        print(f"imported {n} decisions")
        return 0
    if args.cmd == "demo":
        from yesrule.demo import seed

        print(f"seeded {seed(_session())} decisions")
        return 0
    if args.cmd == "mine":
        from yesrule.core.miner import MinerSettings
        from yesrule.service import propose_rules

        for r in propose_rules(_session(), MinerSettings(min_confidence=args.min_confidence)):
            print(f"{r.id}: {r.description}  {r.evidence}")
        return 0
    return 1
