"""Parser for the subset of Nastran / OptiStruct bulk data needed to show load cases.

Supported: small-field (8-character), large-field (``GRID*``) and free-field
(comma separated) cards, ``+`` continuations, and the case-control commands
SUBCASE / LABEL / ANALYSIS / LOAD / SPC.

Cards read: GRID, CQUAD4, CTRIA3, CROD, RBE2, FORCE, MOMENT, SPC, SPC1, LOAD.
Everything else is counted (``Model.card_counts``) but otherwise ignored.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .model import Constraint, Model, PointLoad, Subcase

_SHORT_EXPONENT = re.compile(r"(?<=[\d.])([+-])(?=\d+$)")


def nastran_float(text: str) -> float:
    """Parse Nastran real numbers, including the short form ``1.5-3`` (= 1.5e-3)."""
    s = text.strip().upper().replace("D", "E")
    if not s:
        return 0.0
    if "E" not in s:
        s = _SHORT_EXPONENT.sub(r"E\1", s)
    return float(s)


def _int(text: str, default: int = 0) -> int:
    text = text.strip()
    return int(text) if text else default


def _split(line: str) -> tuple[str, list[str]]:
    """Return (card name, data fields) for one physical line."""
    line = line.rstrip("\n").rstrip()
    if "," in line[:80]:
        parts = [p.strip() for p in line.split(",")]
        return parts[0].upper(), parts[1:]
    name = line[:8].strip().upper()
    if name.endswith("*"):  # large field: 16-character data fields
        return name, [line[i : i + 16] for i in range(8, min(len(line), 72), 16)]
    return name, [line[i : i + 8] for i in range(8, min(len(line), 72), 8)]


def _cards(lines):
    """Yield (name, fields, line number) with continuation lines merged."""
    current = None
    for number, line in lines:
        if not line.strip() or line.startswith("$"):
            continue
        name, fields = _split(line)
        if name.startswith("+") or name.startswith("*") or (name == "" and current):
            if current:
                current[1].extend(fields)
            continue
        if current:
            yield current
        current = (name.rstrip("*"), fields, number)
    if current:
        yield current


def parse_deck(text: str) -> Model:
    model = Model()
    lines = list(enumerate(text.splitlines(), 1))
    bulk_start = next((i for i, (_, l) in enumerate(lines) if l.upper().startswith("BEGIN BULK")), None)
    control = lines if bulk_start is None else lines[:bulk_start]
    bulk = [] if bulk_start is None else lines[bulk_start + 1 :]

    # --- case control --------------------------------------------------
    case: Subcase | None = None
    for _, line in control:
        s = line.strip()
        upper = s.upper()
        if upper.startswith("SUBCASE"):
            case = Subcase(id=int(s.split()[1]))
            model.subcases.append(case)
        elif case is None or not s or s.startswith("$"):
            continue
        elif upper.startswith("LABEL"):
            case.label = s[5:].lstrip(" =").strip()
        elif upper.startswith("ANALYSIS"):
            case.analysis = s.split(None, 1)[1].strip() if " " in s else ""
        elif re.match(r"(LOAD|SPC)\s*=", upper):
            key, value = upper.split("=", 1)
            setattr(case, "load_set" if key.strip() == "LOAD" else "spc_set", int(value))

    # --- bulk data -------------------------------------------------------
    counts: Counter = Counter()
    forces: dict[int, list[PointLoad]] = defaultdict(list)
    spcs: dict[int, list[Constraint]] = defaultdict(list)
    combos: dict[int, tuple[float, list[tuple[float, int]]]] = {}
    for name, f, number in _cards(bulk):
        if name == "ENDDATA":
            break
        counts[name] += 1
        try:
            if name == "GRID":
                if _int(f[1]) != 0:
                    model.warnings.append(f"line {number}: GRID {f[0].strip()} uses CP={f[1].strip()}; treated as basic")
                model.nodes[_int(f[0])] = np.array([nastran_float(x) for x in f[2:5]])
            elif name == "CQUAD4":
                model.shells.append(tuple(_int(x) for x in f[2:6]))
            elif name == "CTRIA3":
                model.shells.append(tuple(_int(x) for x in f[2:5]))
            elif name == "CROD":
                model.rods.append((_int(f[2]), _int(f[3])))
            elif name == "RBE2":
                independent = _int(f[1])
                model.rigid += [(independent, int(x)) for x in f[3:] if x.strip().lstrip("-").isdigit()]
            elif name in ("FORCE", "MOMENT"):
                if _int(f[2]) != 0:
                    model.warnings.append(f"line {number}: {name} uses CID={f[2].strip()}; treated as basic")
                vec = nastran_float(f[3]) * np.array([nastran_float(x) for x in f[4:7]])
                forces[_int(f[0])].append(PointLoad(_int(f[1]), vec, name))
            elif name == "SPC":
                for i in range(1, len(f) - 1, 3):  # G1 C1 D1 [G2 C2 D2]
                    if f[i].strip():
                        spcs[_int(f[0])].append(Constraint(_int(f[i]), f[i + 1].strip()))
            elif name == "SPC1":
                ids = [x.strip() for x in f[2:] if x.strip()]
                if "THRU" in (x.upper() for x in ids):
                    start, end = int(ids[0]), int(ids[2])
                    ids = [str(n) for n in range(start, end + 1)]
                spcs[_int(f[0])] += [Constraint(int(n), f[1].strip()) for n in ids]
            elif name == "LOAD":
                pairs = [(nastran_float(f[i]), _int(f[i + 1])) for i in range(2, len(f) - 1, 2) if f[i].strip()]
                combos[_int(f[0])] = (nastran_float(f[1]), pairs)
        except (ValueError, IndexError) as exc:
            model.warnings.append(f"line {number}: could not read {name} ({exc})")

    def resolve(set_id: int) -> list[PointLoad]:
        if set_id in combos:
            overall, pairs = combos[set_id]
            return [PointLoad(l.node, overall * scale * l.vector, l.kind) for scale, sid in pairs for l in forces[sid]]
        return list(forces[set_id])

    for case in model.subcases:
        if case.load_set is not None:
            case.loads = resolve(case.load_set)
        if case.spc_set is not None:
            case.constraints = list(spcs[case.spc_set])
        for item in case.loads + case.constraints:
            if item.node not in model.nodes:
                model.warnings.append(f"subcase {case.id}: node {item.node} is not defined by a GRID card")

    model.card_counts = dict(counts)
    return model


def parse_file(path: str | Path) -> Model:
    return parse_deck(Path(path).read_text(encoding="latin-1"))
