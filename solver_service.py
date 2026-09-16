"""Run SCIP jobs in subprocesses. At most 3 jobs run at once; others wait in a queue."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "out" / "jobs"
SERIES_FILES = {
    "load_csv": "load.csv",
    "pv_csv": "pv.csv",
    "wt_csv": "wt.csv",
}
MAX_RUNNING = 3

_COND = threading.Condition()
_pending = []
_running_ids = set()


class SolverBusyError(RuntimeError):
    pass


def queue_status():
    with _COND:
        return {
            "running": len(_running_ids),
            "waiting": len(_pending),
            "max_running": MAX_RUNNING,
        }


def is_busy():
    status = queue_status()
    return status["running"] >= MAX_RUNNING


def _as_bytes(blob):
    if blob is None:
        return None
    if isinstance(blob, str):
        return blob.encode("utf-8")
    return bytes(blob)


def _materialize_series(out_dir, config, series_bytes=None):
    cfg = dict(config)
    series_bytes = series_bytes or {}
    for key, fname in SERIES_FILES.items():
        blob = _as_bytes(series_bytes.get(key))
        dest = out_dir / fname
        if blob:
            dest.write_bytes(blob)
            cfg[key] = fname
            continue
        src_raw = cfg.get(key)
        if not src_raw:
            continue
        src = Path(src_raw)
        if src.is_file():
            dest.write_bytes(src.read_bytes())
            cfg[key] = fname
    cfg.pop("_base_dir", None)
    return cfg


def _wait_for_slot(token, wait_callback=None):
    with _COND:
        _pending.append(token)
    while True:
        with _COND:
            pos = _pending.index(token)
            if len(_running_ids) < MAX_RUNNING and pos == 0:
                _pending.pop(0)
                _running_ids.add(token)
                _COND.notify_all()
                return
            stats = (pos, len(_running_ids), len(_pending))
            _COND.wait(timeout=0.5)
        if wait_callback is not None:
            wait_callback(*stats)


def _release_slot(token):
    with _COND:
        if token in _pending:
            _pending.remove(token)
        _running_ids.discard(token)
        _COND.notify_all()


def run_job(config, log_callback=None, series_bytes=None, wait_callback=None):
    """
    Queue a job, wait for a free slot (max 3 running), then solve.
    Returns (job_id, out_dir, returncode, log_text).
    """
    token = uuid.uuid4().hex
    try:
        _wait_for_slot(token, wait_callback=wait_callback)
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        out_dir = JOBS_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg = _materialize_series(out_dir, config, series_bytes=series_bytes)
        cfg_path = out_dir / "job.json"
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
            "-u",
            str(ROOT / "green_power_opt.py"),
            "--config",
            str(cfg_path),
            "--out",
            str(out_dir),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines = []
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if log_callback is not None:
                log_callback("".join(lines))
        rc = proc.wait()
        return job_id, out_dir, rc, "".join(lines)
    finally:
        _release_slot(token)


def load_result(out_dir):
    out_dir = Path(out_dir)
    json_path = out_dir / "optimization_results.json"
    csv_path = out_dir / "timeseries_results.csv"
    txt_path = out_dir / "optimization_results.txt"
    lp_path = out_dir / "model.lp"
    payload = None
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "json": payload,
        "json_path": json_path if json_path.exists() else None,
        "csv_path": csv_path if csv_path.exists() else None,
        "txt_path": txt_path if txt_path.exists() else None,
        "lp_path": lp_path if lp_path.exists() else None,
    }
