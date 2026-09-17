"""Run SCIP jobs in background threads. Keep latest 5 finished jobs plus in-flight ones."""
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
HISTORY_FILE = JOBS_DIR / "history.json"
SERIES_FILES = {
    "load_csv": "load.csv",
    "pv_csv": "pv.csv",
    "wt_csv": "wt.csv",
}
MAX_RUNNING = 3
HISTORY_KEEP = 5

_COND = threading.Condition()
_pending = []
_running_ids = set()
_HISTORY_LOCK = threading.Lock()
_THREADS = {}


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


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_history(items):
    _atomic_write(HISTORY_FILE, items)


def _trim(items):
    active = [x for x in items if x.get("status") in ("queued", "running") and x.get("id")]
    finished = [x for x in items if x.get("status") not in ("queued", "running") and x.get("id")]
    finished.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    keep_finished = finished[:HISTORY_KEEP]
    drop = finished[HISTORY_KEEP:]
    jobs_dir = JOBS_DIR.resolve()
    for rec in drop:
        folder = Path(rec.get("dir") or JOBS_DIR / rec["id"])
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder.is_dir() and folder.parent == jobs_dir:
            for child in folder.glob("*"):
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                folder.rmdir()
            except OSError:
                pass
    keep_ids = {x["id"] for x in active + keep_finished}
    return [x for x in items if x.get("id") in keep_ids]


def _upsert_history(record):
    with _HISTORY_LOCK:
        items = _read_history()
        found = False
        for i, rec in enumerate(items):
            if rec.get("id") == record["id"]:
                items[i] = {**rec, **record}
                found = True
                break
        if not found:
            items.insert(0, record)
        items = _trim(items)
        _write_history(items)
        return items


def _write_status(out_dir, payload):
    _atomic_write(out_dir / "status.json", payload)


def _summary_from_result(out_dir):
    path = Path(out_dir) / "optimization_results.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not data.get("ok"):
        return data.get("message") or data.get("status") or "未成功"
    cap = data.get("capacities") or {}
    obj = data.get("objective_wan_per_year")
    cost = (data.get("cost") or {}).get("unit_cost_yuan_per_kwh")
    parts = []
    if obj is not None:
        parts.append(f"年化 {obj:.0f} 万元")
    if cost is not None:
        parts.append(f"{cost:.3f} 元/kWh")
    wt = cap.get("x_WT_MW")
    pv = cap.get("x_PV_MW")
    if wt is not None and pv is not None:
        parts.append(f"风 {wt:.0f}/光 {pv:.0f} MW")
    return "，".join(parts)


def job_label(rec):
    status = rec.get("status") or "unknown"
    names = {
        "queued": "排队中",
        "running": "计算中",
        "done": "已完成",
        "failed": "失败",
        "infeasible": "不可行",
    }
    created = rec.get("created_at") or ""
    if len(created) >= 16:
        clock = created[5:16].replace("T", " ")
    else:
        clock = str(rec.get("id") or "")[:15]
    title = names.get(status, status)
    extra = rec.get("summary") or ""
    if extra:
        return f"{clock}　{title}　{extra}"
    return f"{clock}　{title}"


def list_history():
    with _HISTORY_LOCK:
        items = _read_history()
    out = []
    for rec in items:
        folder = Path(rec.get("dir") or "")
        status_path = folder / "status.json" if folder else None
        if status_path and status_path.exists():
            try:
                rec = {**rec, **json.loads(status_path.read_text(encoding="utf-8"))}
            except (OSError, json.JSONDecodeError):
                pass
        if rec.get("status") == "done" and not rec.get("summary"):
            rec["summary"] = _summary_from_result(folder)
        out.append(rec)
    active = [x for x in out if x.get("status") in ("running", "queued")]
    finished = [x for x in out if x.get("status") not in ("running", "queued")]
    active.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    finished.sort(key=lambda x: x.get("created_at") or x.get("finished_at") or "", reverse=True)
    return active + finished


def read_log(out_dir, tail=12000):
    path = Path(out_dir) / "run.log"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-tail:]


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


def get_job(job_id):
    for rec in list_history():
        if rec.get("id") == job_id:
            return rec
    return None


def _run_job_thread(job_id, out_dir):
    token = job_id
    log_path = out_dir / "run.log"
    try:
        _wait_for_slot(token)
        rec = {
            "id": job_id,
            "dir": str(out_dir),
            "status": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write_status(out_dir, rec)
        _upsert_history(rec)
        cmd = [
            sys.executable,
            "-u",
            str(ROOT / "green_power_opt.py"),
            "--config",
            str(out_dir / "job.json"),
            "--out",
            str(out_dir),
        ]
        with log_path.open("a", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                logf.write(line)
                logf.flush()
            rc = proc.wait()
        payload = load_result(out_dir)["json"] or {}
        if rc != 0:
            status = "failed"
            summary = f"退出码 {rc}"
        elif payload.get("status") == "infeasible" or (
            payload.get("ok") is False and "不可行" in str(payload.get("message") or "")
        ):
            status = "infeasible"
            summary = payload.get("message") or "模型不可行"
        elif payload.get("ok"):
            status = "done"
            summary = _summary_from_result(out_dir)
        else:
            status = "failed"
            summary = payload.get("message") or payload.get("status") or "未写出结果"
        rec = {
            "id": job_id,
            "dir": str(out_dir),
            "status": status,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "returncode": rc,
            "summary": summary,
        }
        _write_status(out_dir, rec)
        _upsert_history(rec)
    except Exception as exc:
        rec = {
            "id": job_id,
            "dir": str(out_dir),
            "status": "failed",
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "summary": str(exc),
        }
        try:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"\n[error] {exc}\n")
        except OSError:
            pass
        _write_status(out_dir, rec)
        _upsert_history(rec)
    finally:
        _release_slot(token)


def start_job(config, series_bytes=None):
    """Create a job directory and run SCIP in a background thread. Returns job_id."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out_dir = JOBS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = _materialize_series(out_dir, config, series_bytes=series_bytes)
    (out_dir / "job.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    rec = {
        "id": job_id,
        "dir": str(out_dir),
        "status": "queued",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": f"设计峰值 {float(cfg.get('L') or 0):.0f} MW",
    }
    _write_status(out_dir, rec)
    _upsert_history(rec)
    thread = threading.Thread(target=_run_job_thread, args=(job_id, out_dir), daemon=True, name=f"solve-{job_id}")
    _THREADS[job_id] = thread
    thread.start()
    return job_id, out_dir


def _recover_orphans():
    with _HISTORY_LOCK:
        items = _read_history()
        changed = False
        for rec in items:
            if rec.get("status") not in ("queued", "running"):
                continue
            rec["status"] = "failed"
            rec["summary"] = "上次服务中断，任务未完成"
            rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            changed = True
            folder = Path(rec.get("dir") or "")
            if folder:
                try:
                    _write_status(folder, rec)
                except OSError:
                    pass
        if changed:
            _write_history(_trim(items))


_recover_orphans()


def run_job(config, log_callback=None, series_bytes=None, wait_callback=None):
    """Backward-compatible blocking helper."""
    job_id, out_dir = start_job(config, series_bytes=series_bytes)
    while True:
        rec = get_job(job_id) or {}
        status = rec.get("status")
        if wait_callback is not None and status == "queued":
            q = queue_status()
            wait_callback(max(q["waiting"] - 1, 0), q["running"], q["waiting"])
        if log_callback is not None:
            log_callback(read_log(out_dir))
        if status not in ("queued", "running"):
            break
        time.sleep(0.5)
    rec = get_job(job_id) or {}
    rc = int(rec.get("returncode") or (0 if rec.get("status") == "done" else 1))
    return job_id, out_dir, rc, read_log(out_dir)
