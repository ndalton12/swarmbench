import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.settlement_ref import normalize

for line in sys.stdin:
    if line.strip():
        print(normalize(line))
