"""Drains the research queue. Runs as its own process, next to the API:

    cd backend && python -m worker

The API records a request and returns; this claims it, runs the pipeline, and
publishes progress to research_events for the WebSocket to relay. See jobs.py
for the queue itself.

Scale by running more of these. Each claims with FOR UPDATE SKIP LOCKED, so two
workers never take the same job.
"""
import asyncio
import logging
import signal
import time

import jobs
from billing import refund_quota
from config import get_settings
from db import save_session
from graph.research_graph import finalize_cost, stream_research
from jobs import Lease, LeaseLost
from logging_config import configure_logging

logger = logging.getLogger("worker")

POLL_SECONDS = 1.0
# Tokens are batched rather than written one row each: a report is thousands
# of tokens, and a quarter-second of latency on streamed text is invisible.
FLUSH_SECONDS = 0.25
HEARTBEAT_SECONDS = 20
HOUSEKEEPING_SECONDS = 60
PRUNE_SECONDS = 600


async def _pipeline(lease: Lease) -> dict:
    """Run the research, publishing events as they arrive. Returns final state."""
    state: dict = {}
    pending: list[dict] = []
    last_flush = time.monotonic()

    async def flush():
        nonlocal pending, last_flush
        if pending:
            batch, pending = pending, []
            await asyncio.to_thread(jobs.append, lease, batch)
        last_flush = time.monotonic()

    async for event in stream_research(lease.query, lease.job_id, user_id=lease.user_id):
        if event.get("type") == "token":
            tail = pending[-1] if pending else None
            if tail and tail["type"] == "token" and tail["node"] == event["node"]:
                tail["text"] += event["text"]
            else:
                pending.append({"type": "token", "node": event["node"], "text": event["text"]})
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                await flush()
            continue

        state.update(event.get("state", {}))
        pending.append({"type": "progress", "node": event["node"],
                        "step": event["step"], "data": event["data"]})
        await flush()

    await flush()
    return finalize_cost(state, lease.job_id)


async def _heartbeat(lease: Lease) -> None:
    """Keep the lease alive through long silent stretches (one slow model call
    can outlast it), and notice a cancellation without waiting for output."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await asyncio.to_thread(jobs.extend, lease)


async def run_job(lease: Lease) -> None:
    logger.info(f"[Worker] Claimed {lease.job_id} (attempt {lease.attempt}/{lease.max_attempts})")
    pipeline = asyncio.create_task(_pipeline(lease))
    heartbeat = asyncio.create_task(_heartbeat(lease))
    try:
        done, _ = await asyncio.wait({pipeline, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            heartbeat.result()  # raises LeaseLost; the pipeline is cancelled below
        state = pipeline.result()

        # Saved before the job is marked done, so by the time a client sees
        # "complete" the report is already there to fetch.
        await asyncio.to_thread(save_session, lease.job_id, lease.user_id, lease.query, state)
        if await asyncio.to_thread(jobs.complete, lease,
                                   {"type": "complete", "session_id": lease.job_id}):
            logger.info(f"[Worker] Finished {lease.job_id}")
    except LeaseLost:
        logger.info(f"[Worker] {lease.job_id} was cancelled or taken over — stopped")
    except asyncio.CancelledError:
        # Shutting down. Hand the job straight back rather than leaving the
        # next worker to wait out the lease.
        await asyncio.to_thread(jobs.release, lease)
        logger.info(f"[Worker] Released {lease.job_id} on shutdown")
        raise
    except Exception as e:
        logger.error(f"[Worker] {lease.job_id} failed: {e!r}")
        outcome = await asyncio.to_thread(jobs.fail, lease, repr(e))
        if outcome == "failed":
            # Don't bill the user for our own failure. A retry is still going
            # to deliver, so only the attempt that gives up refunds.
            await asyncio.to_thread(refund_quota, lease.user_id)
    finally:
        for task in (pipeline, heartbeat):
            task.cancel()


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def worker_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            lease = await asyncio.to_thread(jobs.claim)
        except Exception as e:
            logger.error(f"[Worker] Claim failed: {e!r}")
            lease = None
        if lease is None:
            await _wait(stop, POLL_SECONDS)
            continue
        try:
            await run_job(lease)
        except Exception as e:
            # Only reachable when recording the failure itself failed (the
            # database went away). The lease lapses and the job is retried.
            logger.error(f"[Worker] Could not record outcome of {lease.job_id}: {e!r}")


async def housekeeping(stop: asyncio.Event) -> None:
    last_prune = 0.0
    while not stop.is_set():
        try:
            for user_id in await asyncio.to_thread(jobs.reap_exhausted):
                await asyncio.to_thread(refund_quota, user_id)
            if time.monotonic() - last_prune >= PRUNE_SECONDS:
                pruned = await asyncio.to_thread(jobs.prune)
                if pruned:
                    logger.info(f"[Worker] Pruned {pruned} finished job(s)")
                last_prune = time.monotonic()
        except Exception as e:
            logger.error(f"[Worker] Housekeeping failed: {e!r}")
        await _wait(stop, HOUSEKEEPING_SECONDS)


async def main() -> None:
    concurrency = max(1, get_settings().worker_concurrency)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    # The corpus agent embeds the query; pay the model load here, once, rather
    # than on the first job after a deploy.
    try:
        from rag.embeddings import embed_query
        await asyncio.to_thread(embed_query, "warmup")
    except Exception as e:
        logger.error(f"[Worker] Failed to warm embedding model: {e}")

    tasks = [asyncio.create_task(worker_loop(stop)) for _ in range(concurrency)]
    tasks.append(asyncio.create_task(housekeeping(stop)))
    logger.info(f"[Worker] {jobs.WORKER_ID} started, concurrency={concurrency}")

    await stop.wait()
    logger.info("[Worker] Shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    configure_logging(level=logging.INFO)
    asyncio.run(main())
