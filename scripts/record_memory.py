#!/usr/bin/env python3
"""Record a decision, experience or explicit preference without promoting it yet."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from common import resolve_vault
from memory_store import KINDS, LABELS, inside, now, validate, vault_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--key", help="stable topic name, e.g. 周报格式; corrections reuse this key")
    parser.add_argument("--scope", choices=("global", "project"), required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--result", default="")
    parser.add_argument("--conditions", default="")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--source", required=True, help="user statement or source file and line, without credentials")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    vault = resolve_vault(args.vault)
    if not (vault / "00-索引/AI启动卡.md").is_file():
        parser.error("请先建立记忆库")
    record = {"schema": 1, "id": uuid.uuid4().hex, "kind": args.kind, "key": args.key or args.summary,
              "summary": args.summary, "scope": args.scope, "project": args.project,
              "reason": args.reason, "result": args.result, "conditions": args.conditions,
              "agent": args.agent, "source": args.source, "recorded_at": now()}
    validate(record)
    path = inside(vault, "00-索引/待处理/" + record["id"] + ".json")
    if args.dry_run:
        print(json.dumps({"record": record, "pending_file": str(path), "write": False}, ensure_ascii=False))
        return 0
    with vault_lock(vault):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        fields = [record["recorded_at"], args.agent, args.project or "全局", LABELS[args.kind],
                  args.summary[:80], args.scope, record["id"]]
        row = " | ".join(value.replace("\n", " ").replace("|", "／") for value in fields) + "\n"
        inbox = inside(vault, "00-索引/收件箱.md")
        descriptor = os.open(str(inbox), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            f.write(row)
    print(json.dumps({"record_id": record["id"], "pending_file": str(path), "status": "pending_confirmation"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FileExistsError:
        print("整理或记录正在进行，请稍后重试；本次未宣称记录成功。", file=sys.stderr)
        sys.exit(75)
    except (OSError, ValueError) as exc:
        print("记录未完成：" + str(exc), file=sys.stderr)
        sys.exit(2)
