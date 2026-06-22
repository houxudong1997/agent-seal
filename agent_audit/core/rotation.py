"""Log rotation — size-based, time-based, hybrid."""

import datetime
import gzip
import logging
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class RotationStrategy(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    SIZE_10MB = "10mb"
    SIZE_100MB = "100mb"
    HYBRID = "hybrid"


@dataclass
class RotationResult:
    rotated: bool
    archived_files: list[str]
    reason: str


class LogRotator:
    def __init__(self, log_dir: str | Path, strategy: RotationStrategy = RotationStrategy.HYBRID):
        self.dir = Path(log_dir)
        self.strategy = strategy
        self.archive = self.dir / "archive"
        self.archive.mkdir(parents=True, exist_ok=True)
        self._last_day = int(time.time() / 86400)

    def check(self) -> RotationResult:
        rotated = []
        today = int(time.time() / 86400)

        # Time-based
        if (
            self.strategy
            in (RotationStrategy.DAILY, RotationStrategy.WEEKLY, RotationStrategy.HYBRID)
            and today != self._last_day
            and (
                self.strategy != RotationStrategy.WEEKLY
                or datetime.date.today().weekday() == 0
            )
        ):
                    logger.info(
                        "Rotation triggered: strategy=%s day=%d prev_day=%d",
                        self.strategy.value,
                        today,
                        self._last_day,
                    )
                    rotated = self._rotate()
                    self._last_day = today

        # Size-based
        if not rotated and self.strategy in (
            RotationStrategy.SIZE_10MB,
            RotationStrategy.SIZE_100MB,
            RotationStrategy.HYBRID,
        ):
            limit = 10_485_760 if self.strategy == RotationStrategy.SIZE_10MB else 104_857_600
            size = sum(
                (f.stat().st_size for f in self.dir.glob("*.jsonl") if f.name != "active.jsonl"), 0
            )
            if size > limit:
                logger.info(
                    "Rotation triggered: size=%d bytes exceeds limit=%d strategy=%s",
                    size,
                    limit,
                    self.strategy.value,
                )
                rotated = self._rotate()

        result = RotationResult(
            bool(rotated), rotated, f"{len(rotated)} files rotated" if rotated else "OK"
        )
        logger.debug(
            "Rotation check: strategy=%s rotated=%d result=%s",
            self.strategy.value,
            len(rotated),
            result.reason,
        )
        return result

    def _rotate(self) -> list[str]:
        ts = time.strftime("%Y%m%d-%H%M")
        result = []
        for f in sorted(self.dir.glob("*.jsonl")):
            if f.name == "active.jsonl":
                continue
            dest = self.archive / f"{f.stem}-{ts}.jsonl.gz"
            with open(f, "rb") as src, gzip.open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            f.unlink()
            result.append(str(dest))
            logger.debug("Rotated: %s -> %s", f.name, dest.name)
        logger.info("Rotation complete: %d files archived", len(result))
        return result

    def cleanup(self, keep_days: int = 90) -> int:
        cutoff = time.time() - keep_days * 86400
        n = 0
        for f in self.archive.glob("*.gz"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        if n > 0:
            logger.info(
                "Rotation cleanup: removed %d archived files older than %d days",
                n,
                keep_days,
            )
        return n
