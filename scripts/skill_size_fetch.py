#!/usr/bin/env python3
"""Fetch all published skills from the Decision Hub dev registry and write per-skill size data to CSV."""

import csv
import io
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

BASE_URL = "https://pymc-labs--api-dev.modal.run"
TIMEOUT = 60
CSV_PATH = Path(__file__).resolve().parent / "skill_sizes.csv"

CSV_COLUMNS = [
    "org_slug",
    "skill_name",
    "entries",
    "compressed_bytes",
    "uncompressed_bytes",
    "largest_file_bytes",
    "extensions",
]


def fetch_skill_list(page_size: int = 100) -> list[dict]:
    """Fetch the first page of skills from the registry."""
    url = f"{BASE_URL}/v1/skills?page_size={page_size}&page=1"
    with urlopen(Request(url), timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
    print(f"Registry total: {data['total']} skills  (fetched {len(data['items'])})")
    return data["items"]


def analyse_zip(body: bytes) -> dict:
    """Return size metrics for a skill zip's raw bytes."""
    extensions: set[str] = set()
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
    return {
        "entries": len(infos),
        "compressed_bytes": len(body),
        "uncompressed_bytes": total_uncompressed,
        "largest_file_bytes": largest,
        "extensions": " ".join(sorted(extensions)),
    }


def main() -> None:
    skills = fetch_skill_list()

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for i, skill in enumerate(skills, 1):
            org = skill["org_slug"]
            name = skill["skill_name"]
            label = f"{org}/{name}"
            print(f"  [{i:>3}/{len(skills)}] {label} …", end=" ", flush=True)

            try:
                url = f"{BASE_URL}/v1/skills/{org}/{name}/download"
                with urlopen(Request(url), timeout=TIMEOUT) as resp:
                    body = resp.read()
                row = {"org_slug": org, "skill_name": name, **analyse_zip(body)}
                writer.writerow(row)
                f.flush()
                print(f"OK  ({row['compressed_bytes']} bytes)")
            except Exception as exc:
                print(f"FAILED  ({exc})", file=sys.stderr)

    print(f"\nWrote {CSV_PATH}")


if __name__ == "__main__":
    main()
