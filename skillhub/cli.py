"""Command-line interface for SKILLHUB.

Subcommands:
  list      list skills in a registry
  search    rank skills by a query
  info      show a skill's manifest + dependency install order
  install   install a skill (and deps) into an agent skills dir
  installed show what's installed in a target dir
  remove    uninstall a skill from a target dir

Global flags: --version, --format {table,json}
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from skillhub import TOOL_NAME, TOOL_VERSION
from skillhub.core import Registry, SkillError, resolve_dependencies


def _emit(fmt: str, payload, table_fn) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        table_fn(payload)


def _print_skill_rows(rows: List[dict]) -> None:
    if not rows:
        print("(no skills)")
        return
    nw = max([len(r["name"]) for r in rows] + [4])
    vw = max([len(r["version"]) for r in rows] + [7])
    print(f"{'NAME':<{nw}}  {'VERSION':<{vw}}  DESCRIPTION")
    for r in rows:
        print(f"{r['name']:<{nw}}  {r['version']:<{vw}}  {r['description']}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Local skill registry and installer for AI agents.",
    )
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--format", choices=["table", "json"], default="table")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="list skills in a registry")
    lp.add_argument("-r", "--registry", default=".")

    sp = sub.add_parser("search", help="rank skills by a query")
    sp.add_argument("query")
    sp.add_argument("-r", "--registry", default=".")

    ip = sub.add_parser("info", help="show a skill manifest + deps")
    ip.add_argument("name")
    ip.add_argument("-r", "--registry", default=".")

    inp = sub.add_parser("install", help="install a skill into a target dir")
    inp.add_argument("name")
    inp.add_argument("-r", "--registry", default=".")
    inp.add_argument("-t", "--target", required=True)
    inp.add_argument("--force", action="store_true")

    sdp = sub.add_parser("installed", help="list installed skills in a target")
    sdp.add_argument("-t", "--target", required=True)

    rp = sub.add_parser("remove", help="uninstall a skill from a target")
    rp.add_argument("name")
    rp.add_argument("-t", "--target", required=True)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    fmt = args.format
    try:
        if args.cmd == "list":
            reg = Registry(args.registry)
            rows = [s.to_dict() for s in sorted(
                reg.skills().values(), key=lambda s: s.name)]
            _emit(fmt, rows, _print_skill_rows)
            return 0

        if args.cmd == "search":
            reg = Registry(args.registry)
            ranked = reg.search(args.query)
            rows = []
            for sk, score in ranked:
                d = sk.to_dict()
                d["score"] = score
                rows.append(d)
            _emit(fmt, rows, _print_skill_rows)
            if not rows:
                return 1
            return 0

        if args.cmd == "info":
            reg = Registry(args.registry)
            sk = reg.get(args.name)
            order = resolve_dependencies(args.name, reg.skills())
            payload = sk.to_dict()
            payload["install_order"] = order
            payload["content_hash"] = sk.content_hash()

            def _t(pl):
                print(f"{pl['name']} {pl['version']}")
                print(pl["description"])
                if pl.get("author"):
                    print(f"author: {pl['author']}")
                if pl.get("tags"):
                    print("tags: " + ", ".join(pl["tags"]))
                print("install order: " + " -> ".join(pl["install_order"]))
                print(f"hash: {pl['content_hash'][:16]}")

            _emit(fmt, payload, _t)
            return 0

        if args.cmd == "install":
            reg = Registry(args.registry)
            report = reg.install(args.name, args.target, force=args.force)

            def _t(pl):
                print(f"target: {pl['target']}")
                print("installed: " + (", ".join(pl["installed"]) or "(none)"))
                if pl["skipped"]:
                    print("skipped: " + ", ".join(pl["skipped"]))

            _emit(fmt, report, _t)
            return 0

        if args.cmd == "installed":
            reg = Registry(".")
            inst = reg.installed(args.target)
            rows = [
                {"name": n, "version": m.get("version", "?"),
                 "description": "requires: " + (
                     ", ".join(m.get("requires", [])) or "-")}
                for n, m in sorted(inst.items())
            ]
            _emit(fmt, rows if fmt == "table" else inst, _print_skill_rows)
            return 0

        if args.cmd == "remove":
            reg = Registry(".")
            report = reg.remove(args.name, args.target)
            _emit(fmt, report, lambda pl: print(f"removed {pl['removed']}"))
            return 0

    except SkillError as exc:
        if fmt == "json":
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
