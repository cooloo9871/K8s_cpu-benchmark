# K8s CPU Throttle Benchmark

> 透過 3 種 CPU 密集運算，即時對比 **CPU Limited vs Unlimited** 的執行時間差異。

## 📁 專案結構

```
cpu-bench/
├── worker/           # CPU 壓測 API (Python Flask)
│   ├── app.py
│   └── Dockerfile
├── dashboard/        # Web UI 儀表板 (Node.js + Socket.IO)
│   ├── server.js
│   ├── package.json
│   ├── Dockerfile
│   └── public/
│       └── index.html
├── k8s/
│   └── deploy.yaml   # 通用 K8s manifest
├── start-minikube.sh # 一鍵啟動腳本（minikube）
└── README.md
```

## 🔬 為什麼設定 CPU Limit 會讓程式變慢？

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

## 🚀 快速啟動 (Minikube)

```bash
# 給腳本執行權限
chmod +x start-minikube.sh

# 一鍵建置並部署
./start-minikube.sh
```

然後打開腳本輸出的 URL，按「Run Benchmark」即可看到差異。

## 🚀 手動部署流程

### 1. Build Docker 映像檔

```bash
# Worker
docker build -t YOUR_REGISTRY/cpu-bench-worker:latest ./worker
docker push YOUR_REGISTRY/cpu-bench-worker:latest

# Dashboard
docker build -t YOUR_REGISTRY/cpu-bench-dashboard:latest ./dashboard
docker push YOUR_REGISTRY/cpu-bench-dashboard:latest
```

### 2. 修改 deploy.yaml

將所有 `ghcr.io/YOUR_ORG/` 替換成你的 Registry 路徑。

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

**Minikube:**
```bash
minikube service dashboard -n cpu-bench
```

**雲端 K8s (GKE/EKS/AKS):**
```bash
# 取得 NodePort
kubectl get svc dashboard -n cpu-bench
# 或改 Service type 為 LoadBalancer
kubectl patch svc dashboard -n cpu-bench -p '{"spec":{"type":"LoadBalancer"}}'
kubectl get svc dashboard -n cpu-bench  # 等待 EXTERNAL-IP
```

**Port-forward（任何環境）:**
```bash
kubectl port-forward svc/dashboard 3000:3000 -n cpu-bench
# 開啟 http://localhost:3000
```

## 📊 壓測項目說明

| 任務 | 內容 | CPU 特性 |
|------|------|----------|
| **質數計算** | 計算 50,000 以內的質數 | 持續迴圈運算，最能展示 throttle |
| **費氏數列** | 遞迴計算 fibonacci(36) | 指數級呼叫堆疊，瞬間大量 CPU |
| **矩陣乘法** | 200×200 矩陣相乘 | 密集浮點數運算 |

## 🔧 調整 CPU Limit

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

## 📈 觀察 CPU Throttle 指標

```bash
# 安裝 metrics-server（如果還沒有）
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# 即時 CPU 使用量
kubectl top pods -n cpu-bench --sort-by=cpu

# 查看 Pod 詳細資訊（含 Throttle 事件）
kubectl describe pod -l app=worker-limited -n cpu-bench
```

## 🧹 清除所有資源

```bash
kubectl delete namespace cpu-bench
```

## 💡 預期結果

在典型的 4-core 節點上，Limited (100m) vs Unlimited 的差異：

| 測試項目 | Limited | Unlimited | 差異倍數 |
|---------|---------|-----------|---------|
| 質數計算 | ~3000ms | ~300ms | ~10x |
| 費氏數列 | ~2000ms | ~200ms | ~10x |
| 矩陣乘法 | ~5000ms | ~500ms | ~10x |
| **總計** | **~10s** | **~1s** | **~10x** |

> 實際數字依節點 CPU 規格和當前負載而有所不同。
