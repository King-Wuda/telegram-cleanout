#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Leave Telegram groups and optionally supergroups."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually leave groups (default is dry-run).",
    )
    parser.add_argument(
        "--include-supergroups",
        action="store_true",
        dest="include_supergroups",
        help="Also include supergroups/megagroups (default: regular groups only).",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        metavar="NAME",
        default=[],
        help="Exclude by display name or username (case-insensitive).",
    )
    parser.add_argument(
        "--exclude-id",
        nargs="+",
        metavar="ID",
        type=int,
        default=[],
        dest="exclude_ids",
        help="Exclude by Telegram group ID.",
    )
    return parser.parse_args()


def load_credentials() -> tuple[int, str, str]:
    api_id_raw = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")
    if not api_id_raw or not api_hash or not phone:
        log.error("Missing credentials. Copy .env.example to .env and fill in values.")
        sys.exit(1)
    return int(api_id_raw), api_hash, phone


async def collect_groups(
    client: TelegramClient,
    include_supergroups: bool,
    exclude_names: list[str],
    exclude_ids: list[int],
) -> list:
    exclude_lower = [n.lower().lstrip("@") for n in exclude_names]
    groups = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        is_supergroup = dialog.is_channel and getattr(entity, "megagroup", False)
        is_regular_group = dialog.is_group and not dialog.is_channel

        if is_supergroup:
            if not include_supergroups:
                continue
        elif not is_regular_group:
            continue

        if entity.id in exclude_ids:
            log.info("Skipping (excluded by ID): %s", dialog.name)
            continue
        name_lower = (dialog.name or "").lower()
        username_lower = (getattr(entity, "username", None) or "").lower()
        if name_lower in exclude_lower or (username_lower and username_lower in exclude_lower):
            log.info("Skipping (excluded by name/username): %s", dialog.name)
            continue

        groups.append(dialog)
    return groups


def print_group_list(groups: list) -> None:
    print(f"\nGroups found: {len(groups)}\n")
    for i, dialog in enumerate(groups, 1):
        entity = dialog.entity
        username = f"@{entity.username}" if getattr(entity, "username", None) else "—"
        kind = "supergroup" if getattr(entity, "megagroup", False) else "group"
        last = dialog.date.strftime("%Y-%m-%d") if dialog.date else "unknown"
        print(f"  {i:>3}. {dialog.name:<35} {username:<25} [{kind}]  ID={entity.id}  last={last}")
    print()


async def leave_groups(client: TelegramClient, groups: list) -> None:
    total = len(groups)
    deleted = 0
    failed = 0

    for i, dialog in enumerate(groups, 1):
        name = dialog.name
        try:
            await client.delete_dialog(dialog.entity)
            print(f"[{i}/{total}] Left: {name}")
            deleted += 1
        except FloodWaitError as e:
            log.warning("Flood wait — sleeping %d s", e.seconds)
            await asyncio.sleep(e.seconds)
            try:
                await client.delete_dialog(dialog.entity)
                print(f"[{i}/{total}] Left (after wait): {name}")
                deleted += 1
            except Exception as retry_err:
                print(f"[{i}/{total}] FAILED: {name} — {retry_err}")
                failed += 1
        except Exception as err:
            print(f"[{i}/{total}] FAILED: {name} — {err}")
            failed += 1

        await asyncio.sleep(0.5)

    skipped = total - deleted - failed
    print(f"\nSummary: {deleted} left, {failed} failed, {skipped} skipped.")


async def main() -> None:
    args = build_args()
    api_id, api_hash, phone = load_credentials()

    async with TelegramClient("telegram_cleanup", api_id, api_hash) as client:
        await client.start(phone=phone)
        me = await client.get_me()
        log.info("Signed in as %s (id=%d)", me.first_name, me.id)

        groups = await collect_groups(
            client, args.include_supergroups, args.exclude, args.exclude_ids
        )

        if not args.execute:
            print("DRY RUN — no groups will be left. Pass --execute to proceed.")
            print_group_list(groups)
            print("Re-run with --execute to proceed.")
            return

        print_group_list(groups)

        if not groups:
            print("Nothing to leave.")
            return

        answer = input(f"Type DELETE to confirm leaving {len(groups)} groups: ")
        if answer.strip() != "DELETE":
            print("Aborted.")
            return

        await leave_groups(client, groups)


if __name__ == "__main__":
    asyncio.run(main())
