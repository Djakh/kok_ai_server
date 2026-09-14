from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from threading import Lock

from app.common.config import get_settings

request_id_context: ContextVar[str] = ContextVar("request_id", default="unknown")

_lock = Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_gauges: dict[str, float] = defaultdict(float)
_analysis_semaphore = asyncio.Semaphore(
    min(
        get_settings().ai_max_concurrent_analyses,
        (
            get_settings().kindwise_max_concurrency
            if get_settings().plant_analysis_provider == "kindwise"
            else get_settings().ai_max_concurrent_analyses
        ),
    )
)


def increment(name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _lock:
        _counters[key] += value


def set_gauge(name: str, value: float) -> None:
    with _lock:
        _gauges[name] = value


def observe_provider_call(
    provider: str,
    capability: str,
    status: str,
    duration_seconds: float,
) -> None:
    labels = {"provider": provider, "capability": capability, "status": status}
    increment("kok_ai_provider_calls_total", labels)
    latency_labels = {"provider": provider, "capability": capability}
    increment("kok_ai_provider_latency_seconds_count", latency_labels)
    increment("kok_ai_provider_latency_seconds_sum", latency_labels, duration_seconds)


@asynccontextmanager
async def analysis_concurrency_slot() -> AsyncIterator[None]:
    await _analysis_semaphore.acquire()
    with _lock:
        _gauges["kok_ai_analysis_active"] += 1
    try:
        yield
    finally:
        with _lock:
            _gauges["kok_ai_analysis_active"] -= 1
        _analysis_semaphore.release()


def render_prometheus() -> str:
    def label_text(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        escaped = [f'{key}="{value.replace(chr(34), chr(92) + chr(34))}"' for key, value in labels]
        return "{" + ",".join(escaped) + "}"

    with _lock:
        counter_rows = [
            f"{name}{label_text(labels)} {value:g}"
            for (name, labels), value in sorted(_counters.items())
        ]
        gauge_rows = [f"{name} {value:g}" for name, value in sorted(_gauges.items())]
    return "\n".join(counter_rows + gauge_rows) + "\n"
