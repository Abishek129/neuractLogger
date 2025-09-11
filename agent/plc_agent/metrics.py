from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple, Any


def _utc_now_iso() -> str:
    # Return IST (UTC+05:30) ISO string for UI/reporting consistency
    import datetime as _dt
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    return _dt.datetime.now(ist).replace(microsecond=0).isoformat()


@dataclass
class _SecSample:
    ts: float
    reads: int = 0
    read_err: int = 0
    writes: int = 0
    write_err: int = 0
    triggers: int = 0
    fires: int = 0
    suppressed: int = 0


@dataclass
class JobMetrics:
    job_id: str
    # per-second samples window (store ~5 minutes @ 1s)
    per_sec: Deque[_SecSample] = field(default_factory=lambda: deque(maxlen=300))
    # rolling latencies (ms)
    read_lat_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=1800))
    write_lat_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=1800))
    # error map: code -> (count, last_message, last_ts)
    errors: Dict[str, Tuple[int, str, float]] = field(default_factory=dict)
    # mapping of table_id -> target_id for writes (last seen)
    targets: Dict[str, Optional[str]] = field(default_factory=dict)
    # run state
    active_run: Optional[Dict[str, Any]] = None
    mtx: threading.RLock = field(default_factory=threading.RLock)

    def _ensure_current_second(self) -> _SecSample:
        now = time.time()
        with self.mtx:
            if self.per_sec and int(self.per_sec[-1].ts) == int(now):
                return self.per_sec[-1]
            s = _SecSample(ts=now)
            self.per_sec.append(s)
            return s

    def start_run(self) -> None:
        with self.mtx:
            if self.active_run is None:
                self.active_run = {
                    "started_at": _utc_now_iso(),
                    "rows": 0,
                    "read_lat_sum": 0.0,
                    "read_lat_n": 0,
                    "write_lat_sum": 0.0,
                    "write_lat_n": 0,
                    "errors": 0,
                }

    def end_run(self) -> Optional[Dict[str, Any]]:
        with self.mtx:
            if not self.active_run:
                return None
            run = dict(self.active_run)
            run["stopped_at"] = _utc_now_iso()
            # compute duration
            run["duration_ms"] = None
            try:
                import datetime as _dt
                a = _dt.datetime.fromisoformat(run["started_at"].replace("Z", ""))
                b = _dt.datetime.fromisoformat(run["stopped_at"].replace("Z", ""))
                run["duration_ms"] = int((b - a).total_seconds() * 1000)
            except Exception:
                pass
            # compute avgs
            r_n = max(1, int(run.get("read_lat_n") or 0))
            w_n = max(1, int(run.get("write_lat_n") or 0))
            run["read_lat_avg"] = float(run.get("read_lat_sum") or 0.0) / r_n
            run["write_lat_avg"] = float(run.get("write_lat_sum") or 0.0) / w_n
            # error % is out of total (errors / max(1, rows))
            rows = max(1, int(run.get("rows") or 0))
            run["error_pct"] = (float(run.get("errors") or 0) / float(rows)) * 100.0
            self.active_run = None
            return run

    def record_read(self, latency_ms: float, *, ok: bool) -> None:
        s = self._ensure_current_second()
        with self.mtx:
            if ok:
                s.reads += 1
            else:
                s.read_err += 1
            self.read_lat_ms.append(latency_ms)
            if self.active_run is not None:
                self.active_run["read_lat_sum"] += float(latency_ms)
                self.active_run["read_lat_n"] += 1
                if not ok:
                    self.active_run["errors"] += 1

    def record_write(self, latency_ms: float, *, ok: bool, rows: int, table_id: Optional[str], target_id: Optional[str]) -> None:
        s = self._ensure_current_second()
        with self.mtx:
            if ok:
                s.writes += int(rows)
            else:
                s.write_err += 1
            self.write_lat_ms.append(latency_ms)
            if table_id is not None:
                self.targets[table_id] = target_id
            if self.active_run is not None:
                self.active_run["rows"] += int(rows)
                self.active_run["write_lat_sum"] += float(latency_ms)
                self.active_run["write_lat_n"] += 1
                if not ok:
                    self.active_run["errors"] += 1

    def record_trigger_eval(self, fired: bool, suppressed: bool = False) -> None:
        s = self._ensure_current_second()
        with self.mtx:
            s.triggers += 1
            if fired:
                s.fires += 1
            if suppressed:
                s.suppressed += 1

    def record_error(self, code: str, message: str) -> None:
        with self.mtx:
            count, _, _ = self.errors.get(code, (0, "", 0.0))
            self.errors[code] = (count + 1, str(message)[:512], time.time())

    def summary_last_secs(self, window: int = 60) -> Dict[str, Any]:
        now = time.time()
        reads = read_err = writes = write_err = trg = fire = sup = 0
        with self.mtx:
            for s in self.per_sec:
                if now - s.ts <= window:
                    reads += s.reads
                    read_err += s.read_err
                    writes += s.writes
                    write_err += s.write_err
                    trg += s.triggers
                    fire += s.fires
                    sup += s.suppressed
            def _q(vals: Deque[float], p: float) -> Optional[float]:
                arr = [v for v in vals][-min(len(vals), 600):]
                if not arr:
                    return None
                arr.sort()
                k = max(0, min(len(arr) - 1, int(p * (len(arr) - 1))))
                return float(arr[k])
            p50r = _q(self.read_lat_ms, 0.50)
            p95r = _q(self.read_lat_ms, 0.95)
            p50w = _q(self.write_lat_ms, 0.50)
            p95w = _q(self.write_lat_ms, 0.95)
        err_pct = (read_err + write_err) / max(1, (reads + writes)) * 100.0
        return {
            "reads": reads,
            "readErrors": read_err,
            "writes": writes,
            "writeErrors": write_err,
            "triggers": trg,
            "fires": fire,
            "suppressed": sup,
            "readP50": p50r,
            "readP95": p95r,
            "writeP50": p50w,
            "writeP95": p95w,
            "errorPct": err_pct,
        }

    def timeseries(self, since_secs: int = 900) -> List[Dict[str, Any]]:
        now = time.time()
        out: List[Dict[str, Any]] = []
        with self.mtx:
            for s in list(self.per_sec):
                if now - s.ts <= since_secs:
                    out.append({
                        "ts": int(s.ts),
                        "reads": s.reads,
                        "readErrors": s.read_err,
                        "writes": s.writes,
                        "writeErrors": s.write_err,
                        "triggers": s.triggers,
                        "fires": s.fires,
                        "suppressed": s.suppressed,
                    })
        return out


class SystemMetrics:
    def __init__(self) -> None:
        self.mtx = threading.RLock()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.per_sec: Deque[Dict[str, Any]] = deque(maxlen=600)  # ~10min
        self._last_disk: Optional[Tuple[int, int]] = None
        self._last_net: Optional[Tuple[int, int]] = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="metrics-system", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        t = self.thread
        if t:
            t.join(timeout=1.0)

    def _loop(self) -> None:
        try:
            import psutil  # type: ignore
        except Exception:
            # Fallback: no psutil, do nothing but keep API alive
            while self.running:
                with self.mtx:
                    self.per_sec.append({
                        "ts": int(time.time()),
                        "cpu": None,
                        "mem": None,
                        "disk_rps": None,
                        "disk_wps": None,
                        "net_rxps": None,
                        "net_txps": None,
                        "proc_cpu": None,
                        "proc_rss_mb": None,
                        "proc_handles": None,
                    })
                time.sleep(1.0)
            return
        proc = psutil.Process()
        # prime counters
        try:
            d0 = psutil.disk_io_counters()
            n0 = psutil.net_io_counters()
            self._last_disk = (int(getattr(d0, "read_bytes", 0)), int(getattr(d0, "write_bytes", 0)))
            self._last_net = (int(getattr(n0, "bytes_recv", 0)), int(getattr(n0, "bytes_sent", 0)))
        except Exception:
            self._last_disk = None
            self._last_net = None
        while self.running:
            ts = int(time.time())
            try:
                cpu = float(psutil.cpu_percent(interval=None))
                mem = float(psutil.virtual_memory().percent)
                d = psutil.disk_io_counters()
                n = psutil.net_io_counters()
                rps = wps = rxps = txps = None
                if self._last_disk is not None:
                    dr = max(0, int(getattr(d, "read_bytes", 0)) - self._last_disk[0])
                    dw = max(0, int(getattr(d, "write_bytes", 0)) - self._last_disk[1])
                    rps, wps = dr, dw
                self._last_disk = (int(getattr(d, "read_bytes", 0)), int(getattr(d, "write_bytes", 0)))
                if self._last_net is not None:
                    rx = max(0, int(getattr(n, "bytes_recv", 0)) - self._last_net[0])
                    tx = max(0, int(getattr(n, "bytes_sent", 0)) - self._last_net[1])
                    rxps, txps = rx, tx
                self._last_net = (int(getattr(n, "bytes_recv", 0)), int(getattr(n, "bytes_sent", 0)))
                with self.mtx:
                    try:
                        rss = float(proc.memory_info().rss) / (1024 * 1024)
                    except Exception:
                        rss = None
                    try:
                        pcpu = float(proc.cpu_percent(interval=None))
                    except Exception:
                        pcpu = None
                    try:
                        handles = proc.num_handles() if hasattr(proc, "num_handles") else proc.num_fds() if hasattr(proc, "num_fds") else None
                    except Exception:
                        handles = None
                    self.per_sec.append({
                        "ts": ts,
                        "cpu": cpu,
                        "mem": mem,
                        "disk_rps": rps,
                        "disk_wps": wps,
                        "net_rxps": rxps,
                        "net_txps": txps,
                        "proc_cpu": pcpu,
                        "proc_rss_mb": rss,
                        "proc_handles": handles,
                    })
            except Exception:
                # keep going
                pass
            time.sleep(1.0)

    def snapshot(self, window_secs: int = 300) -> Dict[str, Any]:
        now = time.time()
        with self.mtx:
            arr = [s for s in self.per_sec if now - s.get("ts", 0) <= window_secs]
        return {
            "items": arr,
            "now": int(now),
        }


class MetricsRegistry:
    def __init__(self) -> None:
        self.system = SystemMetrics()
        self.jobs: Dict[str, JobMetrics] = {}
        self.mtx = threading.RLock()
        # background rollup thread placeholder (future)

    def get_job(self, job_id: str) -> JobMetrics:
        with self.mtx:
            jm = self.jobs.get(job_id)
            if jm is None:
                jm = JobMetrics(job_id=job_id)
                self.jobs[job_id] = jm
            return jm

    def jobs_summary(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        with self.mtx:
            for jid, jm in self.jobs.items():
                out[jid] = jm.summary_last_secs(60)
        return out


# Global metrics singleton
metrics = MetricsRegistry()
