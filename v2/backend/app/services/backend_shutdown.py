"""Shared shutdown coordination for the public website backend.

This module coordinates process-exit behavior only. It never mutates trading,
execution, live-gate, exchange, or Redis producer state.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

SERVICE_RESTART_CLOSE_CODE = 1012


@dataclass(frozen=True)
class TrackedTaskSnapshot:
    label: str
    task_name: str
    done: bool
    cancelled: bool
    age_ms: int


_shutdown_event = threading.Event()
_active_tasks_lock = threading.Lock()
_active_tasks: dict[asyncio.Task[Any], tuple[str, float]] = {}


def reset_shutdown_signal() -> None:
    """Mark the process as accepting work after application startup."""
    _shutdown_event.clear()


def begin_shutdown() -> None:
    """Mark the process as shutting down before resource teardown."""
    _shutdown_event.set()


def shutdown_started() -> bool:
    return _shutdown_event.is_set()


async def wait_for_shutdown() -> None:
    """Async wait for shutdown without binding a global asyncio.Event to a loop."""
    while not _shutdown_event.is_set():
        await asyncio.sleep(0.05)


async def sleep_or_shutdown(seconds: float) -> bool:
    """Sleep in cancellable slices.

    Returns True when shutdown started before the timeout elapsed.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while not _shutdown_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.1, remaining))
    return True


@asynccontextmanager
async def track_current_task(label: str) -> AsyncIterator[None]:
    task = asyncio.current_task()
    if task is None:
        yield
        return
    with _active_tasks_lock:
        _active_tasks[task] = (label, time.monotonic())
    try:
        yield
    finally:
        with _active_tasks_lock:
            _active_tasks.pop(task, None)


def create_registered_task(coro: Coroutine[Any, Any, Any], *, label: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    with _active_tasks_lock:
        _active_tasks[task] = (label, time.monotonic())

    def _discard(done_task: asyncio.Task[Any]) -> None:
        with _active_tasks_lock:
            _active_tasks.pop(done_task, None)

    task.add_done_callback(_discard)
    return task


def active_task_snapshots() -> list[TrackedTaskSnapshot]:
    now = time.monotonic()
    with _active_tasks_lock:
        items = list(_active_tasks.items())
    snapshots: list[TrackedTaskSnapshot] = []
    for task, (label, started) in items:
        snapshots.append(
            TrackedTaskSnapshot(
                label=label,
                task_name=task.get_name(),
                done=task.done(),
                cancelled=task.cancelled(),
                age_ms=max(0, int((now - started) * 1000)),
            )
        )
    return snapshots


async def cancel_and_wait_for_registered_tasks(timeout_seconds: float) -> list[TrackedTaskSnapshot]:
    """Cancel tracked helper tasks and wait briefly for request handlers to exit."""
    begin_shutdown()
    with _active_tasks_lock:
        tasks = list(_active_tasks.keys())
    for task in tasks:
        if task is not asyncio.current_task() and not task.done():
            task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=max(0.0, timeout_seconds))
    return active_task_snapshots()
