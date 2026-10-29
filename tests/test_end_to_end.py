import json
import runpy
from pathlib import Path

from fem_loadcase_viewer.cli import main

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_example_deck_renders(tmp_path):
    runpy.run_path(str(EXAMPLES / "make_bracket.py"))
    assert main([str(EXAMPLES / "bracket.fem"), "-o", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["warnings"] == []
    magnitudes = [s["net_force_magnitude"] for s in summary["subcases"]]
    assert magnitudes == [1500.0, 1081.665]
    assert (tmp_path / "load_case_atlas.png").stat().st_size > 10_000
