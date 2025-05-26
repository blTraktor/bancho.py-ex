#!/usr/bin/env python3.11
from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn

import app.logging
import app.settings
import app.utils
from app.discord.bot import bot
from app.api.init_api import asgi_app

app.logging.configure_logging()

shutdown_event = asyncio.Event()


async def start_uvicorn():
    config = uvicorn.Config(
        app=asgi_app,
        reload=app.settings.DEBUG,
        log_level=logging.WARNING,
        server_header=False,
        date_header=False,
        headers=[("bancho-version", app.settings.VERSION)],
        host=app.settings.APP_HOST,
        port=app.settings.APP_PORT,
    )
    server = uvicorn.Server(config)

    async def run_server():
        await server.serve()
        shutdown_event.set()

    return asyncio.create_task(run_server())


async def start_disnake():
    try:
        await bot.start(app.settings.DISCORD_BOT_TOKEN)
    except asyncio.CancelledError:
        await bot.close()


def setup_signal_handlers():
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)


async def main_async():
    app.utils.display_startup_dialog()
    setup_signal_handlers()

    disnake_task = asyncio.create_task(start_disnake())
    uvicorn_task = await start_uvicorn()

    await shutdown_event.wait()

    disnake_task.cancel()
    try:
        await disnake_task
    except asyncio.CancelledError:
        pass


def main() -> int:
    asyncio.run(main_async())
    return 0


if __name__ == "__main__":
    exit(main())
