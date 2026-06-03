"""Quick diff: PDFs on disk vs the official RA list. Shows the 18 extras."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RA_FILE = ROOT / "data" / "keep_lists" / "chi" / "chi24_ra.txt"
FOLDER  = ROOT / "sigchi" / "VERIFIED COUNT" / "CHI" / "2024" / "Research Article"

ra_dois  = set(re.findall(r"10\.1145/\d+\.\d+", RA_FILE.read_text(encoding="utf-8", errors="ignore")))
ra_stems = {d.replace("/", "_").replace(".", "_") for d in ra_dois}

on_disk = {p.stem for p in FOLDER.glob("*.pdf")}

print(f"RA list:   {len(ra_stems)}")
print(f"On disk:   {len(on_disk)}")
print(f"Extras (on disk, NOT in RA list):  {len(on_disk - ra_stems)}")
print(f"Missing  (in RA list, not on disk): {len(ra_stems - on_disk)}")

print("\nExtras (these are the suspect non-RA files):")
for s in sorted(on_disk - ra_stems):
    doi = s.replace("10_1145_", "10.1145/", 1).replace("_", ".", 1)
    # restore dotted form: 10_1145_3613904_3642XYZ -> 10.1145/3613904.3642XYZ
    parts = s.split("_")
    if len(parts) >= 4:
        doi = f"{parts[0]}.{parts[1]}/{parts[2]}.{parts[3]}"
    print(f"  {doi}    https://dl.acm.org/doi/{doi}")

if ra_stems - on_disk:
    print("\nMissing (in RA list but not yet downloaded):")
    for s in sorted(ra_stems - on_disk):
        parts = s.split("_")
        doi = f"{parts[0]}.{parts[1]}/{parts[2]}.{parts[3]}" if len(parts) >= 4 else s
        print(f"  {doi}")
