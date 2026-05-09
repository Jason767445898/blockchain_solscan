from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PumpClassification:
    category: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    program_ids: list[str] = field(default_factory=list)
    sol_change: float | None = None
    token_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MonitoredTransaction:
    signature: str
    block_time: int | None
    slot: int | None
    status: str | None
    fee: int | None
    signer: list[str]
    source: str | None
    raw: dict[str, Any]
    classification: PumpClassification

    def to_record(self, wallet: str) -> dict[str, Any]:
        return {
            "wallet": wallet,
            "signature": self.signature,
            "block_time": self.block_time,
            "slot": self.slot,
            "status": self.status,
            "fee": self.fee,
            "signer": self.signer,
            "source": self.source,
            "category": self.classification.category,
            "confidence": self.classification.confidence,
            "reasons": self.classification.reasons,
            "program_ids": self.classification.program_ids,
            "sol_change": self.classification.sol_change,
            "token_changes": self.classification.token_changes,
        }
