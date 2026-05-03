# K8s CPU Benchmark

透過多項壓測，即時對比 **CPU Limited（100m）vs CPU Unlimited** 兩個 Pod 在 Kubernetes 中的執行差異，涵蓋 CPU 節流、多執行緒擴展性，以及 NUMA 記憶體拓撲效能。

---

## 專案結構

```
K8s_cpu-benchmark/
├── worker/
│   ├── app.py          # Flask 壓測 API（port 8080）
│   └── Dockerfile      # python:3.11-slim + libnuma1
├── dashboard/
│   ├── server.py       # Python HTTP server（port 3000）
│   ├── index.html      # 前端 UI（由 server.py 提供）
│   └── Dockerfile      # python:3.11-slim
├── k8s/
│   └── deploy.yaml     # Namespace + 2 Workers + Dashboard
└── README.md
```

---

## 架構

```
                ┌──────────────────────────────────────┐
                │         Namespace: cpu-bench         │
                │                                      │
  Browser ──────┤→ dashboard :3000 (NodePort 30080)    │
                │      │                │              │
                │      ↓                ↓              │
                │  worker-limited   worker-unlimited   │
                │  :8080            :8080              │
                │  cpu=100m         cpu=（無限制）      │
                │  mem≤5Gi          mem≤5Gi            │
                └──────────────────────────────────────┘
```

| 元件 | Image | Port | CPU 設定 |
|------|-------|------|----------|
| worker-limited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, limits=100m |
| worker-unlimited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, 無 limits |
| dashboard | `quay.io/cooloo9871/cpu-bench-dashboard:latest` | 3000 (NodePort 30080) | requests=50m, limits=500m |

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

遞迴 `fibonacci(36)`，純 CPU 密集型，無 I/O、無並行。
直接量化 CFS throttle 造成的執行時間差距。

- **API**: `GET /bench/all`

### 2. 執行緒擴展性測試

8 次 NumPy 500×500 矩陣乘法，比較單執行緒 vs 4 執行緒的加速比。
NumPy `dot` 在 C 層執行並釋放 GIL，可觀察真正的多核並行效果。

- **API**: `GET /bench/threads`

### 3. NUMA 記憶體效能測試

測量跨 NUMA Node 記憶體存取的頻寬衰減與延遲倍率。

**測試設計**：
- `arr_local`（2048 MB）透過 libnuma `numa_alloc_onnode` 分配在 Node A
- `arr_remote`（2048 MB）透過 libnuma `numa_alloc_onnode` 分配在 Node B
- 兩次 pass 的讀取執行緒均固定在 Node A 的 CPU（`sched_setaffinity`）
- 唯一變數是記憶體位置，確保對比的科學性

libnuma 使用 `mbind(MPOL_BIND)` 策略，無論哪顆 CPU 觸發 page fault，記憶體都落在正確的 Node，消除傳統 first-touch 方式的不確定性。

延遲測試使用隨機指標追蹤（pointer chasing），有效擊敗硬體預取器，量測真實 DRAM 存取延遲。

若容器 CPU 只涵蓋單一 NUMA Node（cpuset 受限），自動切換為**單節點頻寬擴展測試**（1 vs N 執行緒）。

- **API**: `GET /bench/numa?size_mb=2048`（固定 2048 MB）

---

## Worker API 端點

| 端點 | 說明 |
|------|------|
| `GET /health` | 健康檢查，回傳 `{"status":"ok","pod":"..."}` |
| `GET /info` | CPU 設定資訊（cgroup 路徑感知偵測）、允許 CPU 清單 |
| `GET /bench/all` | fibonacci(36) 壓測 + CPU 資訊 |
| `GET /bench/threads` | 單 vs 多執行緒矩陣乘法，回傳加速比 |
| `GET /bench/primes` | 質數計數至 50000 |
| `GET /bench/fibonacci` | fibonacci(36) 單項測試 |
| `GET /bench/matrix` | 200×200 矩陣乘法單項測試 |
| `GET /bench/numa?size_mb=N` | NUMA 記憶體頻寬與延遲測試 |

### CPU Limit 偵測邏輯（`/info`）

1. K8s Downward API 環境變數（`CPU_LIMIT`）
2. cgroup v2：讀取 `/proc/self/cgroup` 取得容器實際 subpath，再讀 `cpu.max`
3. cgroup v1：同上，讀 `cpu.cfs_quota_us` / `cpu.cfs_period_us`
4. cpuset 模式：`sched_getaffinity` 偵測 Static CPU Manager

---

## Dashboard API 端點

| 端點 | 說明 |
|------|------|
| `GET /api/bench` | 同時對兩個 worker 執行 `/bench/all`（並行） |
| `GET /api/thread_bench` | 同時對兩個 worker 執行 `/bench/threads`（並行） |
| `GET /api/numa_bench?size_mb=2048` | 依序對兩個 worker 執行 `/bench/numa`（Limited 先，避免頻寬干擾） |
| `GET /api/worker_info` | 同時查詢兩個 worker 的 `/info`（並行） |
| `GET /api/health` | Dashboard 自身健康檢查 |

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

NUMA 測試使用固定 2048 MB 陣列：

| 元件 | 大小 |
|------|------|
| arr_local（Node A） | 2048 MB |
| arr_remote（Node B） | 2048 MB |
| lat_chain × 2 | 128 MB |
| evict_buf | 64 MB |
| 其他 overhead | ~200 MB |
| **峰值合計** | **≈ 4.4 GiB** |

兩個 worker Pod 的記憶體 limit 均設為 `5Gi`，worker-limited 的 CPU limit 固定為 `100m`，worker-unlimited 不設 CPU limit。
