# K8s CPU Throttle Benchmark

> 透過遞迴費氏數列計算，即時對比 **CPU Limited vs Unlimited** 的執行時間差異。

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
  Browser ──────┤─→ dashboard :3000(NodePort 30080)│
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
| GET | `/bench/primes` | 計算 50,000 以內質數（單獨測試用） |
| GET | `/bench/fibonacci` | 遞迴計算 fibonacci(36)（單獨測試用） |
| GET | `/bench/matrix` | 200×200 矩陣相乘（單獨測試用） |
| GET | `/bench/all` | 執行費氏數列壓測，回傳執行時間 |
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

### 單執行緒壓測：費氏數列

Dashboard 主壓測使用遞迴費氏數列（`fibonacci(36)`）作為唯一的單執行緒計算任務。

#### 為什麼選擇費氏數列？

費氏數列是 CPU throttle 壓測的理想選擇，原因如下：

**1. 純 CPU 運算，零 I/O 干擾**
遞迴費氏數列完全在 CPU 暫存器與呼叫堆疊上執行，不涉及記憶體大量分配、磁碟或網路 I/O。任何執行時間的變化都直接反映 CPU 可用量，不會被其他瓶頸稀釋。

**2. 指數級呼叫堆疊，持續佔用 CPU 時間片**
`fibonacci(36)` 展開後共需約 **2,900 萬次**函式呼叫。這段連續的 CPU 需求會跨越多個 CFS 調度週期（每週期 100ms），使 throttle 效果得以完整重複累積——每次被暫停都是真實的等待時間。

```
fibonacci(36) 呼叫次數 ≈ 2 × fib(37) - 1 ≈ 29,000,000 次
```

**3. 無法向量化、無法平行化，GIL 無法繞過**
純 Python 遞迴無法被 BLAS、numpy 或 JIT 等外部加速，每一次呼叫都必須持有 Python GIL。這確保測試結果完全反映單一 Python 執行緒受到的 CPU 配額限制，不受多核心加速干擾。

**4. 執行時間適中，差異倍數顯著**
在 100m CPU 限制下，執行時間約為無限制的 8～12 倍，差異清晰易讀且不會讓使用者等待過久。

**對比其他常見選項：**

| 計算方式 | 純 CPU | 無向量化風險 | 呼叫連續性 | 適合展示 throttle |
|---------|--------|-------------|-----------|-----------------|
| 遞迴費氏數列 | ✅ | ✅ | ✅ 持續累積 | ✅ 最佳 |
| 質數計算 | ✅ | ✅ | 尚可 | 良好 |
| 矩陣乘法（純 Python）| ✅ | ✅ | 尚可 | 良好 |
| numpy 矩陣乘法 | ✅ | ❌ BLAS 多執行緒 | — | 不穩定 |

### 多執行緒壓測

使用 Python `ThreadPoolExecutor`（4 條執行緒）並行執行 8 次 numpy 500×500 矩陣乘法，對比單一執行緒的執行時間。

選用 numpy 的原因：numpy 矩陣運算在 C 層執行，會釋放 Python GIL，讓多條執行緒可真正同時佔用多個 CPU core，是目前最貼近實際應用（線代/ML 計算）的多執行緒場景。

| 場景 | 1 執行緒 | 4 執行緒 | 加速比 | 原因 |
|------|---------|---------|--------|------|
| CPU Unlimited | ~Xms | ~X/4ms | ~4x | 4 core 真正並行，GIL 已釋放 |
| CPU Limited | ~Xms | ~Xms | ~1x | throttle 吃掉所有並行優勢 |

> **結論**：CPU limit 下，增加執行緒數無法提升效能，因為 container 的 CPU 時間預算是固定的。

### NUMA 記憶體頻寬測試

使用 256 MB float64 陣列進行連續讀取（`np.sum`），透過 `os.sched_setaffinity` 將執行緒分別綁定到不同 NUMA node 的 CPU，量測本地存取與跨 node 存取的頻寬差異。陣列大小設為 256 MB 是為了確保超過大多數伺服器 CPU 的 L3 cache，避免 cache 命中掩蓋 NUMA 效應。

| 模式 | 說明 |
|------|------|
| `cross_numa` | 記憶體分配在 Node A，分別由 Node A / Node B CPU 存取，展示跨 node 延遲 |
| `single_numa` | 僅有單一 NUMA node 時，改為 1 執行緒 vs N 執行緒頻寬擴展測試 |

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
| **費氏數列** | **~2000ms** | **~200ms** | **~10x** |

> 實際數字依節點 CPU 規格和當前負載而有所不同。
