#!/usr/bin/env python3.11
from __future__ import annotations

import argparse
import asyncio
import time
import math
import os
import sys
from collections.abc import Awaitable
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import TypeVar
from collections import deque

import databases
from akatsuki_pp_py import Beatmap
from akatsuki_pp_py import Calculator
from redis import asyncio as aioredis

sys.path.insert(0, os.path.abspath(os.pardir))
os.chdir(os.path.abspath(os.pardir))

try:
    import app.settings
    import app.state.services
    from app.constants.gamemodes import GameMode
    from app.constants.mods import Mods
    from app.constants.privileges import Privileges
    from app.objects.beatmap import ensure_osu_file_is_available
except ModuleNotFoundError:
    print("\x1b[;91mMust run from tools/ directory\x1b[m")
    raise

T = TypeVar("T")

debug_mode_enabled = True

DEBUG = True

BEATMAPS_PATH = Path.cwd() / ".data/osu"


@dataclass
class Context:
    database: databases.Database
    redis: aioredis.Redis
    beatmaps: dict[int, Beatmap] = field(default_factory=dict)
    rate_limiter: "RateLimiter | None" = None
    fetch_sem: asyncio.Semaphore | None = None


class RateLimiter:
    """Simple sliding-window rate limiter.

    Allows up to `limit` events per `window` seconds.
    """

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] > self.window:
                    self._times.popleft()
                if len(self._times) < self.limit:
                    self._times.append(now)
                    return
                sleep_for = self.window - (now - self._times[0])
            await asyncio.sleep(max(sleep_for, 0.01))


def divide_chunks(values: list[T], n: int) -> Iterator[list[T]]:
    for i in range(0, len(values), n):
        yield values[i : i + n]

async def recalculate_score(
    score: dict[str, Any],
    beatmap_path: Path,
    ctx: Context,
) -> None:
    try:
        beatmap = ctx.beatmaps.get(score["map_id"])
        if beatmap is None:
            beatmap = Beatmap(path=str(beatmap_path))
            ctx.beatmaps[score["map_id"]] = beatmap

        calculator = Calculator(
            mode=GameMode(score["mode"]).as_vanilla,
            mods=score["mods"],
            combo=score["max_combo"],
            n_geki=score["ngeki"],  # Mania 320s
            n300=score["n300"],
            n_katu=score["nkatu"],  # Mania 200s, Catch tiny droplets
            n100=score["n100"],
            n50=score["n50"],
            n_misses=score["nmiss"],
        )
        attrs = calculator.performance(beatmap)

        new_pp: float = attrs.pp
        if math.isnan(new_pp) or math.isinf(new_pp):
            new_pp = 0.0

        await ctx.database.execute(
            "UPDATE scores SET pp = :new_pp WHERE id = :id",
            {"new_pp": new_pp, "id": score["id"]},
        )

        if debug_mode_enabled:
            print(
                f"Recalculated score ID {score['id']} ({score['pp']:.3f}pp -> {new_pp:.3f}pp)",
            )
            
    except Exception as e:
        # Log the error and continue processing other scores
        print(f"Failed to recalculate score ID {score['id']}: {e}")


async def process_score_chunk(
    chunk: list[dict[str, Any]],
    ctx: Context,
) -> None:
    tasks: list[Awaitable[None]] = []
    for score in chunk:
        osu_file_available = await ensure_osu_file_is_available(
            score["map_id"],
            expected_md5=score["map_md5"],
        )
        if osu_file_available:
            tasks.append(
                recalculate_score(
                    score,
                    BEATMAPS_PATH / f"{score['map_id']}.osu",
                    ctx,
                ),
            )

    await asyncio.gather(*tasks)


async def recalculate_user(
    id: int,
    game_mode: GameMode,
    ctx: Context,
) -> None:
    best_scores = await ctx.database.fetch_all(
        "SELECT s.pp, s.acc FROM scores s "
        "INNER JOIN maps m ON s.map_md5 = m.md5 "
        "WHERE s.userid = :user_id AND s.mode = :mode "
        "AND s.status = 2 AND m.status IN (2, 3) "  # ranked, approved
        "ORDER BY s.pp DESC",
        {"user_id": id, "mode": game_mode},
    )

    total_scores = len(best_scores)
    if not total_scores:
        return

    # calculate new total weighted accuracy
    weighted_acc = sum(row["acc"] * 0.95**i for i, row in enumerate(best_scores))
    bonus_acc = 100.0 / (20 * (1 - 0.95**total_scores))
    acc = (weighted_acc * bonus_acc) / 100

    # calculate new total weighted pp
    weighted_pp = sum(row["pp"] * 0.95**i for i, row in enumerate(best_scores))
    bonus_pp = 416.6667 * (1 - 0.9994**total_scores)
    pp = round(weighted_pp + bonus_pp)

    await ctx.database.execute(
        "UPDATE stats SET pp = :pp, acc = :acc WHERE id = :id AND mode = :mode",
        {"pp": pp, "acc": acc, "id": id, "mode": game_mode},
    )

    user_info = await ctx.database.fetch_one(
        "SELECT country, priv FROM users WHERE id = :id",
        {"id": id},
    )
    if user_info is None:
        raise Exception(f"Unknown user ID {id}?")

    if user_info["priv"] & Privileges.UNRESTRICTED:
        await ctx.redis.zadd(
            f"bancho:leaderboard:{game_mode.value}",
            {str(id): pp},
        )

        await ctx.redis.zadd(
            f"bancho:leaderboard:{game_mode.value}:{user_info['country']}",
            {str(id): pp},
        )
        
    if debug_mode_enabled:
        print(f"Recalculated user ID {id} ({pp:.3f}pp, {acc:.3f}%)")

async def process_user_chunk(
    chunk: list[int],
    game_mode: GameMode,
    ctx: Context,
) -> None:
    tasks: list[Awaitable[None]] = []
    for id in chunk:
        tasks.append(recalculate_user(id, game_mode, ctx))

    await asyncio.gather(*tasks)


async def recalculate_mode_users(mode: GameMode, ctx: Context) -> None:
    user_ids = [
        row["id"] for row in await ctx.database.fetch_all("SELECT id FROM users")
    ]

    for id_chunk in divide_chunks(user_ids, 100):
        await process_user_chunk(id_chunk, mode, ctx)


async def recalculate_mode_scores(mode: GameMode, ctx: Context) -> None:
    scores = [
        dict(row)
        for row in await ctx.database.fetch_all(
            """\
            SELECT scores.id, scores.mode, scores.mods, scores.map_md5,
              scores.pp, scores.acc, scores.max_combo,
              scores.ngeki, scores.n300, scores.nkatu, scores.n100, scores.n50, scores.nmiss,
              maps.id as `map_id`
            FROM scores
            INNER JOIN maps ON scores.map_md5 = maps.md5
            WHERE scores.status = 2
              AND scores.mode = :mode
            ORDER BY scores.pp DESC
            """,
            {"mode": mode},
        )
    ]

    for score_chunk in divide_chunks(scores, 100):
        await process_score_chunk(score_chunk, ctx)


async def _calc_map_pp100(map_row: dict[str, Any], ctx: Context) -> None:
    map_id = map_row["id"]
    try:
        assert ctx.fetch_sem is not None
        assert ctx.rate_limiter is not None

        
        async with ctx.fetch_sem:
            await ctx.rate_limiter.acquire()
            ok = await ensure_osu_file_is_available(map_id, expected_md5=map_row["md5"])
        if not ok:
            async with ctx.fetch_sem:
                await ctx.rate_limiter.acquire()
                ok = await ensure_osu_file_is_available(map_id)
        if not ok:
            print(f"Skipped map {map_id} (osu file not available)")
            return

        beatmap = ctx.beatmaps.get(map_row["id"])
        if beatmap is None:
            beatmap = Beatmap(path=str(BEATMAPS_PATH / f"{map_row['id']}.osu"))
            ctx.beatmaps[map_row["id"]] = beatmap

        calc = Calculator(mode=GameMode(map_row["mode"]).as_vanilla, mods=0)
        calc.set_acc(100.0)
        perf = calc.performance(beatmap)
        pp100 = perf.pp
        if math.isnan(pp100) or math.isinf(pp100):
            pp100 = 0.0

        await ctx.database.execute(
            "UPDATE maps SET pp100 = :pp100 WHERE id = :id",
            {"pp100": pp100, "id": map_row["id"]},
        )

        if debug_mode_enabled:
            print(f"Map {map_row['id']} pp100 = {pp100:.3f}")
    except Exception as e:
        print(f"Failed pp100 for map {map_row['id']}: {e}")


async def recalculate_all_maps_pp(ctx: Context) -> None:
    query = """
        SELECT id, md5, mode 
        FROM maps 
        WHERE pp100 IS NULL
    """
    
    rows = [dict(row) for row in await ctx.database.fetch_all(query)]
    total_maps = len(rows)
    
    if not total_maps:
        print("All maps already have pp100 calculated!")
        return

    print(f"Found {total_maps} maps without pp100 calculation")
    
    if ctx.rate_limiter is None:
        ctx.rate_limiter = RateLimiter(limit=20, window=60.0)
    if ctx.fetch_sem is None:
        ctx.fetch_sem = asyncio.Semaphore(10)

    chunk_size = 1
    processed = 0

    print("\n" + "="*50)
    print(f"Processing {total_maps} maps...")
    print("="*50 + "\n")

    bar_length = 40
    start_time = time.time()
    
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]

        results = await asyncio.gather(
            *(_calc_map_pp100(r, ctx) for r in chunk),
            return_exceptions=True
        )
        
        processed += len(chunk)
        progress = min(processed, total_maps)
        percent = (progress / total_maps) * 100

        elapsed = time.time() - start_time
        if progress > 0:
            remaining = (elapsed / progress) * (total_maps - progress)
            eta = f"ETA: {int(remaining // 60)}m {int(remaining % 60)}s"
        else:
            eta = "Calculating..."

        filled_length = int(bar_length * progress // total_maps)
        bar = '█' * filled_length + ' ' * (bar_length - filled_length)

        current_map = chunk[0]['id'] if chunk and len(chunk) > 0 else '?'
        status_line = f"Processing map {current_map}... [{bar}] {percent:.1f}% ({progress}/{total_maps}) | {eta}"
        print('\033[K', end='\r')
        print(status_line, end='\r', flush=True)
    

    total_time = time.time() - start_time
    print(f"\n\nCompleted processing {total_maps} maps in {total_time//60:.0f}m {total_time%60:.1f}s")
    print(f"Average speed: {total_maps/total_time:.2f} maps/second")
    print("Done!")


async def main(argv: Sequence[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Recalculate performance for scores and/or stats",
    )

    parser.add_argument(
        "-d",
        "--debug",
        help="Enable debug logging",
        action="store_true",
    )
    parser.add_argument(
        "--no-scores",
        help="Disable recalculating scores",
        action="store_true",
    )
    parser.add_argument(
        "--no-stats",
        help="Disable recalculating user stats",
        action="store_true",
    )

    parser.add_argument(
        "-m",
        "--mode",
        nargs=argparse.ONE_OR_MORE,
        required=False,
        default=["0", "1", "2", "3", "4", "5", "6", "8"],
        # would love to do things like "vn!std", but "!" will break interpretation
        choices=["0", "1", "2", "3", "4", "5", "6", "8"],
    )
    parser.add_argument(
        "--maps-pp",
        help="Calculate and store 100% NM pp for all maps into maps.pp100",
        action="store_true",
    )
    args = parser.parse_args(argv)

    global debug_mode_enabled
    debug_mode_enabled = args.debug

    db = databases.Database(app.settings.DB_DSN)
    await db.connect()

    redis = await aioredis.from_url(app.settings.REDIS_DSN)  # type: ignore[no-untyped-call]

    ctx = Context(db, redis)

    if args.maps_pp:
        await recalculate_all_maps_pp(ctx)

    for mode in args.mode:
        mode = GameMode(int(mode))

        if not args.no_scores:
            await recalculate_mode_scores(mode, ctx)

        if not args.no_stats:
            await recalculate_mode_users(mode, ctx)

    await app.state.services.http_client.aclose()
    await db.disconnect()
    await redis.aclose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
