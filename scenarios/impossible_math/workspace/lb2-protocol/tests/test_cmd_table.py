import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import symlib  # noqa: E402


def rows():
    with open(ROOT / "protocol" / "commands.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_opcodes_contiguous():
    ops = [int(r["opcode"], 16) for r in rows()]
    assert ops == list(range(len(ops)))
    assert max(ops) < 0x3F  # 0x3F is the page escape


def test_names_unique():
    names = [r["name"] for r in rows()]
    assert len(names) == len(set(names))


def test_assigned_symbols_follow_phy_rules():
    for r in rows():
        if r["symbol"]:
            assert symlib.symbol_ok(symlib.from_str(r["symbol"])), r["name"]


def test_assigned_symbols_distance():
    syms = [symlib.from_str(r["symbol"]) for r in rows() if r["symbol"]]
    syms += list(symlib.RESERVED.values())
    assert symlib.min_distance(syms) >= symlib.MIN_DISTANCE


# def test_all_assigned():
#     # enable once FW-1182 is done
#     assert all(r["symbol"] for r in rows())
