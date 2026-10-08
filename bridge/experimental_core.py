"""Opt-in RustyBox-inspired transfer boundary.

This module is intentionally not imported by the production HTTP bridge.
It trials plan-first operations, serialized execution, resumable partial names,
and an explicit recovery hold without adding threads to console handling.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Optional


class CorePhase(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class TransferPlan:
    """Validated write plan. No adapter call happens during construction."""

    operation: str
    source: str
    destination: str
    total_bytes: int
    overwrite: bool = False
    partial_name: Optional[str] = None
    steps: tuple[str, ...] = ("stage", "send", "verify", "finalize")

    def validate(self) -> None:
        if not self.operation or not self.source or not self.destination:
            raise ValueError("operation, source and destination are required")
        if any("\x00" in value for value in (self.operation, self.source, self.destination)):
            raise ValueError("paths and operation names cannot contain NUL")
        if self.total_bytes < 0:
            raise ValueError("total_bytes cannot be negative")
        if self.overwrite:
            raise ValueError("experimental core keeps overwrite disabled")
        if self.partial_name and "\x00" in self.partial_name:
            raise ValueError("partial_name cannot contain NUL")

    @property
    def partial(self) -> str:
        return self.partial_name or f"{self.destination}.part"


@dataclass(frozen=True)
class FailureRecord:
    code: str
    phase: str
    message: str
    offset: int = 0
    hresult: Optional[str] = None
    uncertain: bool = True

    def public(self) -> dict:
        """Return allowlisted evidence; never expose an exception object."""
        return {
            "code": self.code,
            "phase": self.phase,
            "message": self.message,
            "offset": self.offset,
            "hresult": self.hresult,
            "uncertain": self.uncertain,
        }


class RecoveryRequired(RuntimeError):
    def __init__(self, failure: FailureRecord):
        super().__init__("Recovery confirmation required before another console operation")
        self.failure = failure


class CoreAdapterError(RuntimeError):
    """Adapter may raise this when remote completion is unknown."""

    def __init__(self, code: str, phase: str, message: str, *, offset: int = 0,
                 hresult: Optional[str] = None, uncertain: bool = True):
        super().__init__(message)
        self.record = FailureRecord(code, phase, message, offset, hresult, uncertain)


@dataclass
class CoreJob:
    id: int
    plan: TransferPlan
    phase: CorePhase = CorePhase.QUEUED
    cancel_requested: bool = False
    failure: Optional[FailureRecord] = None


@dataclass(frozen=True)
class CoreResult:
    job_id: int
    phase: CorePhase
    destination: str
    partial: str
    failure: Optional[FailureRecord] = None

    def public(self) -> dict:
        return {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "destination": self.destination,
            "partial": self.partial,
            "failure": self.failure.public() if self.failure else None,
        }


Adapter = Callable[[TransferPlan, Callable[[], bool]], object]


class ExperimentalTransferCore:
    """Single-caller, FIFO transfer core for controlled adapter trials.

    No background worker exists. Caller invokes ``run_next`` or ``drain``.
    This keeps console calls serialized and makes request ordering testable.
    """

    def __init__(self, adapter: Optional[Adapter] = None):
        self.adapter = adapter or (lambda _plan, _cancelled: None)
        self._queue: Deque[CoreJob] = deque()
        self._next_id = 1
        self.current: Optional[CoreJob] = None
        self.hold: Optional[FailureRecord] = None
        self.history: list[CoreResult] = []

    def submit(self, plan: TransferPlan) -> int:
        plan.validate()
        if self.hold:
            raise RecoveryRequired(self.hold)
        job = CoreJob(self._next_id, plan)
        self._next_id += 1
        self._queue.append(job)
        return job.id

    def cancel(self, job_id: int) -> bool:
        for job in self._queue:
            if job.id == job_id:
                job.cancel_requested = True
                return True
        if self.current and self.current.id == job_id:
            self.current.cancel_requested = True
            return True
        return False

    def run_next(self) -> Optional[CoreResult]:
        if self.hold:
            raise RecoveryRequired(self.hold)
        if self.current is not None:
            raise RuntimeError("core already has an active job")
        if not self._queue:
            return None
        job = self._queue.popleft()
        self.current = job
        if job.cancel_requested:
            result = CoreResult(job.id, CorePhase.CANCELLED, job.plan.destination, job.plan.partial)
            job.phase = CorePhase.CANCELLED
            self.current = None
            self.history.append(result)
            return result
        job.phase = CorePhase.RUNNING
        try:
            self.adapter(job.plan, lambda: job.cancel_requested)
            job.phase = CorePhase.CANCELLED if job.cancel_requested else CorePhase.SUCCEEDED
            result = CoreResult(job.id, job.phase, job.plan.destination, job.plan.partial)
        except CoreAdapterError as error:
            job.failure = error.record
            job.phase = CorePhase.RECOVERY_REQUIRED if error.record.uncertain else CorePhase.FAILED
            if error.record.uncertain:
                self.hold = error.record
            result = CoreResult(job.id, job.phase, job.plan.destination, job.plan.partial, error.record)
        except Exception as error:
            # Unknown adapter exceptions are unsafe: remote completion is unknown.
            # Do not copy raw COM/process text into the public failure record.
            failure = FailureRecord("ADAPTER_EXCEPTION", "adapter", "Adapter stopped; remote completion is unknown", uncertain=True)
            job.failure = failure
            job.phase = CorePhase.RECOVERY_REQUIRED
            self.hold = failure
            result = CoreResult(job.id, job.phase, job.plan.destination, job.plan.partial, failure)
        finally:
            self.current = None
        self.history.append(result)
        return result

    def drain(self) -> list[CoreResult]:
        results = []
        while self._queue and not self.hold:
            result = self.run_next()
            if result is not None:
                results.append(result)
        return results

    def recover(self, confirmed: bool) -> None:
        if not self.hold:
            return
        if confirmed is not True:
            raise RecoveryRequired(self.hold)
        self.hold = None

    def status(self) -> dict:
        return {
            "phase": self.current.phase.value if self.current else (CorePhase.RECOVERY_REQUIRED.value if self.hold else CorePhase.IDLE.value),
            "queued": [job.id for job in self._queue],
            "current": self.current.id if self.current else None,
            "recovery_required": self.hold is not None,
            "failure": self.hold.public() if self.hold else None,
        }
