import numpy as np
import pytest

from fem_loadcase_viewer import nastran_float, parse_deck

DECK = """\
SUBCASE 1
  LABEL = gravity
  ANALYSIS STATICS
  SPC = 1
  LOAD = 5
SUBCASE 2
  LABEL combined
  SPC = 1
  LOAD = 9
BEGIN BULK
GRID           1              0.      0.      0.
GRID           2              1.      0.      0.
GRID           3              1.      1.      0.
GRID,4,,0.,1.,0.
{large_grid}
CQUAD4         1       1       1       2       3       4
CTRIA3         2       1       2       5       3
RBE2         100       5  123456       1       2       3       4
+              6
SPC            1       1     123      0.       2      12      0.
SPC1           1     456       3    THRU       4
FORCE          5       3       0     10.      0.      0.     -1.
FORCE          6       5       0      2.      1.      0.      0.
MOMENT         7       5       0      1.      0.      0.     50.
LOAD           9      2.      1.       5      .5       6
ENDDATA
""".format(
    # large-field GRID: 8-char name, then 16-char fields (ID, CP, X1, X2), continued X3
    large_grid="GRID*".ljust(8) + "5".rjust(16) + "".rjust(16) + "2.".rjust(16) + "0.".rjust(16)
    + "\n" + "*".ljust(8) + "0.".rjust(16)
)


@pytest.mark.parametrize("text,value", [("1.5", 1.5), ("1.5-3", 1.5e-3), ("-6.707-3", -6.707e-3),
                                        ("2.+4", 2e4), ("1.0E-2", 0.01), ("3.D2", 300.0), ("  ", 0.0), ("7", 7.0)])
def test_nastran_float(text, value):
    assert nastran_float(text) == pytest.approx(value)


@pytest.fixture(scope="module")
def model():
    return parse_deck(DECK)


def test_grid_formats(model):
    assert set(model.nodes) == {1, 2, 3, 4, 5}
    assert np.allclose(model.nodes[4], [0, 1, 0])  # free field
    assert np.allclose(model.nodes[5], [2, 0, 0])  # large field with continuation


def test_elements_and_rbe2_continuation(model):
    assert model.shells == [(1, 2, 3, 4), (2, 5, 3)]
    assert model.rigid == [(5, 1), (5, 2), (5, 3), (5, 4), (5, 6)]


def test_subcases(model):
    gravity, combined = model.subcases
    assert (gravity.id, gravity.label, gravity.analysis) == (1, "gravity", "STATICS")
    assert combined.label == "combined" and combined.load_set == 9


def test_constraints_spc_and_spc1_thru(model):
    dofs = {(c.node, c.dofs) for c in model.subcases[0].constraints}
    assert dofs == {(1, "123"), (2, "12"), (3, "456"), (4, "456")}


def test_force_scale_factor(model):
    (load,) = model.subcases[0].loads
    assert load.node == 3 and np.allclose(load.vector, [0, 0, -10])


def test_load_combination(model):
    force, _ = model.resultant(model.subcases[1], about=np.zeros(3))
    # 2.0 * (1.0 * FORCE 5 + 0.5 * FORCE 6) = 2 * ([0,0,-10] + [1,0,0])
    assert np.allclose(force, [2, 0, -20])


def test_resultant_moment(model):
    _, moment = model.resultant(model.subcases[0], about=np.zeros(3))
    # r = (1, 1, 0), F = (0, 0, -10) -> M = r x F = (-10, 10, 0)
    assert np.allclose(moment, [-10, 10, 0])


def test_missing_node_is_reported():
    deck = "SUBCASE 1\n  LOAD = 1\nBEGIN BULK\nFORCE          1      99       0      1.      1.      0.      0.\nENDDATA\n"
    assert any("node 99" in w for w in parse_deck(deck).warnings)


def test_summary_rows(model):
    rows = model.summary()
    assert [r["subcase"] for r in rows] == [1, 2]
    assert rows[0]["net_force_magnitude"] == pytest.approx(10.0)
