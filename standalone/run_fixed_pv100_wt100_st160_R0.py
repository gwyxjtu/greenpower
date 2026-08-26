"""Backward-compatible entry: 100/100/160 plant, R=0, one solve (μ from params.py)."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from standalone.run import main

if __name__ == "__main__":
    main(["solve", "--preset", "pv100_wt100_st160", "--r0", *sys.argv[1:]])
