"""In-memory per-tenant SSE event queues."""

import asyncio
import json
from collections import defaultdict

# Per-tenant event queues: {tenant_id: asyncio.Queue}
_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)


async def sse_broadcast(tenant_id: str, event_dict: dict) -> None:
    """Push an event dict onto the tenant's queue."""
    await _queues[tenant_id].put(event_dict)


async def sse_endpoint(tenant_id: str):
    """Async generator that yields SSE-formatted bytes with a 30s heartbeat."""
    queue = _queues[tenant_id]
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            yield f"data: {json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            # Heartbeat — keep the connection alive
            yield ": heartbeat\n\n"
