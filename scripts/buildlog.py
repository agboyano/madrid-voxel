"""Build log shared by the fusion steps: notes printed and kept for data/debug/report.json, and the output folders."""
from pathlib import Path

OUT = Path("web/public/data")
DBG = Path("data/debug")
OUT.mkdir(parents=True, exist_ok=True)
DBG.mkdir(parents=True, exist_ok=True)
report = {"notes": []}


def note(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    report["notes"].append(s)
