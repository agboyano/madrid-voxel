"""Run a pipeline script and report its wall time and peak memory (children included), for build_data.sh.

usage: PYTHONPATH=scripts uv run python scripts/measure.py scripts/<step>.py
"""
import resource, runpy, sys, time
t0 = time.time()
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    peak = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    print(f"MEASURE {sys.argv[0]}: {time.time() - t0:.0f} s, peak RSS {peak / 1e6:.2f} GB", file=sys.stderr)
