"""Golden tests pinning SimpleTaskQueue scheduling semantics.

These tests describe externally observable behaviour only (dequeue order,
FIFO ties, dedupe, worker wakeup, cancellation, queue_size consistency) so
that the internal queue data structure can be refactored without semantic
drift. They must pass unchanged before and after the refactor.

Sort key under test (ascending):
    (task_type_order, priority_class, max(1, estimated_work_units), enqueue_sequence)
where task_type_order is 0 for "structured"/"recognition" and 1 otherwise.
"""
from __future__ import annotations

import asyncio
import time

from app.services.task_queue import SimpleTaskQueue, TaskItem


class DummyStore:
    """Minimal stand-in for JobStore: records status updates, ignores the rest."""

    def __init__(self) -> None:
        self.status_updates: list[tuple[str, str, str | None]] = []

    def update_item_performance(self, item_id, patch) -> None:
        pass

    def update_item_status(self, item_id, status, error_message=None) -> None:
        self.status_updates.append((item_id, getattr(status, "value", str(status)), error_message))

    def touch_job_updated(self, job_id) -> None:
        pass

    def repair_stale_processing_items(self, **kwargs) -> list:
        return []


def make_task(
    item_id: str,
    *,
    task_type: str = "recognition",
    priority_class: int = 1,
    work_units: int = 1,
) -> TaskItem:
    """Build a TaskItem with explicit priority metadata (skips file inspection)."""
    return TaskItem(
        job_id="job-0001",
        item_id=item_id,
        file_id=f"file-{item_id}",
        task_type=task_type,
        meta={"priority_class": priority_class, "estimated_work_units": work_units},
    )


class QueueHarness:
    """SimpleTaskQueue with task handlers stubbed to record processing order."""

    def __init__(self, concurrency: int = 1) -> None:
        self.queue = SimpleTaskQueue(concurrency=concurrency)
        self.store = DummyStore()
        self.queue._get_store = lambda: self.store
        self.processed: list[tuple[str, str]] = []
        self.start_times: dict[str, float] = {}
        self.started_events: dict[str, asyncio.Event] = {}
        self.release_events: dict[str, asyncio.Event] = {}
        self.failing_items: set[str] = set()
        self.handler_delay: float = 0.0

        async def handle(task: TaskItem) -> None:
            self.start_times[task.item_id] = time.monotonic()
            started = self.started_events.get(task.item_id)
            if started is not None:
                started.set()
            release = self.release_events.get(task.item_id)
            if release is not None:
                await release.wait()
            if self.handler_delay:
                await asyncio.sleep(self.handler_delay)
            if task.item_id in self.failing_items:
                raise RuntimeError(f"boom {task.item_id}")
            self.processed.append((task.task_type, task.item_id))

        self.queue._run_recognition = handle
        self.queue._run_redaction = handle
        self.queue._run_structured = handle

    def add_blocker(self, item_id: str) -> tuple[asyncio.Event, asyncio.Event]:
        """Make item_id's handler signal start and then wait for release."""
        started = asyncio.Event()
        release = asyncio.Event()
        self.started_events[item_id] = started
        self.release_events[item_id] = release
        return started, release

    async def shutdown(self) -> None:
        tasks = self.queue.stop()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def wait_until(predicate, timeout: float = 5.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met within timeout")


def test_mixed_priority_dequeue_order():
    """Tasks drain by (type order, priority_class, work_units), not enqueue order."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        try:
            blocker_started, blocker_release = h.add_blocker("blocker")
            h.queue.enqueue(make_task("blocker", priority_class=-1))
            await blocker_started.wait()

            # Scrambled enqueue order; expected drain order is by sort key.
            h.queue.enqueue(make_task("redaction-p0", task_type="redaction", priority_class=0))
            h.queue.enqueue(make_task("rec-p2", priority_class=2))
            h.queue.enqueue(make_task("rec-p1-w5", priority_class=1, work_units=5))
            h.queue.enqueue(make_task("structured-p0", task_type="structured", priority_class=0))
            h.queue.enqueue(make_task("rec-p1-w1", priority_class=1, work_units=1))
            assert h.queue.queue_size == 5  # blocker already taken by the worker

            blocker_release.set()
            await wait_until(lambda: len(h.processed) == 6)
            assert h.processed == [
                ("recognition", "blocker"),
                ("structured", "structured-p0"),   # type order 0, pc 0
                ("recognition", "rec-p1-w1"),      # pc 1, work 1
                ("recognition", "rec-p1-w5"),      # pc 1, work 5
                ("recognition", "rec-p2"),         # pc 2
                ("redaction", "redaction-p0"),     # type order 1 sorts after all of the above
            ]
            assert h.queue.queue_size == 0
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_same_priority_fifo_order():
    """Tasks with identical sort keys drain strictly in enqueue order."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        try:
            blocker_started, blocker_release = h.add_blocker("blocker")
            h.queue.enqueue(make_task("blocker", priority_class=-1))
            await blocker_started.wait()

            ids = [f"item-{i}" for i in range(6)]
            for item_id in ids:
                h.queue.enqueue(make_task(item_id, priority_class=3, work_units=2))

            blocker_release.set()
            await wait_until(lambda: len(h.processed) == 7)
            assert [item_id for _, item_id in h.processed[1:]] == ids
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_higher_priority_jumps_ahead_of_earlier_enqueue():
    """A later high-priority enqueue overtakes already-queued low-priority tasks."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        try:
            blocker_started, blocker_release = h.add_blocker("blocker")
            h.queue.enqueue(make_task("blocker", priority_class=-1))
            await blocker_started.wait()

            h.queue.enqueue(make_task("low-a", priority_class=5))
            h.queue.enqueue(make_task("low-b", priority_class=5))
            h.queue.enqueue(make_task("high-c", priority_class=0))

            blocker_release.set()
            await wait_until(lambda: len(h.processed) == 4)
            assert [item_id for _, item_id in h.processed[1:]] == ["high-c", "low-a", "low-b"]
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_duplicate_pending_enqueue_is_skipped():
    """(task_type, item_id) dedupe: pending duplicates dropped; re-enqueue after done OK."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        try:
            blocker_started, blocker_release = h.add_blocker("blocker")
            h.queue.enqueue(make_task("blocker", priority_class=-1))
            await blocker_started.wait()

            h.queue.enqueue(make_task("dup"))
            h.queue.enqueue(make_task("dup"))  # duplicate while pending: skipped
            assert h.queue.queue_size == 1
            # Same item_id but different task_type is NOT a duplicate.
            h.queue.enqueue(make_task("dup", task_type="redaction"))
            assert h.queue.queue_size == 2

            blocker_release.set()
            await wait_until(lambda: len(h.processed) == 3)
            assert h.processed.count(("recognition", "dup")) == 1
            assert h.processed.count(("redaction", "dup")) == 1

            # After completion the dedupe entry is released: enqueue works again.
            h.queue.enqueue(make_task("dup"))
            await wait_until(lambda: h.processed.count(("recognition", "dup")) == 2)
            assert h.queue.queue_size == 0
            assert not h.queue._pending_items
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_enqueue_wakes_waiting_worker_immediately():
    """A worker parked in queue.get() is woken by enqueue, not by the 2s re-poll."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        try:
            await asyncio.sleep(0.05)  # let the worker park in get()
            t0 = time.monotonic()
            h.queue.enqueue(make_task("wakeup"))
            await wait_until(lambda: len(h.processed) == 1)
            latency = h.start_times["wakeup"] - t0
            assert latency < 1.5, f"worker woke too slowly ({latency:.3f}s), wakeup broken"
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_concurrent_enqueue_and_consume():
    """Real asyncio concurrency: 3 producers + 3 workers, every task runs exactly once."""

    async def main() -> None:
        h = QueueHarness(concurrency=3)
        h.handler_delay = 0.002
        h.queue.start()
        try:
            async def producer(prefix: str, count: int) -> None:
                for i in range(count):
                    h.queue.enqueue(make_task(f"{prefix}-{i}", priority_class=i % 3))
                    await asyncio.sleep(0)

            await asyncio.gather(
                producer("a", 10), producer("b", 10), producer("c", 10)
            )
            await wait_until(lambda: len(h.processed) == 30)
            processed_ids = [item_id for _, item_id in h.processed]
            assert len(processed_ids) == 30
            assert len(set(processed_ids)) == 30  # exactly once each
            assert h.queue.queue_size == 0
            assert not h.queue._pending_items
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_handler_exception_marks_failed_and_worker_continues():
    """A failing task is marked FAILED, released from dedupe, and the worker survives."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.failing_items.add("bad")
        h.queue.start()
        try:
            h.queue.enqueue(make_task("bad"))
            h.queue.enqueue(make_task("good"))
            await wait_until(lambda: ("recognition", "good") in h.processed)

            failed = [u for u in h.store.status_updates if u[0] == "bad" and u[1] == "failed"]
            assert len(failed) == 1
            assert "RuntimeError" in (failed[0][2] or "")
            assert h.queue.queue_size == 0
            assert not h.queue._pending_items  # failed key released for re-enqueue

            h.failing_items.discard("bad")
            h.queue.enqueue(make_task("bad"))
            await wait_until(lambda: ("recognition", "bad") in h.processed)
        finally:
            await h.shutdown()

    asyncio.run(main())


def test_stop_cancels_idle_workers():
    """stop() cancels workers parked in get(); all tasks finish and state resets."""

    async def main() -> None:
        h = QueueHarness(concurrency=2)
        h.queue.start()
        await asyncio.sleep(0.05)  # workers parked in get()
        tasks = h.queue.stop()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(t.done() for t in tasks)
        assert len(results) == len(tasks)
        assert h.queue.queue_size == 0
        assert not h.queue._pending_items

    asyncio.run(main())


def test_stop_during_active_task_drops_pending():
    """stop() while a task runs: worker task terminates, queued backlog is discarded."""

    async def main() -> None:
        h = QueueHarness(concurrency=1)
        h.queue.start()
        blocker_started, _release = h.add_blocker("blocker")
        h.queue.enqueue(make_task("blocker", priority_class=-1))
        await blocker_started.wait()
        h.queue.enqueue(make_task("queued-1"))
        h.queue.enqueue(make_task("queued-2"))
        assert h.queue.queue_size == 2

        tasks = h.queue.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert all(t.done() for t in tasks)
        assert h.queue.queue_size == 0
        assert not h.queue._pending_items
        assert ("recognition", "queued-1") not in h.processed
        assert ("recognition", "queued-2") not in h.processed

    asyncio.run(main())


def test_start_on_new_loop_resets_preexisting_queue_state():
    """Items enqueued before start() (different/none loop) are discarded by start()."""

    async def main(h: QueueHarness) -> None:
        h.queue.start()
        try:
            assert h.queue.queue_size == 0  # pre-start enqueue was discarded
            # Dedupe state was also reset: the same task can be enqueued again.
            h.queue.enqueue(make_task("early"))
            await wait_until(lambda: ("recognition", "early") in h.processed)
            assert len(h.processed) == 1
        finally:
            await h.shutdown()

    h = QueueHarness(concurrency=1)
    h.queue.enqueue(make_task("early"))  # enqueued before any loop/start
    assert h.queue.queue_size == 1
    asyncio.run(main(h))
