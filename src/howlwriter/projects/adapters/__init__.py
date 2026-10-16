"""Source adapters: one per format family, each returning located evidence.

Every adapter obeys the same contract:

* read the file, never modify it, never execute anything inside it;
* return evidence with an exact location (page, timestamp, frame range,
  image region) or return nothing -- never an invented location;
* report what it could not do (no text layer, no OCR engine, silent audio)
  as a limitation or an `unavailable` status, not as success;
* run locally. Nothing is uploaded; remote inference is a separate,
  explicitly authorized step the adapters do not take.

Adapters are imported lazily so a missing optional library (dpkt, ffmpeg,
an OCR engine, a speech model) affects only its own format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bump when an adapter's output changes meaning; cached results are redone.
ADAPTER_VERSION = 1


@dataclass
class AdapterResult:
    status: str = "extracted"  # extracted | partial | unavailable | failed
    reason: str = ""
    method: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)  # evidence fields (no ids yet)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    text: str = ""  # full extracted text, kept in memory for classification
