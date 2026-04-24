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
            def run(url, key, label):
                results[key] = fetch_bench(url, label)
            t1 = threading.Thread(target=run, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t2 = threading.Thread(target=run, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/thread_bench":
            results = {}
            def run_thread(url, key, label):
                try:
                    with urllib.request.urlopen(f"{url}/bench/threads", timeout=120) as r:
                        data = json.loads(r.read())
                        data["label"] = label
                        results[key] = data
                except Exception as e:
                    results[key] = {"label": label, "error": str(e)}
            t1 = threading.Thread(target=run_thread, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t2 = threading.Thread(target=run_thread, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/numa_bench":
            results = {}
            def run_numa(url, key, label):
                try:
                    with urllib.request.urlopen(f"{url}/bench/numa", timeout=120) as r:
                        data = json.loads(r.read())
                        data["label"] = label
                        results[key] = data
                except Exception as e:
                    results[key] = {"label": label, "error": str(e)}
            t1 = threading.Thread(target=run_numa, args=(LIMITED_URL,   "limited",   "CPU Limited"))
            t2 = threading.Thread(target=run_numa, args=(UNLIMITED_URL, "unlimited", "CPU Unlimited"))
            t1.start(); t2.start()
            t1.join();  t2.join()
            self.send_json(200, results)
        elif self.path == "/api/health":
            self.send_json(200, {"status": "ok"})
        else:
            super().do_GET()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

os.chdir("/app/public")
server = ThreadedHTTPServer(("0.0.0.0", 3000), Handler)
print("Dashboard running on :3000 (threaded)", flush=True)
server.serve_forever()
