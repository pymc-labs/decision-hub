#!/usr/bin/env python3
"""Fetch published skills from the Decision Hub dev registry and write size data to CSV.

Produces two files:
  skill_sizes.csv  — one row per skill (aggregate metrics)
  skill_files.csv  — one row per file inside each skill zip (per-file metrics)
"""

import csv
import io
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

BASE_URL = "https://pymc-labs--api-dev.modal.run"
TIMEOUT = 60
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_CSV = SCRIPT_DIR / "skill_sizes.csv"
FILES_CSV = SCRIPT_DIR / "skill_files.csv"

SKILL_COLUMNS = [
    "org_slug",
    "skill_name",
    "entries",
    "compressed_bytes",
    "uncompressed_bytes",
    "largest_file_bytes",
    "extensions",
]

FILE_COLUMNS = [
    "org_slug",
    "skill_name",
    "filepath",
    "extension",
    "uncompressed_bytes",
    "compressed_bytes",
    "is_dir",
]


def fetch_skill_list(page_size: int = 100) -> list[dict]:
    """Fetch all skills from the registry, paginating until exhausted."""
    all_items: list[dict] = []
    page = 1
    total_pages = 1  # updated after first response
    while page <= total_pages:
        url = f"{BASE_URL}/v1/skills?page_size={page_size}&page={page}"
        with urlopen(Request(url), timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
        items = data["items"]
        total = data["total"]
        total_pages = data.get("total_pages", (total + page_size - 1) // page_size)
        all_items.extend(items)
        print(f"  Page {page}/{total_pages}: got {len(items)} skills  (registry total: {total})")
        if not items:
            break
        page += 1
    print(f"  Fetched {len(all_items)} skills to download.\n")
    return all_items


def analyse_zip(body: bytes, org_slug: str, skill_name: str) -> tuple[dict, list[dict]]:
    """Return (skill_row, file_rows) for a skill zip's raw bytes."""
    extensions: set[str] = set()
    file_rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        infos = zf.infolist()
        total_uncompressed = 0
        largest = 0
        for info in infos:
            total_uncompressed += info.file_size
            if info.file_size > largest:
                largest = info.file_size
            ext = PurePosixPath(info.filename).suffix
            if ext:
                extensions.add(ext)
            file_rows.append(
                {
                    "org_slug": org_slug,
                    "skill_name": skill_name,
                    "filepath": info.filename,
                    "extension": ext,
                    "uncompressed_bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    "is_dir": info.is_dir(),
                }
            )
    skill_row = {
        "entries": len(infos),
        "compressed_bytes": len(body),
        "uncompressed_bytes": total_uncompressed,
        "largest_file_bytes": largest,
        "extensions": " ".join(sorted(extensions)),
    }
    return skill_row, file_rows


def main() -> None:
    skills = fetch_skill_list()
    total = len(skills)

    with (
        SKILL_CSV.open("w", newline="") as sf,
        FILES_CSV.open("w", newline="") as ff,
    ):
        skill_writer = csv.DictWriter(sf, fieldnames=SKILL_COLUMNS)
        skill_writer.writeheader()
        file_writer = csv.DictWriter(ff, fieldnames=FILE_COLUMNS)
        file_writer.writeheader()

        ok = 0
        total_files = 0
        for i, skill in enumerate(skills, 1):
            org = skill["org_slug"]
            name = skill["skill_name"]
            label = f"{org}/{name}"
            print(f"  [{i:>{len(str(total))}}/{total}] {label} …", end=" ", flush=True)

            try:
                url = f"{BASE_URL}/v1/skills/{org}/{name}/download"
                with urlopen(Request(url), timeout=TIMEOUT) as resp:
                    body = resp.read()
                skill_row, file_rows = analyse_zip(body, org, name)
                skill_writer.writerow({"org_slug": org, "skill_name": name, **skill_row})
                sf.flush()
                file_writer.writerows(file_rows)
                ff.flush()
                ok += 1
                total_files += len(file_rows)
                print(f"OK  ({skill_row['compressed_bytes']} bytes, {len(file_rows)} files)")
            except Exception as exc:
                print(f"FAILED  ({exc})", file=sys.stderr)

    print(f"\nWrote {ok}/{total} skills to {SKILL_CSV}")
    print(f"Wrote {total_files} file entries to {FILES_CSV}")


if __name__ == "__main__":
    main()
