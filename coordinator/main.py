"""Pipeline Coordinator entry point."""

from __future__ import annotations

import asyncio
import signal

from quantum_edge.core.pipeline_coordinator import PipelineCoordinator
from quantum_edge.utils.logging import setup_logging


async def main() -> None:
    setup_logging()
    coordinator = PipelineCoordinator()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(coordinator.stop()))

    await coordinator.start()


if __name__ == "__main__":
    asyncio.run(main())
