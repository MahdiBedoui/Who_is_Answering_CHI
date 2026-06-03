"""Audit sigchi/CHI-EA/ — count PDFs by proc-id to find the surplus."""
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
EA_DIR = ROOT / "sigchi" / "CHI-EA"

# What I currently assume the 5 EA procs are
EXPECTED = {
    "3491101": "CHI '22 EA",
    "3544549": "CHI '23 EA",
    "3613905": "CHI '24 EA",
    "3706599": "CHI '25 EA",
    "3772319": "CHI '26 EA",
}

procs = Counter()
for pdf in EA_DIR.rglob("*.pdf"):   # recursive in case some are in year folders already
    m = re.match(r"10_1145_(\d+)_\d+", pdf.stem)
    if m: procs[m.group(1)] += 1

print(f"Total PDFs found: {sum(procs.values())}\n")
print(f"{'proc-id':<10} {'count':>6}  status")
print("-" * 50)
for proc, n in procs.most_common():
    status = EXPECTED.get(proc, "❓ NOT in my mapping")
    print(f"{proc:<10} {n:>6}  {status}")

# Highlight surplus
expected_total = sum(n for p, n in procs.items() if p in EXPECTED)
surplus_total  = sum(n for p, n in procs.items() if p not in EXPECTED)
print(f"\nExpected procs total: {expected_total}")
print(f"Surplus (unmapped):   {surplus_total}")