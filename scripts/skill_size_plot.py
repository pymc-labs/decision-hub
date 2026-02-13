#!/usr/bin/env python3
"""Generate log-log histogram of skill sizes to check for power-law behavior."""

import csv
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

matplotlib.use("Agg")  # headless

CSV_PATH = Path(__file__).resolve().parent / "skill_sizes.csv"
OUT_DIR = Path(__file__).resolve().parent


def load_sizes() -> list[int]:
    sizes: list[int] = []
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            sizes.append(int(row["uncompressed_bytes"]))
    return sizes


def _human_label(x: float, _pos: object = None) -> str:
    if x < 1024:
        return f"{int(x)} B"
    if x < 1024 * 1024:
        return f"{x / 1024:.0f} KB"
    return f"{x / (1024 * 1024):.1f} MB"


def main() -> None:
    sizes = load_sizes()
    sizes_arr = np.array(sizes, dtype=float)
    n = len(sizes_arr)
    print(f"Loaded {n} skills")

    # --- 1) Log-log histogram (log-spaced bins, log count axis) ---
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Left panel: histogram with log-spaced bins
    ax1 = axes[0]
    lo, hi = sizes_arr.min(), sizes_arr.max()
    bins = np.logspace(np.log10(max(lo, 1)), np.log10(hi), 40)
    ax1.hist(sizes_arr, bins=bins, edgecolor="white", linewidth=0.5, color="#4C72B0", alpha=0.85)
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Uncompressed size (bytes)")
    ax1.set_ylabel("Number of skills")
    ax1.set_title(f"Skill size distribution (n={n})")
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(_human_label))
    ax1.grid(True, which="both", alpha=0.3, linestyle="--")

    # Right panel: complementary CDF (survival function) — classic power-law check
    ax2 = axes[1]
    sorted_sizes = np.sort(sizes_arr)[::-1]
    rank = np.arange(1, n + 1)
    ccdf = rank / n  # P(X >= x)
    ax2.scatter(sorted_sizes, ccdf, s=4, alpha=0.5, color="#4C72B0", edgecolors="none")
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("Uncompressed size (bytes)")
    ax2.set_ylabel("P(X >= x)")
    ax2.set_title("Complementary CDF (survival function)")
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(_human_label))
    ax2.grid(True, which="both", alpha=0.3, linestyle="--")

    # Fit a power law via linear regression on log-log CCDF (above median to avoid small-size noise)
    median_size = np.median(sizes_arr)
    mask = sorted_sizes >= median_size
    if mask.sum() > 10:
        log_x = np.log10(sorted_sizes[mask])
        log_y = np.log10(ccdf[mask])
        coeffs = np.polyfit(log_x, log_y, 1)
        alpha = -coeffs[0]  # power-law exponent
        fit_x = np.logspace(np.log10(median_size), np.log10(sorted_sizes[0]), 100)
        fit_y = 10 ** np.polyval(coeffs, np.log10(fit_x))
        ax2.plot(fit_x, fit_y, "r--", linewidth=1.5, label=f"power-law fit (alpha={alpha:.2f})")
        ax2.legend(fontsize=9)
        print(f"Power-law exponent (alpha) from CCDF fit: {alpha:.2f}")

    plt.tight_layout()
    out_path = OUT_DIR / "skill_size_distribution.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")

    # --- 2) Also plot compressed size and largest file for comparison ---
    compressed: list[int] = []
    largest: list[int] = []
    with CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            compressed.append(int(row["compressed_bytes"]))
            largest.append(int(row["largest_file_bytes"]))

    fig2, axes2 = plt.subplots(1, 3, figsize=(18, 5))
    for ax, data, title in [
        (axes2[0], sizes, "Uncompressed size"),
        (axes2[1], compressed, "Compressed size"),
        (axes2[2], largest, "Largest single file"),
    ]:
        arr = np.array(data, dtype=float)
        lo, hi = max(arr.min(), 1), arr.max()
        bins = np.logspace(np.log10(lo), np.log10(hi), 35)
        ax.hist(arr, bins=bins, edgecolor="white", linewidth=0.5, color="#4C72B0", alpha=0.85)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Size (bytes)")
        ax.set_ylabel("Count")
        ax.set_title(title)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(_human_label))
        ax.grid(True, which="both", alpha=0.3, linestyle="--")

    plt.suptitle(f"Log-log histograms (n={n})", y=1.02, fontsize=13)
    plt.tight_layout()
    out_path2 = OUT_DIR / "skill_size_histograms.png"
    fig2.savefig(out_path2, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"Saved {out_path2}")


if __name__ == "__main__":
    main()
