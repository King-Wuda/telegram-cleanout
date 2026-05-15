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
        description="Delete personal 1-on-1 Telegram chats."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete chats (default is dry-run).",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Delete messages from both sides (default: one-sided only).",
    )
    parser.add_argument(
        "--include-bots",
        action="store_true",
        dest="include_bots",
        help="Include bot chats in deletion (default: skip bots).",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        metavar="NAME",
        default=[],
        help="Exclude chats by display name (case-insensitive). e.g. --exclude \"John Smith\" \"Jane\"",
    )
    parser.add_argument(
        "--exclude-id",
        nargs="+",
        metavar="ID",
        type=int,
        default=[],
        dest="exclude_ids",
        help="Exclude chats by Telegram user ID. e.g. --exclude-id 123456789",
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


async def collect_personal_chats(
    client: TelegramClient,
    own_id: int,
    include_bots: bool,
    exclude_names: list[str],
    exclude_ids: list[int],
) -> list:
    exclude_names_lower = [n.lower() for n in exclude_names]
    chats = []
    async for dialog in client.iter_dialogs():
        if not dialog.is_user:
            continue
        entity = dialog.entity
        if entity.id == own_id:
            continue
        if entity.bot and not include_bots:
            continue
        if entity.id in exclude_ids:
            log.info("Skipping (excluded by ID): %s", dialog.name)
            continue
        if dialog.name and dialog.name.lower() in exclude_names_lower:
            log.info("Skipping (excluded by name): %s", dialog.name)
            continue
        entity_username = (getattr(entity, "username", None) or "").lower()
        if entity_username and entity_username in exclude_names_lower:
            log.info("Skipping (excluded by username): %s", dialog.name)
            continue
        chats.append(dialog)
    return chats


def print_chat_list(chats: list) -> None:
    print(f"\nPersonal chats found: {len(chats)}\n")
    for i, dialog in enumerate(chats, 1):
        entity = dialog.entity
        username = f"@{entity.username}" if getattr(entity, "username", None) else "—"
        last = dialog.date.strftime("%Y-%m-%d") if dialog.date else "unknown"
        print(f"  {i:>3}. {dialog.name:<35} {username:<25} ID={entity.id}  last={last}")
    print()


async def delete_chats(client: TelegramClient, chats: list, revoke: bool) -> None:
    total = len(chats)
    deleted = 0
    failed = 0

    for i, dialog in enumerate(chats, 1):
        name = dialog.name
        try:
            await client.delete_dialog(dialog.entity, revoke=revoke)
            print(f"[{i}/{total}] Deleted: {name}")
            deleted += 1
        except FloodWaitError as e:
            log.warning("Flood wait — sleeping %d s", e.seconds)
            await asyncio.sleep(e.seconds)
            try:
                await client.delete_dialog(dialog.entity, revoke=revoke)
                print(f"[{i}/{total}] Deleted (after wait): {name}")
                deleted += 1
            except Exception as retry_err:
                print(f"[{i}/{total}] FAILED: {name} — {retry_err}")
                failed += 1
        except Exception as err:
            print(f"[{i}/{total}] FAILED: {name} — {err}")
            failed += 1

        await asyncio.sleep(0.5)

    skipped = total - deleted - failed
    print(f"\nSummary: {deleted} deleted, {failed} failed, {skipped} skipped.")


async def main() -> None:
    args = build_args()
    api_id, api_hash, phone = load_credentials()

    async with TelegramClient("telegram_cleanup", api_id, api_hash) as client:
        await client.start(phone=phone)
        me = await client.get_me()
        own_id = me.id
        log.info("Signed in as %s (id=%d)", me.first_name, own_id)

        chats = await collect_personal_chats(
            client, own_id, args.include_bots, args.exclude, args.exclude_ids
        )

        if not args.execute:
            print("DRY RUN — no chats will be deleted. Pass --execute to delete.")
            print_chat_list(chats)
            print("Re-run with --execute to proceed.")
            return

        print_chat_list(chats)

        if not chats:
            print("Nothing to delete.")
            return

        revoke_note = "both sides" if args.revoke else "your side only"
        answer = input(f"Type DELETE to confirm deletion of {len(chats)} chats ({revoke_note}): ")
        if answer.strip() != "DELETE":
            print("Aborted.")
            return

        await delete_chats(client, chats, revoke=args.revoke)


if __name__ == "__main__":
    asyncio.run(main())
