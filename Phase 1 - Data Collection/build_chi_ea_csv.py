"""Combine per-year CHI EA DOI lists into a single download CSV."""
import re, csv, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where your per-year EA keep-lists live. Adjust path if you saved them elsewhere.
KEEP_DIR = ROOT / "data" / "keep_lists" / "chi"   # or "chi-ea" if you put them there

# Gather all CHI EA DOIs across years
all_dois = set()
for f in sorted(KEEP_DIR.glob("chi*_ea.txt")):
    dois = set(re.findall(r"10\.1145/\d+\.\d+", f.read_text(encoding="utf-8", errors="ignore")))
    print(f"  {f.name}: {len(dois)} DOIs")
    all_dois |= dois

print(f"\nGrand total (deduped): {len(all_dois)}")

# Check what's already on disk
def stem(d): return d.replace("/", "_").replace(".", "_")

disk_stems = set()
for r, _, files in os.walk(ROOT / "sigchi"):
    for f in files:
        if f.endswith(".pdf"):
            disk_stems.add(f[:-4])

missing = sorted(d for d in all_dois if stem(d) not in disk_stems)
have    = len(all_dois) - len(missing)
print(f"Already on disk: {have}")
print(f"Missing:         {len(missing)}")

# Write the download CSV (venue = CHI-EA → PDFs will land in sigchi/CHI-EA/)
out = ROOT / "data" / "downloads" / "chi_ea_missing.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["doi", "venue", "is_sigchi"])
    for d in missing:
        w.writerow([d, "CHI-EA", "True"])

print(f"\nWrote {out}  ({len(missing)} rows)")
print(f"\nNext: py scripts/sigchi_downloader.py --csv {out.relative_to(ROOT)}")