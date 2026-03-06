"""Benchmark the /v1/ask endpoint. Runs N queries and reports timing + responses."""

import json
import sys
import time

import httpx

QUERIES = [
    "video editing tools",
    "help me build a Bayesian model",
    "chocolate cake recipe",  # off-topic — should be fast
    "data validation library for python",
    "create presentation slides",
]

NUM_RUNS = 2  # runs per query


def run_benchmark(base_url: str) -> list[dict]:
    results = []
    client = httpx.Client(timeout=90)
    for query in QUERIES:
        for run in range(NUM_RUNS):
            t0 = time.monotonic()
            resp = client.get(f"{base_url}/v1/ask", params={"q": query})
            elapsed = time.monotonic() - t0
            data = resp.json() if resp.status_code == 200 else {}
            results.append(
                {
                    "query": query,
                    "run": run + 1,
                    "status": resp.status_code,
                    "time_s": round(elapsed, 2),
                    "answer_len": len(data.get("answer", "")),
                    "num_skills": len(data.get("skills", [])),
                    "answer_preview": data.get("answer", "")[:120],
                }
            )
            print(
                f"  {query!r} run={run + 1} → {elapsed:.2f}s  skills={len(data.get('skills', []))}  status={resp.status_code}"
            )
    client.close()
    return results


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "https://hub-dev.decision.ai"
    label = sys.argv[2] if len(sys.argv) > 2 else "benchmark"

    print(f"\n=== Benchmark: {label} ({base_url}) ===\n")
    results = run_benchmark(base_url)

    # Summary
    times = [r["time_s"] for r in results]
    on_topic = [r["time_s"] for r in results if r["query"] != "chocolate cake recipe"]
    off_topic = [r["time_s"] for r in results if r["query"] == "chocolate cake recipe"]

    print(f"\n--- Summary ({label}) ---")
    print(f"  Total queries:    {len(results)}")
    print(f"  Mean (all):       {sum(times) / len(times):.2f}s")
    print(f"  Mean (on-topic):  {sum(on_topic) / len(on_topic):.2f}s")
    print(f"  Mean (off-topic): {sum(off_topic) / len(off_topic):.2f}s")
    print(f"  Min:              {min(times):.2f}s")
    print(f"  Max:              {max(times):.2f}s")

    outfile = f"benchmark_{label}.json"
    with open(outfile, "w") as f:
        json.dump({"label": label, "base_url": base_url, "results": results}, f, indent=2)
    print(f"\n  Results saved to {outfile}\n")


if __name__ == "__main__":
    main()
