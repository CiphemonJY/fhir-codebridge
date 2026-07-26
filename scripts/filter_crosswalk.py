#!/usr/bin/env python3
"""
Filter crosswalk_v3.json down to entries that can actually be returned.

Two classes of row were shipped that never should have been:

  identity      A code mapped to itself — LOINC 10230-1 -> LOINC 10230-1 at
                similarity 1.0. That is not a mapping, and 1,316 of them
                inflated the published count by more than two thirds.

  below floor   Similarity under the router's 0.70 review floor, so the router
                refuses them anyway. Shipping them means shipping data the
                service will always decline to use, and counting it as coverage.
                These are also the rows that were laundering: CVX 10 (polio
                vaccine) -> LOINC 56799-0 "Address" at 0.427.

Writes the filtered file and prints the accounting, because the published count
has to match what survives.
"""
import argparse
import collections
import json
import pathlib
import sys

REVIEW_FLOOR = 0.70


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/terminology_parsed/crosswalk_v3.json")
    ap.add_argument("--apply", action="store_true", help="write the file; otherwise dry run")
    args = ap.parse_args()

    p = pathlib.Path(args.path)
    rows = json.loads(p.read_text(encoding="utf-8"))

    kept, dropped_identity, dropped_low = [], [], []
    for m in rows:
        src_code = m["source"].rsplit("|", 1)[1]
        if src_code == m["target_code"] and m.get("same_system"):
            dropped_identity.append(m)
        elif float(m.get("similarity", 0.0)) < REVIEW_FLOOR:
            dropped_low.append(m)
        else:
            kept.append(m)

    print("in                 %5d" % len(rows))
    print("  identity rows    %5d  (a code mapped to itself)" % len(dropped_identity))
    print("  below %.2f floor  %5d  (router refuses these)" % (REVIEW_FLOOR, len(dropped_low)))
    print("kept               %5d" % len(kept))
    by_target = collections.Counter(m["target_system"] for m in kept)
    print("  by target system %s" % dict(by_target.most_common()))
    cross = sum(1 for m in kept if not m.get("same_system"))
    print("  cross-system     %5d" % cross)
    print("  same-system      %5d  (synonym links within one system)" % (len(kept) - cross))

    if args.apply:
        p.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
        print("\nwrote %s" % p)
    else:
        print("\ndry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
