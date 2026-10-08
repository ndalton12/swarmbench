"""Small helpers for LB2 symbols (used by gen_cmd_table.py and the tests).

The constants mirror the symbols: section of config/lb2_spec.yaml. Keep them in sync
(the build hosts don't all have PyYAML, which is why they're duplicated here).
"""

BITS = 12
WEIGHT = 6
MAX_RUN = 3
MAX_EDGE_RUN = 2
MIN_DISTANCE = 4
RESERVED = {"IDLE_A": 0b010101010101, "IDLE_B": 0b101010101010}


def to_str(value: int) -> str:
    return format(value, f"0{BITS}b")


def from_str(s: str) -> int:
    s = s.strip()
    if len(s) != BITS or set(s) - {"0", "1"}:
        raise ValueError(f"not a {BITS}-bit symbol: {s!r}")
    return int(s, 2)


def weight(value: int) -> int:
    return bin(value).count("1")


def runs(value: int) -> list[int]:
    s = to_str(value)
    out, cur = [], 1
    for a, b in zip(s, s[1:]):
        if a == b:
            cur += 1
        else:
            out.append(cur)
            cur = 1
    out.append(cur)
    return out


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def symbol_ok(value: int) -> bool:
    r = runs(value)
    return weight(value) == WEIGHT and max(r) <= MAX_RUN and r[0] <= MAX_EDGE_RUN and r[-1] <= MAX_EDGE_RUN


def all_symbols() -> list[int]:
    """Every word that passes the PHY rules (ignores distance)."""
    return [v for v in range(1 << BITS) if symbol_ok(v)]


def min_distance(values) -> int:
    values = list(values)
    best = BITS
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            best = min(best, distance(a, b))
    return best
