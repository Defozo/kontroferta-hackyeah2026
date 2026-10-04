"""Repeatable exact-engine boundary benchmark; no model calls or source uploads."""
import argparse
import cProfile
import json
import platform
import pstats
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from statistics import median
from time import perf_counter, process_time

from packages.domain import demo_model, evaluate


def boundary_model():
    model = demo_model()
    model["variables"][0]["values"] = list(range(100000))
    model["variables"][0]["source"] = "Synthetic finite benchmark domain, 100000 integer minor-unit amounts."
    model["max_scenarios"] = 100000
    return model


def run(repetitions=3, profile=False, output=None):
    model = boundary_model()
    cold_started = perf_counter()
    initial = evaluate(model)
    cold_ms = (perf_counter()-cold_started)*1000
    assert initial["complete"] and initial["checked_count"] == 100000
    samples, cpu_samples = [], []
    for _ in range(repetitions):
        started = perf_counter()
        cpu_started = process_time()
        result = evaluate(model)
        samples.append((perf_counter()-started)*1000)
        cpu_samples.append((process_time()-cpu_started)*1000)
        assert result["complete"] and result["checked_count"] == 100000
        assert result["robust_feasible"] == ["B"] and result["status"] == "needs_clarification"
    output = Path(output or ".runtime/engine-benchmark")
    output.mkdir(parents=True, exist_ok=True)
    report = {"measured_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor(),
              "scenario_count": 100000, "model": "Fictional AV model with 100000 enumerated integer surcharges",
              "cold_first_calculation_ms": cold_ms, "acceleration": initial.get("acceleration"),
              "sample_size": len(samples), "samples_ms": samples, "process_cpu_samples_ms": cpu_samples,
              "median_ms": median(samples), "observed_p95_nearest_rank_ms": sorted(samples)[ceil(len(samples)*.95)-1],
              "target_500_ms_observed": sorted(samples)[ceil(len(samples)*.95)-1] <= 500,
              "limitations": ["Small repeated sample is not a production percentile estimate.", "Shared workstation, without isolation from other workloads.", "Timing covers model validation, exact enumeration, question ranking and result construction; not HTTP, persistence or browser rendering."]}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    if profile:
        profiler = cProfile.Profile()
        profiler.runcall(evaluate, model)
        with (output / "profile.txt").open("w", encoding="utf-8") as handle:
            pstats.Stats(profiler, stream=handle).strip_dirs().sort_stats("cumtime").print_stats(35)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    run(args.repetitions, args.profile, args.output)
