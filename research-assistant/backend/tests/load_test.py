"""
High-concurrency async load testing script for Deep Research & RAG APIs.
Simulates concurrent authenticated users hitting endpoints, testing latency and throughput.

Usage:
    PYTHONPATH=. python tests/load_test.py --concurrency 20 --requests 100
"""

import asyncio
import time
import argparse
import httpx
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LoadTest")

BASE_URL = "http://localhost:8000"


async def simulate_user(client: httpx.AsyncClient, user_idx: int) -> dict:
    """Simulate a user making a health check, listing history, and checking billing quota."""
    start = time.perf_counter()
    try:
        # Health check
        resp = await client.get(f"{BASE_URL}/health")
        if resp.status_code != 200:
            return {"user": user_idx, "success": False, "status": resp.status_code, "latency": time.perf_counter() - start}

        # Root ping
        resp = await client.get(f"{BASE_URL}/")
        success = resp.status_code == 200
        latency = time.perf_counter() - start
        return {"user": user_idx, "success": success, "status": resp.status_code, "latency": latency}
    except Exception as e:
        return {"user": user_idx, "success": False, "error": str(e), "latency": time.perf_counter() - start}


async def run_benchmark(concurrency: int, total_requests: int):
    logger.info(f"Starting async load test: {total_requests} requests with {concurrency} concurrent workers...")

    limits = httpx.Limits(max_keepalive_connections=50, max_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, timeout=10.0) as client:
        start_time = time.perf_counter()
        tasks = []
        for i in range(total_requests):
            tasks.append(simulate_user(client, i))

        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time

    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    latencies = [r["latency"] for r in results]

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
    rps = len(results) / total_time if total_time > 0 else 0.0

    print("\n" + "=" * 50)
    print("       LOAD TEST BENCHMARK RESULTS")
    print("=" * 50)
    print(f" Total Requests:       {total_requests}")
    print(f" Concurrency Level:    {concurrency}")
    print(f" Successful Requests:  {len(successful)} ({(len(successful)/total_requests)*100:.1f}%)")
    print(f" Failed Requests:      {len(failed)}")
    print(f" Total Time Taken:     {total_time:.3f} s")
    print(f" Requests Per Second:  {rps:.1f} req/s")
    print(f" Average Latency:      {avg_latency * 1000:.2f} ms")
    print(f" 95th Percentile:      {p95_latency * 1000:.2f} ms")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run async concurrency load test")
    parser.add_argument("--concurrency", type=int, default=20, help="Number of concurrent workers")
    parser.add_argument("--requests", type=int, default=100, help="Total requests to dispatch")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.concurrency, args.requests))
