#!/usr/bin/env python3
"""Read skill_sizes.csv and print aggregate size-distribution stats."""

import csv
import statistics
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent / "skill_sizes.csv"


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def main() -> None:
    rows = []
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            row["entries"] = int(row["entries"])
            row["compressed_bytes"] = int(row["compressed_bytes"])
            row["uncompressed_bytes"] = int(row["uncompressed_bytes"])
            row["largest_file_bytes"] = int(row["largest_file_bytes"])
            rows.append(row)

    if not rows:
        print("No data in CSV.")
        return

    rows.sort(key=lambda r: r["uncompressed_bytes"], reverse=True)

    # --- Per-skill table ---
    header = f"{'org/skill':<45} {'entries':>7} {'compressed':>12} {'uncompressed':>14} {'largest_file':>13} extensions"
    sep = "-" * max(len(header), 120)
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        label = f"{r['org_slug']}/{r['skill_name']}"
        print(
            f"{label:<45} "
            f"{r['entries']:>7} "
            f"{_human(r['compressed_bytes']):>12} "
            f"{_human(r['uncompressed_bytes']):>14} "
            f"{_human(r['largest_file_bytes']):>13} "
            f"{r['extensions']}"
        )
    print(sep)

    # --- Aggregate percentiles ---
    n = len(rows)
    print(f"\n{n} skills sampled\n")

    for label, key in [
        ("uncompressed", "uncompressed_bytes"),
        ("compressed", "compressed_bytes"),
        ("largest_file", "largest_file_bytes"),
        ("entries", "entries"),
    ]:
        vals = sorted(r[key] for r in rows)
        fmt = _human if key != "entries" else str
        if n >= 4:
            qs = statistics.quantiles(vals, n=100)
            p50, p90, p99 = qs[49], qs[89], qs[98]
            print(
                f"  {label:>20}  "
                f"p50={fmt(int(p50)):>10}  "
                f"p90={fmt(int(p90)):>10}  "
                f"p99={fmt(int(p99)):>10}  "
                f"max={fmt(max(vals)):>10}"
            )
        else:
            print(f"  {label:>20}  max={fmt(max(vals)):>10}")

    # --- Extension frequency ---
    ext_counter: Counter[str] = Counter()
    for r in rows:
        for ext in r["extensions"].split():
            if ext:
                ext_counter[ext] += 1
    print(f"\nExtension frequency (top 20):")
    for ext, count in ext_counter.most_common(20):
        print(f"  {ext:<12} {count:>4} skills")


if __name__ == "__main__":
    main()
