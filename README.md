# K8s CPU Benchmark

透過四種壓測工具，即時對比 **CPU Limited（100m）vs CPU Unlimited** 兩個 Pod 在 Kubernetes 中的執行差異，涵蓋 CPU 節流、多執行緒擴展性、NUMA 記憶體拓撲效能，以及搭配 Prometheus 觀察 CFS throttle 比率。

---

## 專案結構

```
K8s_cpu-benchmark/
├── worker/
│   ├── app.py          # Flask 壓測 API（port 8080）
│   └── Dockerfile      # python:3.11-slim + libnuma1
├── dashboard/
│   ├── server.py       # Python HTTP server（port 3000）
│   ├── index.html      # 前端 UI（由 Dockerfile 複製到容器 /app/public/）
│   └── Dockerfile      # python:3.11-slim
├── k8s/
│   └── deploy.yaml     # Namespace + 2 Workers + Dashboard
└── README.md
```

---

## 架構

```
                ┌──────────────────────────────────────────┐
                │           Namespace: cpu-bench           │
                │                                          │
  Browser ──────┤→ dashboard :3000 (NodePort 30080)        │
                │      │                   │               │
                │      ↓                   ↓               │
                │  worker-limited      worker-unlimited     │
                │  :8080               :8080               │
                │  cpu limit=100m      cpu limit=無         │
                │  mem limit=5Gi       mem req=512Mi        │
                │  ── 同一節點（podAffinity）──              │
                └──────────────────────────────────────────┘
```

| 元件 | Image | Port | CPU 設定 | 記憶體設定 |
|------|-------|------|----------|-----------|
| worker-limited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, limits=100m | requests=limits=5Gi |
| worker-unlimited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, 無 limits | requests=512Mi，無 limits |
| dashboard | `quay.io/cooloo9871/cpu-bench-dashboard:latest` | 3000 (NodePort 30080) | requests=50m, limits=500m | requests=128Mi, limits=256Mi |

兩個 worker 使用 `podAffinity`，強制排程在**相同節點**（便於在相同硬體環境下純粹對比 CPU throttle 差異）。

---

## 為什麼 CPU Limit 會讓程式變慢？

Linux CFS（Completely Fair Scheduler）的 throttle 機制：

```
CPU Limit = 100m = 0.1 core
= 每 100ms 週期只能使用 10ms 的 CPU 時間

若某任務需要 90ms 的 CPU 時間：
  ✅ Unlimited: 直接執行，~90ms 完成
  ❌ Limited:   執行 10ms → throttled 90ms → 執行 10ms → ...
                需要 9 個週期 ≈ 900ms（慢 10 倍）
```

---

## 壓測項目

### 1. CPU 壓測（Fibonacci）

遞迴 `fibonacci(36)`，純 CPU 密集型，無 I/O、無並行。直接量化 CFS throttle 造成的 wall-clock time 差距。

### 2. 多執行緒效益比較

8 次 NumPy 500×500 矩陣乘法，比較單執行緒 vs 4 執行緒的加速比。NumPy `dot` 在 C 層執行並釋放 GIL，可觀察真正的多核並行效果與 throttle 的阻礙。

### 3. 持續性 CPU 壓測（搭配 Prometheus）

可開始／停止的持續性壓測，固定以 **50% duty cycle** 燃燒 CPU（每 20ms 週期：燒 10ms、睡 10ms），相當於對系統請求 ~500m CPU。

**用途**：透過調整 Pod 的 `limits.cpu`，觀察 Prometheus 的 CFS throttle 比率如何隨之變化，找到應用真正需要的 CPU 配額。

**關鍵行為**：
- limit < 500m → 壓測需求超過配額，throttle 比率偏高
- limit ≥ 500m → 壓測需求在配額內，throttle 比率趨近 0
- 邊界效應：limit 從 480m 調到 500m，throttle 比率可從 ~70% 降至 ~4%

**Prometheus PromQL**：
```
sum(rate(container_cpu_cfs_throttled_periods_total{
  container=~"worker-.*", namespace="cpu-bench"
}[1m])) by (pod)
/
sum(rate(container_cpu_cfs_periods_total{
  container=~"worker-.*", namespace="cpu-bench"
}[1m])) by (pod)
```

### 4. NUMA 記憶體效能測試

測量跨 NUMA Node 記憶體存取的頻寬衰減與延遲倍率。

**測試設計（cross_numa 模式）**：
- `arr_local`（2048 MB）透過 libnuma `numa_alloc_onnode` 分配在 Node A
- `arr_remote`（2048 MB）透過 libnuma `numa_alloc_onnode` 分配在 Node B
- 讀取執行緒固定在 Node A 的 CPU，唯一變數是記憶體位置

**測試策略自動判斷（`_is_cpuset_pinned`）**：
- `cpuset 限制在單一 node`（worker-limited）：用各 node 自身的 CPU 執行對應 pass
- `cpuset 跨多個 node`（worker-unlimited）：固定在 node 0 的第一顆 CPU，確保只有記憶體位置在變

libnuma 使用 `mbind(MPOL_BIND)` 策略，無論哪顆 CPU 觸發 page fault，記憶體都落在正確 Node，消除傳統 first-touch 方式的不確定性。

延遲測試使用隨機指標追蹤（pointer chasing），擊敗硬體預取器，量測真實 DRAM 延遲。

若容器 CPU 只涵蓋單一 NUMA Node，自動切換為**單節點頻寬擴展測試**（1 vs N 執行緒）。

---

## Worker API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/health` | GET | 健康檢查 |
| `/info` | GET | CPU 設定資訊、允許 CPU 清單（cgroup 路徑感知偵測）|
| `/bench/all` | GET | fibonacci(36) 壓測 + CPU 資訊 |
| `/bench/threads` | GET | 單 vs 4 執行緒矩陣乘法，回傳加速比 |
| `/bench/primes` | GET | 質數計數至 50000 |
| `/bench/fibonacci` | GET | fibonacci(36) 單項測試 |
| `/bench/matrix` | GET | 200×200 矩陣乘法單項測試 |
| `/bench/numa?size_mb=2048` | GET | NUMA 記憶體頻寬與延遲測試（固定 2048 MB）|
| `/stress/start` | POST | 啟動持續性壓測（body: `duration_seconds`, `workers`, `cpu_load_percent`）|
| `/stress/stop` | POST | 停止持續性壓測 |
| `/stress/status` | GET | 查詢壓測狀態（running, remaining_seconds, cpu_load_percent）|

### CPU Limit 偵測邏輯（`/info`）

1. K8s Downward API 環境變數（`CPU_LIMIT`）
2. cgroup v2：讀取 `/proc/self/cgroup` 取得容器實際 subpath，再讀 `cpu.max`
3. cgroup v1：同上，讀 `cpu.cfs_quota_us` / `cpu.cfs_period_us`
4. cpuset 模式：`sched_getaffinity` 偵測 Static CPU Manager

---

## Dashboard API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/bench` | GET | 並行對兩個 worker 執行 `/bench/all` |
| `/api/thread_bench` | GET | 並行對兩個 worker 執行 `/bench/threads` |
| `/api/numa_bench?size_mb=2048` | GET | 並行對兩個 worker 執行 `/bench/numa` |
| `/api/stress/start` | POST | 並行對兩個 worker 啟動壓測 |
| `/api/stress/stop` | POST | 並行對兩個 worker 停止壓測 |
| `/api/stress/status` | GET | 並行查詢兩個 worker 的壓測狀態 |
| `/api/worker_info` | GET | 並行查詢兩個 worker 的 `/info` |
| `/api/health` | GET | Dashboard 自身健康檢查 |

---

## 部署

```bash
kubectl apply -f k8s/deploy.yaml
```

存取 Dashboard：`http://<NodeIP>:30080`

---

## 建置 Image

```bash
# Worker
cd worker
docker build -t quay.io/cooloo9871/cpu-bench-worker:latest .
docker push quay.io/cooloo9871/cpu-bench-worker:latest

# Dashboard
cd dashboard
docker build -t quay.io/cooloo9871/cpu-bench-dashboard:latest .
docker push quay.io/cooloo9871/cpu-bench-dashboard:latest
```

---

## 記憶體需求

NUMA 測試使用固定 2048 MB 雙陣列：

| 元件 | 大小 |
|------|------|
| arr_local（Node A） | 2048 MB |
| arr_remote（Node B） | 2048 MB |
| lat_chain × 2 | 128 MB |
| evict_buf | 64 MB |
| 其他 overhead | ~200 MB |
| **峰值合計** | **≈ 4.4 GiB** |

worker-limited 的記憶體 requests 與 limits 均設為 `5Gi`；worker-unlimited 只設 requests=`512Mi`，無 limits（NUMA 測試時峰值可達 4.4 GiB，依賴節點可用記憶體）。

---

## 安全性設定

兩個 worker Pod 均設有 container-level `securityContext`：

```yaml
securityContext:
  capabilities:
    add:
      - SYS_NICE
```

`CAP_SYS_NICE` 讓 `sched_setaffinity`（NUMA 測試的 CPU 綁核）在容器內有權限執行。
