"""Real host/process telemetry. Values come from the OS; nothing is synthesized."""

import os
import platform
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from . import __version__
from .auth import Principal, current_principal

_started = time.monotonic()
router = APIRouter(prefix="/api/v1/system", tags=["system"])


class SystemInfo(BaseModel):
    version: str
    python: str
    platform: str
    uptime_seconds: float
    cpu_count: int
    load_average: tuple[float, float, float] | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    process_rss_bytes: int | None


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return out


def _rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def collect() -> SystemInfo:
    mem = _meminfo()
    try:
        load: tuple[float, float, float] | None = os.getloadavg()
    except OSError:
        load = None
    return SystemInfo(
        version=__version__,
        python=platform.python_version(),
        platform=platform.platform(),
        uptime_seconds=round(time.monotonic() - _started, 1),
        cpu_count=os.cpu_count() or 1,
        load_average=load,
        memory_total_bytes=mem.get("MemTotal"),
        memory_available_bytes=mem.get("MemAvailable"),
        process_rss_bytes=_rss(),
    )


@router.get("", response_model=SystemInfo)
def system_info(_: Annotated[Principal, Depends(current_principal)]) -> SystemInfo:
    return collect()
