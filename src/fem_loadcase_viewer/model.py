"""Data model for a parsed deck and the loads/constraints of each subcase."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PointLoad:
    node: int
    vector: np.ndarray  # (3,) in basic coordinates
    kind: str = "FORCE"  # FORCE or MOMENT


@dataclass
class Constraint:
    node: int
    dofs: str  # e.g. "123" = translations fixed


@dataclass
class Subcase:
    id: int
    label: str = ""
    analysis: str = ""
    load_set: int | None = None
    spc_set: int | None = None
    loads: list[PointLoad] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.label or f"Subcase {self.id}"


@dataclass
class Model:
    nodes: dict[int, np.ndarray] = field(default_factory=dict)
    shells: list[tuple[int, ...]] = field(default_factory=list)  # CQUAD4 / CTRIA3 node ids
    rods: list[tuple[int, int]] = field(default_factory=list)  # CROD node pairs
    rigid: list[tuple[int, int]] = field(default_factory=list)  # RBE2 (independent, dependent)
    subcases: list[Subcase] = field(default_factory=list)
    card_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def xyz(self, node: int) -> np.ndarray:
        return self.nodes[node]

    def resultant(self, case: Subcase, about: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Net applied force and moment (about ``about``, default the mesh centroid)."""
        if about is None:
            about = self.centroid()
        force = np.zeros(3)
        moment = np.zeros(3)
        for load in case.loads:
            if load.kind == "FORCE":
                force += load.vector
                moment += np.cross(self.nodes[load.node] - about, load.vector)
            else:
                moment += load.vector
        return force, moment

    def centroid(self) -> np.ndarray:
        used = {n for shell in self.shells for n in shell} or set(self.nodes)
        return np.mean([self.nodes[n] for n in used if n in self.nodes], axis=0)

    def summary(self) -> list[dict]:
        rows = []
        for case in self.subcases:
            force, moment = self.resultant(case)
            rows.append({
                "subcase": case.id,
                "label": case.name,
                "loads": len(case.loads),
                "constrained_nodes": len({c.node for c in case.constraints}),
                "net_force": force.round(3).tolist(),
                "net_force_magnitude": round(float(np.linalg.norm(force)), 3),
                "net_moment_about_centroid": moment.round(1).tolist(),
            })
        return rows
