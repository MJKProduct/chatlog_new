from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessOutcomeKind(str, Enum):
    PROCESSED = "processed"
    NO_WORK = "no_work"
    OWNERSHIP_LOST = "ownership_lost"
    EXECUTOR_ERROR = "executor_error"


@dataclass
class ProcessOutcome:
    kind: ProcessOutcomeKind
    detail: str = ""

    @property
    def counts_as_processed(self) -> bool:
        return self.kind == ProcessOutcomeKind.PROCESSED
