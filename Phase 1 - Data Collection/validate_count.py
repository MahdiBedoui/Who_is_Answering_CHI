"""
Validate a venue's expected paper count against two bibliographic sources
(Crossref + OpenAlex) so we don't trust a single source blindly.

Usage examples:
    # PACMHCI ISS issue in 2024
    python validate_count.py --issn 2573-0142 --year 2024 --issue ISS

    # ACM CHI proceedings 2024 (proc-style DOI prefix)
    python validate_count.py --proc-prefix 10.1145/3613904 --year 2024

    # Free container-title search
    python validate_count.py --container "Proceedings of the 2024 ACM..." --year 2024
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

UA = "sigchi-fetcher/1.0 (mailto:bedouimehdi39@gmail.com)"


def crossref_count(args):
    """Cursor-paginate Crossref and return matched DOIs."""
    filters = []
    if args.issn:
        filters.append(f"issn:{args.issn}")
    if args.year:
        filters.append(f"from-pub-date:{args.year}-01-01")
        filters.append(f"until-pub-date:{args.year}-12-31")
    if args.type:
        filters.append(f"type:{args.type}")
    # If only proc-prefix given (no issn/container), narrow Crossref via ACM member + prefix
    if args.proc_prefix and not args.issn and not args.container:
        filters.append("prefix:10.1145")
        filters.append("member:320")  # ACM is Crossref member 320

    items = []
    cursor = "*"
    page = 0
    while True:
        page += 1
        params = {
            "filter": ",".join(filters),
            "rows": "1000",
            "cursor": cursor,
            "select": "DOI,issue,page,title",
        }
        if args.container:
            params["query.container-title"] = args.container

        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())["message"]
        except Exception as e:
            print(f"  Crossref err: {e}", file=sys.stderr)
            break
        page_items = data.get("items", [])
        # If we have a prefix filter, count only matching items so we can stop early
        # when later pages stop matching (Crossref sorts by relevance)
        if args.proc_prefix:
            matching = [it for it in page_items
                        if it.get("DOI", "").startswith(args.proc_prefix + ".")]
            print(f"  page {page}: {len(page_items)} returned, {len(matching)} match prefix "
                  f"({len(items)} running)", file=sys.stderr)
            # if a page returns ZERO matches AND we already collected some, we're past relevance
            if len(matching) == 0 and items:
                break
        else:
            print(f"  page {page}: {len(page_items)} returned ({len(items)+len(page_items)} total)",
                  file=sys.stderr)
        page_items = data.get("items", [])
        if not page_items:
            break
        items.extend(page_items)
        nxt = data.get("next-cursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)

    # filter by proc prefix and/or issue tag
    if args.proc_prefix:
        items = [it for it in items if it.get("DOI", "").startswith(args.proc_prefix + ".")]
    if args.issue:
        items = [it for it in items if (it.get("issue") or "").upper() == args.issue.upper()]
    return items


def openalex_count(args):
    if not args.issn:
        print("  (skipped: OpenAlex needs --issn to filter efficiently)", file=sys.stderr)
        return []
    filters = []
    filters.append(f"primary_location.source.issn:{args.issn}")
    if args.year:
        filters.append(f"publication_year:{args.year}")

    items = []
    cursor = "*"
    while True:
        params = {
            "filter": ",".join(filters),
            "per_page": "200",
            "cursor": cursor,
            "select": "id,doi,title,biblio",
            "mailto": "bedouimehdi39@gmail.com",
        }
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(urllib.request.urlopen(url, timeout=30).read())
        except Exception as e:
            print(f"  OpenAlex err: {e}", file=sys.stderr)
            break
        results = data.get("results", [])
        if not results:
            break
        items.extend(results)
        nxt = data.get("meta", {}).get("next_cursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.3)

    if args.proc_prefix:
        items = [it for it in items
                 if (it.get("doi") or "").replace("https://doi.org/", "")
                    .startswith(args.proc_prefix + ".")]
    if args.issue:
        items = [it for it in items
                 if (it.get("biblio", {}).get("issue") or "").upper() == args.issue.upper()]
    return items


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--issn",        help="Journal ISSN, e.g. 2573-0142")
    p.add_argument("--year",        type=int, help="Publication year")
    p.add_argument("--proc-prefix", help="DOI prefix like 10.1145/3613904")
    p.add_argument("--container",   help="Container title (Crossref fuzzy match)")
    p.add_argument("--issue",       help="Issue name, e.g. GROUP, ISS, CSCW1")
    p.add_argument("--type",        default="journal-article",
                   help="Crossref type (default: journal-article; use 'proceedings-article' for conf)")
    args = p.parse_args()

    print(f"Filters: issn={args.issn} year={args.year} proc={args.proc_prefix} "
          f"issue={args.issue} container={args.container!r}")

    print("\n=== Crossref ===")
    cr = crossref_count(args)
    print(f"  matched: {len(cr)}")
    cr_dois = {it["DOI"] for it in cr}

    print("\n=== OpenAlex ===")
    oa = openalex_count(args)
    print(f"  matched: {len(oa)}")
    oa_dois = {(it.get("doi") or "").replace("https://doi.org/", "") for it in oa}

    only_cr = cr_dois - oa_dois
    only_oa = oa_dois - cr_dois
    print(f"\n=== Diff ===")
    print(f"  Both:        {len(cr_dois & oa_dois)}")
    print(f"  Only Crossref: {len(only_cr)}")
    print(f"  Only OpenAlex: {len(only_oa)}")
    if only_cr and args.issn:
        print(f"\n  Only-Crossref DOIs:")
        for d in sorted(only_cr)[:10]:
            print(f"    {d}")
    if only_oa and args.issn:
        for d in sorted(only_oa)[:10]:
            print(f"    {d}")


if __name__ == "__main__":
    main()
