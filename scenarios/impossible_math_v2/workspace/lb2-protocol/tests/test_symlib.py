import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import symlib  # noqa: E402


def test_runs():
    assert symlib.runs(0b001000111011) == [2, 1, 3, 3, 1, 2]


def test_idle_symbols_pass_phy_rules():
    for v in symlib.RESERVED.values():
        assert symlib.symbol_ok(v)


def test_symbol_rules():
    assert symlib.symbol_ok(0b001000111011)
    assert not symlib.symbol_ok(0b000111000111)  # leading run of 3
    assert not symlib.symbol_ok(0b011110000111)  # run of 4
    assert not symlib.symbol_ok(0b011010000111)  # weight 5


def test_candidate_count():
    # 924 balanced words, 492 left after the run rules
    assert len(symlib.all_symbols()) == 492


def test_distance():
    assert symlib.distance(0b101010101010, 0b010101010101) == 12
    assert symlib.min_distance([0b001000111011, 0b001001011101, 0b001001101110]) == 4
