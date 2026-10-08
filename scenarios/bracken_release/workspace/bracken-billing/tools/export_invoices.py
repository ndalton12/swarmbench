import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.exporter import run

parser = argparse.ArgumentParser(description="Prepare partner invoice CSVs")
parser.add_argument("--input", required=True)
parser.add_argument("--policy", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()
accepted, rejected = run(args.input, args.policy, args.out)
print(f"Prepared {accepted} invoices; {rejected} rejected. Output: {args.out}")
