# K8s CPU Throttle Benchmark

> 透過 3 種 CPU 密集運算，即時對比 **CPU Limited vs Unlimited** 的執行時間差異。

## 專案結構

```
K8s_cpu-benchmark/
├── worker/                   # CPU 壓測 API (Python Flask)
│   ├── app.py                # Flask 應用，提供壓測 endpoints
│   └── Dockerfile            # python:3.11-slim，port 8080
├── dashboard/                # Web UI 儀表板
│   ├── server.py             # Python 標準庫 HTTP server（Dockerfile 實際使用）
│   ├── index.html            # 對應 server.py 的前端（輪詢 /api/bench）
│   ├── server.js             # Node.js + Socket.IO 版（備用，未用於 Dockerfile）
│   ├── package.json          # Node.js 依賴（express, socket.io, node-fetch）
│   ├── Dockerfile            # python:3.11-slim，port 3000
│   └── public/
│       └── index.html        # 對應 server.js 的前端（Socket.IO 版）
├── k8s/
│   └── deploy.yaml           # K8s manifest（namespace, 2 workers, dashboard）
└── README.md
```

## 為什麼設定 CPU Limit 會讓程式變慢？

Linux CFS (Completely Fair Scheduler) 的 CPU throttle 機制：

```
CPU Limit = 100m = 0.1 core
= 每 100ms 週期只能使用 10ms 的 CPU 時間

若程式需要用 90ms 的 CPU 時間：
  ✅ Unlimited: 直接執行，90ms 完成
  ❌ Limited:   使用 10ms → throttled 90ms → 使用 10ms → ...
                總共需要 9 個週期 = ~900ms !!
```

**差異倍數取決於：**
- Limit 設定值（越低差異越大）
- 節點實際可用 CPU（越多 Unlimited 越快）
- 工作負載的 CPU 密集程度

## 架構說明

```
                ┌─────────────────────────────────┐
                │       Namespace: cpu-bench       │
                │                                  │
  Browser ──────┤─→ dashboard :3000 (NodePort 30080)
                │       │              │           │
                │       ↓              ↓           │
                │  worker-limited  worker-unlimited │
                │  :8080 (100m)    :8080 (no limit)│
                └─────────────────────────────────┘
```

| 元件 | Image | Port | CPU 設定 |
|------|-------|------|----------|
| worker-limited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, limits=100m |
| worker-unlimited | `quay.io/cooloo9871/cpu-bench-worker:latest` | 8080 | requests=100m, 無 limits |
| dashboard | `quay.io/cooloo9871/cpu-bench-dashboard:latest` | 3000 (NodePort 30080) | requests=50m, limits=500m |

## Worker API

Worker 同時部署兩個實例（limited / unlimited），各自提供相同 endpoints：

| Method | Path | 說明 |
|--------|------|------|
| GET | `/health` | 健康檢查，回傳 pod 名稱 |
| GET | `/info` | Pod 資訊與 CPU limit 狀態 |
| GET | `/bench/primes` | 計算 50,000 以內質數 |
| GET | `/bench/fibonacci` | 遞迴計算 fibonacci(36) |
| GET | `/bench/matrix` | 200×200 矩陣相乘 |
| GET | `/bench/all` | 依序執行全部三項，回傳總時間 |
| GET | `/bench/threads` | 1 執行緒 vs 4 執行緒並行 numpy 矩陣乘法（500×500 ×8），回傳加速比 |

## Dashboard 實作說明

Dashboard 有兩個 server 實作，目前 **Dockerfile 使用 Python 版**：

| 檔案 | 前端 | 通訊方式 |
|------|------|----------|
| `server.py` + `index.html` | 輪詢 REST | `GET /api/bench`，兩 worker 並行取結果 |
| `server.js` + `public/index.html` | Socket.IO | 事件驅動，`run_benchmark` / `benchmark_result` |

## 部署流程

### 1. Build Container 映像檔

```bash
# Worker
podman build -t YOUR_REGISTRY/cpu-bench-worker:latest ./worker
podman push YOUR_REGISTRY/cpu-bench-worker:latest

# Dashboard
podman build -t YOUR_REGISTRY/cpu-bench-dashboard:latest ./dashboard
podman push YOUR_REGISTRY/cpu-bench-dashboard:latest
```

### 2. 修改 deploy.yaml

將所有 `quay.io/cooloo9871/` 替換成你的 Registry 路徑。

### 3. 套用 Manifest

```bash
kubectl apply -f k8s/deploy.yaml
```

### 4. 確認 Pods 狀態

```bash
kubectl get pods -n cpu-bench
kubectl get services -n cpu-bench
```

### 5. 開啟儀表板

```bash
kubectl port-forward --address <your ip address> svc/dashboard 3000:3000 -n cpu-bench
# 開啟 http://<your ip address>:3000
```

## 壓測項目說明

| 任務 | 內容 | CPU 特性 |
|------|------|----------|
| **質數計算**（Dashboard：Primes） | 計算 50,000 以內的質數 | 持續迴圈運算，最能展示 throttle |
| **費氏數列**（Dashboard：Fibonacci） | 遞迴計算 fibonacci(36) | 指數級呼叫堆疊，瞬間大量 CPU |
| **矩陣乘法**（Dashboard：Matrix） | 200×200 矩陣相乘 | 密集浮點數運算 |
| **多執行緒比較**（Dashboard：Thread Benchmark） | numpy 500×500 矩陣乘法 ×8（1 條 vs 4 條執行緒） | 展示 CPU throttle 如何吃掉多核並行優勢 |

### 多執行緒測試說明

使用 Python `ThreadPoolExecutor`（4 條執行緒）並行執行 8 次 numpy 500×500 矩陣乘法，對比單一執行緒的執行時間。

選用 numpy 的原因：numpy 矩陣運算在 C 層執行，會釋放 Python GIL，讓多條執行緒可真正同時佔用多個 CPU core，是目前最貼近實際應用（線代/ML 計算）的多執行緒場景。

| 場景 | 1 執行緒 | 4 執行緒 | 加速比 | 原因 |
|------|---------|---------|--------|------|
| CPU Unlimited | ~Xms | ~X/4ms | ~4x | 4 core 真正並行，GIL 已釋放 |
| CPU Limited | ~Xms | ~Xms | ~1x | throttle 吃掉所有並行優勢 |

> **結論**：CPU limit 下，增加執行緒數無法提升效能，因為 container 的 CPU 時間預算是固定的。

## 調整 CPU Limit

修改 `k8s/deploy.yaml` 中 `worker-limited` 的 limit：

```yaml
resources:
  limits:
    cpu: "100m"   # 試試 50m（更慢）或 500m（差異縮小）
```

重新套用：
```bash
kubectl apply -f k8s/deploy.yaml
kubectl rollout restart deployment/worker-limited -n cpu-bench
```

## 觀察 CPU Throttle 指標

```bash
# 安裝 metrics-server（如果還沒有）
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# 即時 CPU 使用量
kubectl top pods -n cpu-bench --sort-by=cpu

# 查看 Pod 詳細資訊（含 Throttle 事件）
kubectl describe pod -l app=worker-limited -n cpu-bench
```

## 清除所有資源

```bash
kubectl delete -f k8s/deploy.yaml
```

## 預期結果

在典型的 4-core 節點上，Limited (100m) vs Unlimited 的差異：

| 測試項目 | Limited | Unlimited | 差異倍數 |
|---------|---------|-----------|---------|
| 質數計算 | ~3000ms | ~300ms | ~10x |
| 費氏數列 | ~2000ms | ~200ms | ~10x |
| 矩陣乘法 | ~5000ms | ~500ms | ~10x |
| **總計** | **~10s** | **~1s** | **~10x** |

> 實際數字依節點 CPU 規格和當前負載而有所不同。
