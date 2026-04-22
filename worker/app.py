import os
import time
import math
import threading
from concurrent.futures import ProcessPoolExecutor
from flask import Flask, jsonify
from datetime import datetime

app = Flask(__name__)

POD_NAME = os.environ.get("POD_NAME", "unknown")
HAS_LIMIT = os.environ.get("HAS_CPU_LIMIT", "false")

def get_cpu_limit_str():
    # cgroup v2
    try:
        with open('/sys/fs/cgroup/cpu.max') as f:
            quota_str, period_str = f.read().strip().split()
        if quota_str == 'max':
            return None
        millis = round(int(quota_str) / int(period_str) * 1000)
        return f"{millis}m"
    except Exception:
        pass
    # cgroup v1
    try:
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
            quota = int(f.read().strip())
        if quota == -1:
            return None
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
            period = int(f.read().strip())
        millis = round(quota / period * 1000)
        return f"{millis}m"
    except Exception:
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
    """Count primes up to limit - pure CPU intensive work"""
    count = 0
    for n in range(2, limit + 1):
        if is_prime(n):
            count += 1
    return count

def fibonacci(n):
    """Recursive fibonacci - exponential CPU work"""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

def _count_primes_chunk(args):
    start, end = args
    count = 0
    for n in range(max(2, start), end + 1):
        if is_prime(n):
            count += 1
    return count

def matrix_multiply(size):
    """Matrix multiplication"""
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
    total_start = time.perf_counter()

    # Primes
    start = time.perf_counter()
    prime_count = count_primes(50000)
    results["primes"] = {
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "description": "Count primes up to 50,000"
    }

    # Fibonacci
    start = time.perf_counter()
    fib = fibonacci(36)
    results["fibonacci"] = {
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "description": "Recursive fibonacci(36)"
    }

    # Matrix
    start = time.perf_counter()
    matrix_multiply(200)
    results["matrix"] = {
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "description": "200x200 matrix multiplication"
    }

    total_elapsed = time.perf_counter() - total_start

    return jsonify({
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "cpu_limit": get_cpu_limit_str(),
        "total_elapsed_ms": round(total_elapsed * 1000, 2),
        "benchmarks": results,
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/bench/threads")
def bench_threads():
    limit = 500000
    workers = 4

    start = time.perf_counter()
    count_primes(limit)
    single_ms = round((time.perf_counter() - start) * 1000, 2)

    chunk = limit // workers
    ranges = [(i * chunk, (i + 1) * chunk - 1 if i < workers - 1 else limit)
              for i in range(workers)]
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        list(executor.map(_count_primes_chunk, ranges))
    multi_ms = round((time.perf_counter() - start) * 1000, 2)

    return jsonify({
        "task": "thread_compare",
        "limit": limit,
        "workers": workers,
        "single_ms": single_ms,
        "multi_ms": multi_ms,
        "speedup": round(single_ms / multi_ms, 2) if multi_ms > 0 else 0,
        "pod_name": POD_NAME,
        "has_cpu_limit": HAS_LIMIT,
        "cpu_limit": get_cpu_limit_str(),
        "timestamp": datetime.utcnow().isoformat()
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
