"""Organize sigchi/CHI-EA/ into year subfolders using the per-year keep-lists.

The keep-lists in data/keep_lists/chi/chi<YY>_ea.txt are the source of truth.
PDFs not in any keep-list are left in place (potential candidates for review).
"""
import shutil, re, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EA_DIR = ROOT / "sigchi" / "CHI-EA"
KEEP_DIR = ROOT / "data" / "keep_lists" / "chi"

def stem(d: str) -> str:
    return d.replace("/", "_").replace(".", "_")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print plan, don't move.")
    args = ap.parse_args()

    if not EA_DIR.exists():
        print(f"ERROR: {EA_DIR} not found"); return

    # Build {stem: year} index from keep-lists
    target = {}  # stem -> year
    for keep_file in sorted(KEEP_DIR.glob("chi*_ea.txt")):
        m = re.search(r"chi(\d{2})_ea", keep_file.name)
        if not m: continue
        year = "20" + m.group(1)
        dois = set(re.findall(r"10\.1145/\d+\.\d+",
                              keep_file.read_text(encoding="utf-8", errors="ignore")))
        for d in dois:
            target[stem(d)] = year
        print(f"  {keep_file.name}: {len(dois)} DOIs  -> year {year}")

    print(f"\nTotal targets across keep-lists: {len(target)}")

    # Walk top-level PDFs only; don't disturb files already in year subfolders
    moved = {}
    unmatched = []
    for pdf in EA_DIR.glob("*.pdf"):
        year = target.get(pdf.stem)
        if year is None:
            unmatched.append(pdf.name); continue
        dest = EA_DIR / year
        if args.dry_run:
            print(f"  would move {pdf.name} -> {year}/")
        else:
            dest.mkdir(exist_ok=True)
            shutil.move(str(pdf), str(dest / pdf.name))
        moved[year] = moved.get(year, 0) + 1

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Moved by year:")
    for y in sorted(moved):
        live = len(list((EA_DIR / y).glob("*.pdf"))) if (EA_DIR / y).exists() else 0
        print(f"  {y}: moved={moved[y]}  on disk total={live}")

    print(f"\nLeft at top level (not in any keep-list): {len(unmatched)}")
    if unmatched:
        for u in unmatched[:5]:
            print(f"  {u}")
        if len(unmatched) > 5:
            print(f"  ... and {len(unmatched)-5} more")

if __name__ == "__main__":
    main()