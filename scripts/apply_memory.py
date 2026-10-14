#!/usr/bin/env python3
"""Apply a user-confirmed record to its project/preferences and startup card."""
import argparse
import json
import re
import sys

from common import resolve_vault
from memory_store import atomic_write, inside, plan_apply, vault_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", help="record ID from record_memory.py")
    mode.add_argument("--refresh", action="store_true", help="regenerate managed views from already confirmed records after a review")
    parser.add_argument("--confirmed", action="store_true", help="only when user authorization covers this exact record")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.record and not re.fullmatch(r"[a-f0-9]{32}", args.record):
        parser.error("记录 ID 不正确")
    if args.record and not args.confirmed and not args.dry_run:
        parser.error("尚未确认；先预览，确认后再写入正式记忆")
    vault = resolve_vault(args.vault)
    if not (vault / "00-索引/AI启动卡.md").is_file():
        parser.error("请先建立记忆库")
    record = None
    if args.record:
        pending = inside(vault, "00-索引/待处理/" + args.record + ".json")
        record = json.loads(pending.read_text(encoding="utf-8"))
        if record.get("id") != args.record:
            parser.error("记录 ID 与文件内容不一致")
    if args.dry_run:
        updates, _ = plan_apply(vault, record)
        print(json.dumps({"record_id": args.record, "write": False, "files": [str(p) for p in updates]}, ensure_ascii=False))
        return 0
    with vault_lock(vault):
        updates, state = plan_apply(vault, record)
        for path, text in updates.items():
            atomic_write(path, text)
        # State is committed last. Repeating interrupted writes regenerates managed blocks safely.
        if updates:
            atomic_write(inside(vault, "00-索引/.已确认记录.json"), json.dumps(state, ensure_ascii=False, indent=2))
    print(json.dumps({"record_id": args.record, "status": "applied" if updates else "already_applied",
                      "files": [str(p) for p in updates]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileExistsError:
        print("已有整理或记录任务在执行，请稍后重试。", file=sys.stderr)
        sys.exit(75)
    except (OSError, ValueError) as exc:
        print("正式记忆未完成更新：" + str(exc) + "；保留待处理记录，修复后可重跑。", file=sys.stderr)
        sys.exit(2)
