#!/usr/bin/env python3
"""Analyze per-file size breakdown by extension from skill_files.csv."""

import csv
from collections import defaultdict
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent / "skill_files.csv"


def _human(n: int | float) -> str:
    n = int(n)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def main() -> None:
    # Accumulate per-extension stats
    ext_stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "total_unc": 0, "total_comp": 0, "max_unc": 0, "skills": set()}
    )
    total_files = 0
    total_unc = 0
    total_comp = 0

    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            if row["is_dir"] == "True":
                continue
            ext = row["extension"] or "(none)"
            unc = int(row["uncompressed_bytes"])
            comp = int(row["compressed_bytes"])
            skill_key = f"{row['org_slug']}/{row['skill_name']}"

            s = ext_stats[ext]
            s["count"] += 1
            s["total_unc"] += unc
            s["total_comp"] += comp
            if unc > s["max_unc"]:
                s["max_unc"] = unc
            s["skills"].add(skill_key)

            total_files += 1
            total_unc += unc
            total_comp += comp

    print(f"Total: {total_files} files, {_human(total_unc)} uncompressed, {_human(total_comp)} compressed\n")

    # --- Table sorted by total uncompressed bytes ---
    sorted_exts = sorted(ext_stats.items(), key=lambda kv: kv[1]["total_unc"], reverse=True)

    header = (
        f"{'extension':<12} {'files':>7} {'skills':>7} "
        f"{'total_unc':>12} {'% unc':>7} "
        f"{'total_comp':>12} {'avg_unc':>10} {'max_unc':>10}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for ext, s in sorted_exts:
        pct = s["total_unc"] / total_unc * 100 if total_unc else 0
        avg = s["total_unc"] / s["count"] if s["count"] else 0
        print(
            f"{ext:<12} {s['count']:>7} {len(s['skills']):>7} "
            f"{_human(s['total_unc']):>12} {pct:>6.1f}% "
            f"{_human(s['total_comp']):>12} {_human(avg):>10} {_human(s['max_unc']):>10}"
        )

    print(sep)

    # --- Top 30 largest individual files ---
    print("\nTop 30 largest individual files:\n")
    big_files: list[dict] = []
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            if row["is_dir"] == "True":
                continue
            big_files.append(row)

    big_files.sort(key=lambda r: int(r["uncompressed_bytes"]), reverse=True)

    header2 = f"{'#':>3}  {'org/skill':<45} {'filepath':<50} {'extension':<8} {'uncompressed':>12} {'compressed':>12}"
    print(header2)
    print("-" * len(header2))
    for i, r in enumerate(big_files[:30], 1):
        label = f"{r['org_slug']}/{r['skill_name']}"
        fp = r["filepath"]
        if len(fp) > 48:
            fp = "…" + fp[-47:]
        print(
            f"{i:>3}  {label:<45} {fp:<50} {r['extension']:<8} "
            f"{_human(int(r['uncompressed_bytes'])):>12} {_human(int(r['compressed_bytes'])):>12}"
        )


if __name__ == "__main__":
    main()
