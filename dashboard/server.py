import os, json, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading

LIMITED_URL   = os.environ.get("WORKER_LIMITED_URL",   "http://worker-limited:8080")
UNLIMITED_URL = os.environ.get("WORKER_UNLIMITED_URL", "http://worker-unlimited:8080")

def fetch_bench(url, label):
    try:
        with urllib.request.urlopen(f"{url}/bench/all", timeout=120) as r:
            data = json.loads(r.read())
            data["label"] = label
            data["error"] = None
            return data
    except Exception as e:
        return {"label": label, "error": str(e)}

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/worker_info":
            results = {}
            def run_info(url, key, label):
                try:
                    with urllib.request.urlopen(f"{url}/info", timeout=10) as r:
                        data = json.loads(r.read())
                        data["label"] = label
                        results[key] = data
                except Exception as e:
                    results[key] = {"label": label, "error": str(e)}
            t1 = threading.Thread(target=run_info, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t2 = threading.Thread(target=run_info, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/bench":
            results = {}
            def _do_fetch(url, key, label):
                results[key] = fetch_bench(url, label)
            t1 = threading.Thread(target=_do_fetch, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t2 = threading.Thread(target=_do_fetch, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/thread_bench":
            results = {}
            def fetch_thread(url, key, label):
                try:
                    with urllib.request.urlopen(f"{url}/bench/threads", timeout=120) as r:
                        data = json.loads(r.read())
                        data["label"] = label
                        results[key] = data
                except Exception as e:
                    results[key] = {"label": label, "error": str(e)}
            t1 = threading.Thread(target=fetch_thread, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t2 = threading.Thread(target=fetch_thread, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path.startswith("/api/numa_bench"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            size_mb = qs.get("size_mb", ["1024"])[0]
            results = {}
            def run_numa(url, key, label):
                try:
                    with urllib.request.urlopen(f"{url}/bench/numa?size_mb={size_mb}", timeout=300) as r:
                        data = json.loads(r.read())
                        data["label"] = label
                        results[key] = data
                except Exception as e:
                    results[key] = {"label": label, "error": str(e)}
            t1 = threading.Thread(target=run_numa, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t2 = threading.Thread(target=run_numa, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/stress/status":
            results = {}
            def run_stress_status(url, key):
                try:
                    with urllib.request.urlopen(f"{url}/stress/status", timeout=10) as r:
                        results[key] = json.loads(r.read())
                except Exception as e:
                    results[key] = {"error": str(e)}
            t1 = threading.Thread(target=run_stress_status, args=(LIMITED_URL,   "limited"))
            t2 = threading.Thread(target=run_stress_status, args=(UNLIMITED_URL, "unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/health":
            self.send_json(200, {"status": "ok"})
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length > 0 else b"{}"

        if self.path == "/api/stress/start":
            results = {}
            def run_stress_start(url, key):
                try:
                    req = urllib.request.Request(
                        f"{url}/stress/start", data=body,
                        headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=10) as r:
                        results[key] = json.loads(r.read())
                except Exception as e:
                    results[key] = {"error": str(e)}
            t1 = threading.Thread(target=run_stress_start, args=(LIMITED_URL,   "limited"))
            t2 = threading.Thread(target=run_stress_start, args=(UNLIMITED_URL, "unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)

        elif self.path == "/api/stress/stop":
            results = {}
            def run_stress_stop(url, key):
                try:
                    req = urllib.request.Request(
                        f"{url}/stress/stop", data=b"{}",
                        headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req, timeout=10) as r:
                        results[key] = json.loads(r.read())
                except Exception as e:
                    results[key] = {"error": str(e)}
            t1 = threading.Thread(target=run_stress_stop, args=(LIMITED_URL,   "limited"))
            t2 = threading.Thread(target=run_stress_stop, args=(UNLIMITED_URL, "unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)

        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

os.chdir("/app/public")
server = ThreadedHTTPServer(("0.0.0.0", 3000), Handler)
print("Dashboard running on :3000 (threaded)", flush=True)
server.serve_forever()
