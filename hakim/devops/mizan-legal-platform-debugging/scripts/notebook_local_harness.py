#!/usr/bin/env python3
"""Execute a Colab notebook locally, so fixes are verified before handoff.

A notebook cell cannot be tested in the runtime you do not control. This
execs cells with Colab-only pieces stubbed, so the failure modes that otherwise
reach the operator one runtime error per re-run are caught here first:

* NameError from a cell relying on an earlier cell's namespace
* TypeError from importing a module where a callable was needed
* a cell that must run before another (config read at module level)
* every handler-level fault a GET-only smoke test cannot see

The cross-cell check is the important one. A fresh namespace per cell -- the
obvious design -- cannot see a missing dependency at all, because the cell that
would have failed is simply never sharing scope with the one that defines it.

Usage
-----
    # parse every code cell
    python notebook_local_harness.py notebook.ipynb

    # static cross-cell dependency check (no execution)
    python notebook_local_harness.py notebook.ipynb --deps

    # exec every cell into ONE shared namespace, reporting the first failure
    python notebook_local_harness.py notebook.ipynb --all

    # exec one cell, then drive an entry point
    python notebook_local_harness.py notebook.ipynb --cell 6
    python notebook_local_harness.py notebook.ipynb --marker 'class Handler' \\
        --stub 'transcribe=def transcribe(png): return "stub"' \\
        --call "Handler"

Cells are exec'd in order. Magics are stripped at COLUMN 0 ONLY -- an indented
'%' is an operator continuation, not a magic.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import json
import sys
import types
from pathlib import Path

# Stubs for the names a Colab cell expects to find in the runtime. Stub the
# DEPENDENCY, never the thing under test -- a fake standing in for the code you
# are checking hides the defect it was written to find.
COLAB_STUBS: dict[str, object] = {
    "userdata": {"get": lambda key: None},
    "drive": {"mount": lambda *a, **k: None},
    "get_ipython": lambda: None,
}


def load_cells(path: Path) -> list[str]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in nb.get("cells", [])
            if c.get("cell_type") == "code"]


def strip_magics(source: str) -> str:
    """Remove shell/line magics. Column 0 only -- an indented '%' is code."""
    return "\n".join(l for l in source.split("\n") if not l.startswith(("!", "%")))


def bound_names(tree: ast.AST) -> set[str]:
    """Every name the unit binds, at any scope depth."""
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            args = getattr(n, "args", None)
            if args:
                for a in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
                    out.add(a.arg)
                if args.vararg:
                    out.add(args.vararg.arg)
                if args.kwarg:
                    out.add(args.kwarg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                out.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.comprehension) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def free_names(tree: ast.AST) -> set[str]:
    """Names the unit reads that it does not itself bind."""
    used = {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return used - bound_names(tree)


def dependency_check(cells: list[str]) -> bool:
    """Every free name must be bound by an earlier cell, a builtin, or a stub.

    Order matters, which is the whole point: a cell that reads a value another
    cell assigns at MODULE level only works if it runs first, and this reports
    that before anything is executed.
    """
    available = set(dir(builtins)) | {"__name__", "__file__", "self", "cls"}
    available |= set(COLAB_STUBS)
    ok = True
    for i, src in enumerate(cells):
        tree = ast.parse(strip_magics(src))
        missing = free_names(tree) - available
        if missing:
            ok = False
            print(f"  [BAD] cell {i}: undefined {sorted(missing)}")
        available |= bound_names(tree)
    print("cross-cell dependencies OK" if ok else "UNDEFINED NAMES ABOVE")
    return ok


def syntax_check(cells: list[str]) -> bool:
    ok = True
    for i, src in enumerate(cells):
        try:
            ast.parse(strip_magics(src))
        except SyntaxError as e:
            ok = False
            print(f"  [BAD] cell {i}: {e}")
    print("all cells parse" if ok else "SYNTAX ERRORS ABOVE")
    return ok


def make_ns(stubs: list[str]) -> dict:
    ns: dict = {"__name__": "__main__"}
    for name, val in COLAB_STUBS.items():
        ns[name] = types.SimpleNamespace(**val) if isinstance(val, dict) else val
    for stub in stubs:
        name, _, body = stub.partition("=")
        name, body = name.strip(), body.strip()
        exec(compile(body, f"<stub:{name}>", "exec"), ns)   # noqa: S102
    return ns


def exec_all(cells: list[str], stubs: list[str], skip_marker: str | None) -> bool:
    """Run every cell in ONE shared namespace; report the first failure."""
    ns = make_ns(stubs)
    ran = 0
    for i, src in enumerate(cells):
        if skip_marker and skip_marker in src:
            print(f"  cell {i}: skipped (--skip-marker)")
            continue
        try:
            exec(compile(strip_magics(src), f"<cell {i}>", "exec"), ns)  # noqa: S102
        except Exception as exc:                                       # noqa: BLE001
            print(f"  [BAD] cell {i}: {type(exc).__name__}: {exc}")
            return False
        ran += 1
        print(f"  cell {i}: ok")
    print(f"{ran}/{len(cells)} cells exec'd")
    return True


def find_cell(cells: list[str], index: int | None, marker: str | None) -> int | None:
    if index is not None:
        return index
    if marker:
        for i, s in enumerate(cells):
            if marker in s:
                return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notebook", type=Path)
    ap.add_argument("--cell", type=int, help="cell index to exec")
    ap.add_argument("--marker", help="substring identifying the cell to exec")
    ap.add_argument("--all", action="store_true",
                    help="exec every cell into one shared namespace")
    ap.add_argument("--deps", action="store_true",
                    help="static cross-cell dependency check")
    ap.add_argument("--skip-marker",
                    help="substring marking cells to skip during --all "
                         "(e.g. a teardown cell that stops the server)")
    ap.add_argument("--stub", action="append", default=[],
                    help="name=python-source injected into the namespace")
    ap.add_argument("--call", help="dotted expression evaluated after exec")
    ap.add_argument("--list", action="store_true", help="list cells and exit")
    args = ap.parse_args()

    cells = load_cells(args.notebook)

    if args.list:
        for i, src in enumerate(cells):
            head = next((l for l in strip_magics(src).strip().split("\n")
                         if l.strip()), "")
            print(f"  [{i:>2}] {head[:90]}")
        return 0

    if args.deps:
        return 0 if dependency_check(cells) else 1

    if args.all:
        return 0 if exec_all(cells, args.stub, args.skip_marker) else 1

    if args.cell is None and args.marker is None:
        ok = syntax_check(cells)
        ok = dependency_check(cells) and ok
        return 0 if ok else 1

    idx = find_cell(cells, args.cell, args.marker)
    if idx is None:
        print(f"no cell matched marker {args.marker!r}")
        return 2

    source = strip_magics(cells[idx])
    ns = make_ns(args.stub)
    try:
        exec(compile(source, f"<cell {idx}>", "exec"), ns)              # noqa: S102
    except Exception as exc:                                           # noqa: BLE001
        print(f"cell {idx} raised on exec: {type(exc).__name__}: {exc}")
        return 1

    print(f"cell {idx} exec OK ({len(source)} chars)")
    if args.call:
        try:
            print("->", eval(args.call, ns))                            # noqa: S307
        except Exception as exc:                                       # noqa: BLE001
            print(f"{args.call} raised: {type(exc).__name__}: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())