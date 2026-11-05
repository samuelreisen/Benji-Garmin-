"""Daily job: sync Garmin then write the morning briefing."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.service import Service

log = logging.getLogger("benji.scheduler")


def seconds_until(now: datetime, hour: int) -> float:
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def daily_briefing_loop(service: Service) -> None:
    while True:
        await asyncio.sleep(seconds_until(datetime.now(service.tz), service.settings.briefing_hour))
        try:
            await asyncio.to_thread(service.sync)
            await asyncio.to_thread(service.briefing, True)
            log.info("daily briefing ready")
        except Exception as exc:  # never let one bad morning kill the loop
            log.warning("daily briefing failed: %s", type(exc).__name__)
