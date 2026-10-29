"""Command line: ``fem-loadcases model.fem -o out``."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .parser import parse_file
from .render import render_all


def markdown_table(rows: list[dict], units: str) -> str:
    lines = [f"| Subcase | Label | Loads | Supported nodes | Net applied force ({units}) | Magnitude ({units}) |",
             "|---:|---|---:|---:|---|---:|"]
    for r in rows:
        f = ", ".join(f"{x:,.1f}" for x in r["net_force"])
        lines.append(f"| {r['subcase']} | {r['label']} | {r['loads']} | {r['constrained_nodes']} | ({f}) | "
                     f"{r['net_force_magnitude']:,.1f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fem-loadcases", description="Visualise the load cases in a Nastran/OptiStruct deck")
    ap.add_argument("deck", type=Path, help=".fem / .bdf / .dat file")
    ap.add_argument("-o", "--out", type=Path, default=Path("out"))
    ap.add_argument("--up", choices=["Y", "Z"], default="Z", help="vertical axis of the model (default Z)")
    ap.add_argument("--yaw", type=float, default=-35)
    ap.add_argument("--pitch", type=float, default=20)
    ap.add_argument("--units", default="N", help="force unit label for the report (default N)")
    ap.add_argument("--no-images", action="store_true", help="only write the summary report")
    args = ap.parse_args(argv)

    model = parse_file(args.deck)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = model.summary()
    (args.out / "summary.json").write_text(json.dumps({"deck": args.deck.name, "cards": model.card_counts,
                                                         "subcases": rows, "warnings": model.warnings}, indent=2))
    report = f"# Load cases in `{args.deck.name}`\n\n{markdown_table(rows, args.units)}\n"
    if model.warnings:
        report += "\n## Warnings\n\n" + "\n".join(f"- {w}" for w in model.warnings) + "\n"
    (args.out / "summary.md").write_text(report)
    print(f"{len(model.nodes)} nodes, {len(model.shells)} shells, {len(model.subcases)} subcases")
    print(markdown_table(rows, args.units))
    for w in model.warnings[:20]:
        print("warning:", w)
    if not args.no_images:
        for path in render_all(model, args.out, args.yaw, args.pitch, args.up, args.units):
            print("->", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
