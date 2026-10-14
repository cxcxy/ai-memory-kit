#!/usr/bin/env python3
"""Connect an AI agent to the memory vault, or disconnect it.

Connecting does two things:
  1. entry: add a marked block to the agent's user-level rules file, so it
     reads the startup card at the start of every session ("use").
  2. skill: symlink <vault>/.kit/ai-memory-kit into the agent's skills folder,
     so it knows how to record, organize and check the vault ("maintain").

Reruns update in place. Entry files are backed up before every write.
Symlinked entry files are refused unless --follow-symlink is given, because
editing the link target changes every tool that shares it. An existing skill
folder that is not our own link is never replaced.
Standard library only; works with Python 3.8+.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AGENTS, KIT_SUBDIR, SKILL_NAME, display_path, expand, resolve_vault, skill_linked  # noqa: E402

SNIPPET = Path(__file__).resolve().parent.parent / "assets" / "entry-snippet.md"
START = "<!-- ai-memory-kit:start -->"
END = "<!-- ai-memory-kit:end -->"
OWNER = ".ai-memory-kit-owner.json"


def owned_copy(path: Path, vault: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        data = json.loads((path / OWNER).read_text(encoding="utf-8"))
        return data.get("schema") == 1 and data.get("mode") == "copy" and expand(data["vault"]) == vault.resolve()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def matching_bootstrap(path: Path, kit: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    required = ["SKILL.md", "scripts/common.py", "scripts/connect_agent.py", "scripts/init_vault.py"]
    try:
        return all((path / name).read_bytes() == (kit / name).read_bytes() for name in required)
    except OSError:
        return False


def backup_location(skills_dir: Path) -> Path:
    return skills_dir.parent / "ai-memory-kit-backups" / (SKILL_NAME + "-" + str(time.time_ns()))


def strip_block(text: str) -> str:
    if START not in text and END not in text:
        return text
    if text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
        raise ValueError("记忆库标记区块不完整或重复，请先人工核对")
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    return head.rstrip("\n") + ("\n" if head.strip() else "") + tail.lstrip("\n")


def update_entry(entry: Path, vault: Path, remove: bool, dry: bool, follow: bool) -> int:
    if entry.is_symlink():
        real = entry.resolve()
        if not follow:
            print(f"入口：停止。{entry} 是指向 {real} 的软链接，修改会影响所有共用它的工具。"
                  f"确认后加 --follow-symlink 重试。", file=sys.stderr)
            return 2
        entry = real
    old = entry.read_text(encoding="utf-8") if entry.exists() else ""
    try:
        base = strip_block(old)
    except ValueError as exc:
        print(f"入口：停止。{entry}：{exc}", file=sys.stderr)
        return 2
    if remove:
        new = base
    else:
        block = SNIPPET.read_text(encoding="utf-8").replace("{{VAULT}}", display_path(vault)).strip()
        new = (base.rstrip("\n") + "\n\n" if base.strip() else "") + f"{START}\n{block}\n{END}\n"
    if new == old:
        print(f"入口：无需修改 {entry}")
        return 0
    if dry:
        print(f"入口：将{'移除本工具区块' if remove else '增补本工具区块，保留其他规则'} {entry}")
        if not remove:
            print(block)
        return 0
    entry.parent.mkdir(parents=True, exist_ok=True)
    if entry.exists():
        backup = entry.with_name(entry.name + time.strftime(".bak-%Y%m%d%H%M%S-") + str(time.time_ns()))
        shutil.copy2(entry, backup)
        print(f"入口：已备份原文件 {backup}")
    entry.write_text(new, encoding="utf-8")
    print(f"入口：已{'移除' if remove else '写入'} {entry}")
    return 0


def update_skill(skills_dir: Path, vault: Path, remove: bool, dry: bool, adopt: bool = False) -> int:
    link = skills_dir / SKILL_NAME
    kit = vault / KIT_SUBDIR
    ours = link.is_symlink() and link.resolve() == kit.resolve()
    if remove:
        if not link.is_symlink() and not link.exists():
            print(f"Skill：{link} 不存在，无需移除")
        elif ours:
            if not dry:
                link.unlink()
            print(f"Skill：{'将移除' if dry else '已移除'}链接 {link}")
        elif owned_copy(link, vault):
            backup = backup_location(skills_dir)
            if not dry:
                backup.parent.mkdir(parents=True, exist_ok=True)
                link.rename(backup)
            print(f"Skill：{'将保留副本到' if dry else '副本已保留到'} {backup}")
        else:
            print(f"Skill：{link} 不是本工具创建的链接，保留不动", file=sys.stderr)
            return 2
        return 0
    if not (kit / "SKILL.md").is_file():
        print(f"Skill：停止。{kit} 里没有 SKILL.md，先运行 init_vault.py。", file=sys.stderr)
        return 2
    if ours:
        print(f"Skill：已链接 {link}")
        return 0
    copied = owned_copy(link, vault) if link.is_dir() and not link.is_symlink() else False
    bootstrap = adopt and matching_bootstrap(link, kit)
    occupied = link.exists() or link.is_symlink()
    if occupied and not (copied or bootstrap):
        print(f"Skill：停止。{link} 已存在且不是指向本记忆库的链接，为避免覆盖不做改动。"
              f"如果它是旧版本，请先手动移走。", file=sys.stderr)
        return 2
    if dry:
        if occupied:
            print(f"Skill：将备份已确认的{'副本' if copied else '初始安装'}到 {backup_location(skills_dir)}")
        print(f"Skill：将创建链接 {link} -> {kit}")
        return 0
    backup = None
    created = False
    try:
        skills_dir.mkdir(parents=True, exist_ok=True)
        if occupied:
            backup = backup_location(skills_dir)
            backup.parent.mkdir(parents=True, exist_ok=True)
            link.rename(backup)
        try:
            link.symlink_to(kit, target_is_directory=True)
            created = True
            print(f"Skill：已链接 {link} -> {kit}")
        except OSError:
            link.mkdir()
            created = True
            shutil.copytree(kit, link, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", OWNER))
            (link / OWNER).write_text(json.dumps({"schema": 1, "mode": "copy", "vault": display_path(vault)}), encoding="utf-8")
            print(f"Skill：系统不支持软链接，已复制到 {link}；重跑接入可更新这个受管理副本")
        if backup:
            print(f"Skill：原目录已备份 {backup}")
    except OSError as exc:
        if created and link.is_symlink():
            link.unlink()
        elif created and link.exists():
            shutil.rmtree(link)
        if backup and not link.exists() and not link.is_symlink():
            backup.rename(link)
        elif backup:
            print(f"Skill：目标出现其他内容，原目录保留在 {backup}", file=sys.stderr)
        print(f"Skill：接入失败并恢复原目录：{exc}", file=sys.stderr)
        return 2
    return 0


def status(vault: Path) -> None:
    print(f"记忆库：{vault}")
    for name, loc in AGENTS.items():
        entry = expand(loc["entry"]) if loc["entry"] else None
        entry_text = entry.read_text(encoding="utf-8", errors="ignore") if entry and entry.is_file() else ""
        expected = SNIPPET.read_text(encoding="utf-8").replace("{{VAULT}}", display_path(vault)).strip()
        has_entry = START in entry_text and END in entry_text and expected in entry_text
        link = expand(loc["skills"]) / SKILL_NAME
        has_skill = skill_linked(loc["skills"], vault)
        has_copy = owned_copy(link, vault)
        foreign = (link.exists() or link.is_symlink()) and not (has_skill or has_copy)
        installed = expand(loc["skills"]).parent.exists()
        e = "无入口文件" if entry is None else ("已接入" if has_entry else ("需更新" if START in entry_text else "未接入"))
        skill_status = "已链接" if has_skill else ("受管理副本" if has_copy else ("被其他同名文件夹占用" if foreign else "未链接"))
        print(f"  {name:10s} 工具目录{'存在' if installed else '不存在'}；入口 {e}；Skill {skill_status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=sorted(AGENTS), help="a known agent")
    parser.add_argument("--entry", help="custom entry file (for agents not in the list)")
    parser.add_argument("--skills-dir", help="custom skills folder (for agents not in the list)")
    parser.add_argument("--vault", help="vault path; default from ~/.config/ai-memory/path or ~/ai-memory")
    parser.add_argument("--no-entry", action="store_true", help="skip the entry step")
    parser.add_argument("--no-skill", action="store_true", help="skip the skill step")
    parser.add_argument("--remove", action="store_true", help="disconnect instead of connect")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("--follow-symlink", action="store_true", help="allow editing a symlinked entry file")
    parser.add_argument("--adopt-bootstrap", action="store_true", help="back up an identical initial Skill installation and replace it with the shared link")
    parser.add_argument("--status", action="store_true", help="show connection status of known agents")
    args = parser.parse_args()

    vault = resolve_vault(args.vault)
    if args.status:
        status(vault)
        return 0
    if not args.agent and not (args.entry or args.skills_dir):
        parser.error("需要 --agent，或者 --entry / --skills-dir")
    if not args.remove and not (vault / "00-索引" / "AI启动卡.md").is_file():
        print(f"停止：{vault} 不是记忆库（没有 00-索引/AI启动卡.md），先运行 init_vault.py。", file=sys.stderr)
        return 2

    loc = AGENTS.get(args.agent, {"entry": None, "skills": None})
    entry = args.entry or loc["entry"]
    skills = args.skills_dir or loc["skills"]
    # Keep the final entry symlink visible to update_entry's protection.
    entry_path = Path(os.path.expanduser(entry)).absolute() if entry else None
    skills_path = expand(skills) if skills else None
    # Preview both operations before changing any user-level entry.
    if not args.remove and not args.no_skill and skills_path:
        link = skills_path / SKILL_NAME
        kit = vault / KIT_SUBDIR
        if not (kit / "SKILL.md").is_file():
            print(f"Skill：停止。{kit} 里没有 SKILL.md，先运行 init_vault.py。", file=sys.stderr)
            return 2
        if update_skill(skills_path, vault, False, True, args.adopt_bootstrap):
            return 2
    if args.remove and not args.no_skill and skills_path:
        if update_skill(skills_path, vault, True, True):
            return 2
    if not args.no_entry and entry_path:
        if update_entry(entry_path, vault, args.remove, True, args.follow_symlink):
            return 2
    if args.dry_run:
        return 0
    entry_target = entry_path.resolve() if entry_path else None
    entry_existed = bool(entry_target and entry_target.exists())
    old_entry = entry_target.read_bytes() if entry_existed else None
    rc = 0
    if not args.no_entry:
        if entry_path:
            rc |= update_entry(entry_path, vault, args.remove, args.dry_run, args.follow_symlink)
            if rc:
                return rc
        else:
            print("入口：这个工具没有文件型入口，请把 assets/entry-snippet.md 填好路径后粘贴到它的规则设置里。")
    if not args.no_skill:
        if skills:
            rc |= update_skill(skills_path, vault, args.remove, False, args.adopt_bootstrap)
            if rc and entry_target and not args.no_entry:
                if entry_existed:
                    entry_target.write_bytes(old_entry)
                elif entry_target.exists():
                    entry_target.unlink()
                print("入口：Skill 步骤失败，已恢复接入前内容", file=sys.stderr)
        else:
            print("Skill：没有指定 Skill 目录，跳过。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
