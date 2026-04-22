const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const fetch = (...args) => import('node-fetch').then(({default: f}) => f(...args));

const app = express();
const server = http.createServer(app);
const io = new Server(server);

const WORKER_LIMITED_URL = process.env.WORKER_LIMITED_URL || 'http://worker-limited:8080';
const WORKER_UNLIMITED_URL = process.env.WORKER_UNLIMITED_URL || 'http://worker-unlimited:8080';

app.use(express.static('public'));

async function fetchEndpoint(url, path, label) {
  try {
    const res = await fetch(`${url}${path}`, { timeout: 10000 });
    const data = await res.json();
    return { ...data, label, error: null };
  } catch (e) {
    return { label, error: e.message };
  }
}

async function runBench(url, label) {
  try {
    const start = Date.now();
    const res = await fetch(`${url}/bench/all`, { timeout: 60000 });
    const data = await res.json();
    return { ...data, label, fetch_ms: Date.now() - start, error: null };
  } catch (e) {
    return { label, error: e.message };
  }
}

async function runThreadBenchWorker(url, label) {
  try {
    const res = await fetch(`${url}/bench/threads`, { timeout: 120000 });
    const data = await res.json();
    return { ...data, label, error: null };
  } catch (e) {
    return { label, error: e.message };
  }
}

io.on('connection', (socket) => {
  console.log('Dashboard client connected');

  socket.on('get_worker_info', async () => {
    const [limited, unlimited] = await Promise.all([
      fetchEndpoint(WORKER_LIMITED_URL, '/info', 'CPU Limited'),
      fetchEndpoint(WORKER_UNLIMITED_URL, '/info', 'CPU Unlimited'),
    ]);
    socket.emit('worker_info', { limited, unlimited });
  });

  socket.on('run_benchmark', async () => {
    socket.emit('benchmark_start', { timestamp: new Date().toISOString() });

    const [limited, unlimited] = await Promise.all([
      runBench(WORKER_LIMITED_URL, 'CPU Limited'),
      runBench(WORKER_UNLIMITED_URL, 'CPU Unlimited'),
    ]);

    socket.emit('benchmark_result', { limited, unlimited, timestamp: new Date().toISOString() });
  });

  socket.on('run_thread_benchmark', async () => {
    socket.emit('benchmark_start', { timestamp: new Date().toISOString() });
    const [limited, unlimited] = await Promise.all([
      runThreadBenchWorker(WORKER_LIMITED_URL, 'CPU Limited'),
      runThreadBenchWorker(WORKER_UNLIMITED_URL, 'CPU Unlimited'),
    ]);
    socket.emit('thread_benchmark_result', { limited, unlimited, timestamp: new Date().toISOString() });
  });

  socket.on('disconnect', () => {
    console.log('Client disconnected');
  });
});

server.listen(3000, () => {
  console.log('Dashboard running on :3000');
});
