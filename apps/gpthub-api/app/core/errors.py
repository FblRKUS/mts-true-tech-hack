from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    details: Any = None
    status_code: int = 400

    def as_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}
