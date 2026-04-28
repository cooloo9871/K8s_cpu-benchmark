import os
# 限制 BLAS 內部執行緒為 1，避免與 ThreadPoolExecutor 競爭
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('BLIS_NUM_THREADS', '1')
import time
import math
import threading
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, jsonify
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

POD_NAME = os.environ.get("POD_NAME", "unknown")
HAS_LIMIT = os.environ.get("HAS_CPU_LIMIT", "false")

def get_cpu_limit_str():
    # cgroup v2 CFS quota
    try:
        with open('/sys/fs/cgroup/cpu.max') as f:
            quota_str, period_str = f.read().strip().split()
        if quota_str != 'max':
            millis = round(int(quota_str) / int(period_str) * 1000)
            return f"{millis}m"
    except Exception:
        pass
    # cgroup v1 CFS quota
    try:
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
            quota = int(f.read().strip())
        if quota != -1:
            with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
                period = int(f.read().strip())
            millis = round(quota / period * 1000)
            return f"{millis}m"
    except Exception:
        pass
    # K8s static CPU Manager: exclusive cpuset replaces CFS quota.
    # cpu.max = "max", but sched_getaffinity returns only the pinned cores.
    try:
        allowed = sorted(os.sched_getaffinity(0))
        if len(allowed) < (os.cpu_count() or 1):
            return "cpuset:" + ",".join(str(c) for c in allowed)
    except (AttributeError, OSError):
        pass
    return None

def is_prime(n):
    if n < 2:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(math.sqrt(n)) + 1, 2):
        if n % i == 0:
            return False
    return True

def count_primes(limit):
    count = 0
    for n in range(2, limit + 1):
        if is_prime(n):
            count += 1
    return count

def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

def _numpy_matrix_work(_):
    """numpy 矩陣乘法 — 在 C 層執行，會釋放 GIL，可真正多執行緒並行"""
    a = np.random.rand(500, 500)
    b = np.random.rand(500, 500)
    return np.dot(a, b)

def matrix_multiply(size):
    a = [[float(i * size + j) for j in range(size)] for i in range(size)]
    b = [[float(i + j) for j in range(size)] for i in range(size)]
    result = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            for k in range(size):
                result[i][j] += a[i][k] * b[k][j]
    return result[0][0]

@app.route("/health")
def health():
    return jsonify({"status": "ok", "pod": POD_NAME})

@app.route("/info")
def info():
    return jsonify({
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "cpu_limit": get_cpu_limit_str(),
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/primes")
def bench_primes():
    limit = 50000
    start = time.perf_counter()
    result = count_primes(limit)
    elapsed = time.perf_counter() - start
    return jsonify({
        "task": "prime_count",
        "limit": limit,
        "result": result,
        "elapsed_ms": round(elapsed * 1000, 2),
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/fibonacci")
def bench_fibonacci():
    n = 36
    start = time.perf_counter()
    result = fibonacci(n)
    elapsed = time.perf_counter() - start
    return jsonify({
        "task": "fibonacci",
        "n": n,
        "result": result,
        "elapsed_ms": round(elapsed * 1000, 2),
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/matrix")
def bench_matrix():
    size = 200
    start = time.perf_counter()
    result = matrix_multiply(size)
    elapsed = time.perf_counter() - start
    return jsonify({
        "task": "matrix_multiply",
        "size": f"{size}x{size}",
        "result": round(result, 2),
        "elapsed_ms": round(elapsed * 1000, 2),
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/all")
def bench_all():
    results = {}

    start = time.perf_counter()
    fibonacci(36)
    fib_ms = round((time.perf_counter() - start) * 1000, 2)
    results["fibonacci"] = {
        "elapsed_ms": fib_ms,
        "description": "Recursive fibonacci(36)"
    }

    return jsonify({
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "cpu_limit": get_cpu_limit_str(),
        "total_elapsed_ms": fib_ms,
        "benchmarks": results,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/threads")
def bench_threads():
    workers = 4
    tasks = workers * 2  # 共 8 次矩陣乘法，分配給 1 或 4 條執行緒

    start = time.perf_counter()
    for i in range(tasks):
        _numpy_matrix_work(i)
    single_ms = round((time.perf_counter() - start) * 1000, 2)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(_numpy_matrix_work, range(tasks)))
    multi_ms = round((time.perf_counter() - start) * 1000, 2)

    return jsonify({
        "task": "thread_compare",
        "workload": "numpy 500x500 matmul x8",
        "workers": workers,
        "tasks": tasks,
        "single_ms": single_ms,
        "multi_ms": multi_ms,
        "speedup": round(single_ms / multi_ms, 2) if multi_ms > 0 else 0,
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "cpu_limit": get_cpu_limit_str(),
        "timestamp": datetime.utcnow().isoformat()
    })

# ── NUMA helpers ──────────────────────────────────────────────────────────────

def _parse_cpulist(s):
    cpus = []
    for part in s.strip().split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo, hi = part.split('-', 1)
            cpus.extend(range(int(lo), int(hi) + 1))
        else:
            cpus.append(int(part))
    return cpus

def get_numa_cpu_map():
    """Returns {node_id: [cpu_ids]} from /sys/devices/system/node/."""
    result = {}
    base = Path('/sys/devices/system/node')
    if not base.exists():
        return result
    for d in sorted(base.glob('node[0-9]*')):
        nid = int(d.name[4:])
        f = d / 'cpulist'
        if f.exists():
            text = f.read_text().strip()
            if text:
                result[nid] = _parse_cpulist(text)
    return result

def _get_thread_cpu():
    """Return the CPU core the calling thread is currently running on.
    Reads /proc/self/task/<tid>/stat field 39 (1-indexed) = processor.
    Returns -1 if unavailable."""
    try:
        tid = threading.get_native_id()
        with open(f'/proc/self/task/{tid}/stat') as f:
            raw = f.read()
        # Strip "pid (comm)" — comm can contain spaces, use rfind(')') to be safe.
        # Remaining fields start at field 3 (state), so:
        #   after_comm[0]=state(3), [1]=ppid(4), ..., [35]=exit_signal(38), [36]=processor(39)
        after_comm = raw[raw.rfind(')') + 1:].split()
        return int(after_comm[36])
    except Exception:
        return -1

def _stream_chunk(args):
    """Pin thread to cpuset, sum the chunk (releases GIL), record actual CPU."""
    arr_chunk, cpuset = args
    if cpuset:
        try:
            os.sched_setaffinity(0, cpuset)
        except (OSError, PermissionError, AttributeError):
            pass
    val = float(np.sum(arr_chunk))
    cpu = _get_thread_cpu()
    return val, cpu

@app.route("/bench/numa")
def bench_numa():
    try:
        return _bench_numa_impl()
    except Exception as exc:
        return jsonify({
            "available": False,
            "mode": "error",
            "error": str(exc),
            "pod_name": POD_NAME,
            "has_cpu_limit": HAS_LIMIT,
            "cpu_limit": get_cpu_limit_str(),
            "timestamp": datetime.utcnow().isoformat()
        })

def _bench_numa_impl():
    numa_map = get_numa_cpu_map()
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = list(range(os.cpu_count() or 1))
    allowed_set = set(allowed)

    # NUMA nodes that have at least 1 allowed CPU in this container
    node_cpus = {}
    for nid, cpus in numa_map.items():
        avail = [c for c in cpus if c in allowed_set]
        if avail:
            node_cpus[nid] = avail

    array_mb = 128
    n = (array_mb * 1024 * 1024) // 8  # number of float64 elements

    def run_pass(executor, chunks, cpu_list):
        """One timed pass: pin each thread to its CPU, stream-read its chunk.
        Returns (elapsed_ms, sorted list of actual CPUs observed)."""
        task_args = [
            (chunks[i], {cpu_list[i % len(cpu_list)]})
            for i in range(len(chunks))
        ]
        t = time.perf_counter()
        results = list(executor.map(_stream_chunk, task_args))
        elapsed_ms = (time.perf_counter() - t) * 1000
        actual_cpus = sorted({r[1] for r in results if r[1] >= 0})
        return elapsed_ms, actual_cpus

    # ── Cross-NUMA mode ───────────────────────────────────────────────────────
    if len(node_cpus) >= 2:
        node_ids = sorted(node_cpus.keys())
        cpus_a   = node_cpus[node_ids[0]]
        cpus_b   = node_cpus[node_ids[1]]
        workers  = min(4, len(cpus_a), len(cpus_b))

        # Pin main thread to Node A so first-touch places pages there
        saved_aff = None
        try:
            saved_aff = os.sched_getaffinity(0)
            os.sched_setaffinity(0, {cpus_a[0]})
        except Exception:
            pass

        arr = np.ones(n, dtype=np.float64)
        float(np.sum(arr))              # first-touch: place pages on Node A DRAM

        # 64 MB eviction buffer (first-touched on main thread → Node A DRAM).
        # Streaming through it populates Node A L3 with new lines, evicting arr.
        # arr[:] = value writes through L3 (write-allocate), so it does NOT flush
        # arr from L3 — the evict_buf stream-read approach is the correct way to
        # ensure both local and remote measurements start from DRAM, not L3.
        evict_n = (64 * 1024 * 1024) // 8
        evict_buf = np.empty(evict_n, dtype=np.float64)
        float(np.sum(evict_buf))        # first-touch evict_buf on Node A

        chunks = np.array_split(arr, workers)

        # Pre-create executor once; exclude thread-pool setup from timing.
        PASSES = 7  # odd; median index = 3
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # Symmetric warm-up: evict arr from L3, then one warm pass per node.
            float(np.sum(evict_buf))
            run_pass(ex, chunks, cpus_a)
            float(np.sum(evict_buf))
            run_pass(ex, chunks, cpus_b)

            # Interleaved timed passes: stream evict_buf before every measurement
            # so arr must be fetched from DRAM each time (not L3).
            local_times, remote_times   = [], []
            local_cpus_seen, remote_cpus_seen = set(), set()
            for _ in range(PASSES):
                float(np.sum(evict_buf))   # flush arr from Node A L3
                t, cpus = run_pass(ex, chunks, cpus_a)
                local_times.append(t)
                local_cpus_seen.update(cpus)

                float(np.sum(evict_buf))   # flush before remote
                t, cpus = run_pass(ex, chunks, cpus_b)
                remote_times.append(t)
                remote_cpus_seen.update(cpus)

            # Median discards outlier passes caused by OS scheduling noise.
            local_ms          = round(sorted(local_times)[PASSES // 2], 2)
            remote_ms         = round(sorted(remote_times)[PASSES // 2], 2)
            actual_local_cpus  = sorted(local_cpus_seen)
            actual_remote_cpus = sorted(remote_cpus_seen)

        # affinity_ok=False means threads ran on overlapping cores →
        # local and remote saw the same memory path → measurement unreliable.
        affinity_ok = not bool(set(actual_local_cpus) & set(actual_remote_cpus))

        if saved_aff:
            try:
                os.sched_setaffinity(0, saved_aff)
            except Exception:
                pass

        bw_local  = round(array_mb / 1024 / (local_ms  / 1000), 2) if local_ms  > 0 else 0
        bw_remote = round(array_mb / 1024 / (remote_ms / 1000), 2) if remote_ms > 0 else 0
        slowdown  = round(remote_ms / local_ms, 2) if local_ms > 0 else 0

        return jsonify({
            "available": True,
            "mode": "cross_numa",
            "array_mb": array_mb,
            "workers": workers,
            "total_numa_nodes": len(numa_map),
            "node_a": node_ids[0],
            "node_b": node_ids[1],
            "node_a_cpus": cpus_a,
            "node_b_cpus": cpus_b,
            "actual_local_cpus": actual_local_cpus,
            "actual_remote_cpus": actual_remote_cpus,
            "affinity_ok": affinity_ok,
            "local_ms": local_ms,
            "remote_ms": remote_ms,
            "slowdown": slowdown,
            "bandwidth_local_gbps": bw_local,
            "bandwidth_remote_gbps": bw_remote,
            "pod_name": POD_NAME,
            "has_cpu_limit": HAS_LIMIT,
            "cpu_limit": get_cpu_limit_str(),
            "timestamp": datetime.utcnow().isoformat()
        })

    # ── Single-NUMA fallback: bandwidth scaling (1 thread vs N threads) ───────
    else:
        workers = max(1, min(4, len(allowed)))
        arr = np.ones(n, dtype=np.float64)
        float(np.sum(arr))              # warm-up / force allocation

        # Single-thread baseline: main thread reads full array
        t = time.perf_counter()
        for _ in range(3):
            float(np.sum(arr))
        single_ms = round((time.perf_counter() - t) / 3 * 1000, 2)

        # Multi-thread: N threads read split chunks; pool kept alive across runs
        chunks     = np.array_split(arr, workers)
        task_args  = [(c, None) for c in chunks]

        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_stream_chunk, task_args))  # warm-up, discard
            t = time.perf_counter()
            for _ in range(3):
                list(ex.map(_stream_chunk, task_args))
            multi_ms = round((time.perf_counter() - t) / 3 * 1000, 2)

        bw_single = round(array_mb / 1024 / (single_ms / 1000), 2) if single_ms > 0 else 0
        bw_multi  = round(array_mb / 1024 / (multi_ms  / 1000), 2) if multi_ms  > 0 else 0

        return jsonify({
            "available": False,
            "mode": "single_numa",
            "reason": "container CPUs only span 1 NUMA node — showing bandwidth scaling instead",
            "total_numa_nodes": len(numa_map),
            "allowed_cpus": allowed,
            "array_mb": array_mb,
            "workers": workers,
            "single_ms": single_ms,
            "multi_ms": multi_ms,
            "bandwidth_single_gbps": bw_single,
            "bandwidth_multi_gbps": bw_multi,
            "pod_name": POD_NAME,
            "has_cpu_limit": HAS_LIMIT,
            "cpu_limit": get_cpu_limit_str(),
            "timestamp": datetime.utcnow().isoformat()
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
