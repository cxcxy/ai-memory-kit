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


def strip_block(text: str) -> str:
    if START not in text:
        return text
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
    base = strip_block(old)
    if remove:
        new = base
    else:
        block = SNIPPET.read_text(encoding="utf-8").replace("{{VAULT}}", display_path(vault)).strip()
        new = (base.rstrip("\n") + "\n\n" if base.strip() else "") + f"{START}\n{block}\n{END}\n"
    if new == old:
        print(f"入口：无需修改 {entry}")
        return 0
    if dry:
        print(f"入口：将写入 {entry}\n{new}")
        return 0
    entry.parent.mkdir(parents=True, exist_ok=True)
    if entry.exists():
        backup = entry.with_name(entry.name + time.strftime(".bak-%Y%m%d%H%M%S"))
        shutil.copy2(entry, backup)
        print(f"入口：已备份原文件 {backup}")
    entry.write_text(new, encoding="utf-8")
    print(f"入口：已{'移除' if remove else '写入'} {entry}")
    return 0


def update_skill(skills_dir: Path, vault: Path, remove: bool, dry: bool) -> int:
    link = skills_dir / SKILL_NAME
    kit = vault / KIT_SUBDIR
    ours = link.is_symlink() and link.resolve() == kit.resolve()
    if remove:
        if not link.is_symlink() and not link.exists():
            print(f"Skill：{link} 不存在，无需移除")
        elif ours or (link.is_symlink() and SKILL_NAME in os.readlink(link)):
            if not dry:
                link.unlink()
            print(f"Skill：{'将移除' if dry else '已移除'}链接 {link}")
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
    if link.exists() or link.is_symlink():
        print(f"Skill：停止。{link} 已存在且不是指向本记忆库的链接，为避免覆盖不做改动。"
              f"如果它是旧版本，请先手动移走。", file=sys.stderr)
        return 2
    if dry:
        print(f"Skill：将创建链接 {link} -> {kit}")
        return 0
    skills_dir.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(kit, target_is_directory=True)
        print(f"Skill：已链接 {link} -> {kit}")
    except OSError:
        shutil.copytree(kit, link)
        print(f"Skill：系统不支持软链接，已复制到 {link}（更新工具后需要重新复制）")
    return 0


def status(vault: Path) -> None:
    print(f"记忆库：{vault}")
    for name, loc in AGENTS.items():
        entry = expand(loc["entry"]) if loc["entry"] else None
        has_entry = bool(entry and entry.exists() and START in entry.read_text(encoding="utf-8", errors="ignore"))
        link = expand(loc["skills"]) / SKILL_NAME
        has_skill = skill_linked(loc["skills"], vault)
        foreign = (link.exists() or link.is_symlink()) and not has_skill
        installed = expand(loc["skills"]).parent.exists()
        e = "无入口文件" if entry is None else ("已接入" if has_entry else "未接入")
        print(f"  {name:10s} 工具目录{'存在' if installed else '不存在'}；入口 {e}；Skill {'已链接' if has_skill else ('被其他同名文件夹占用' if foreign else '未链接')}")


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
    rc = 0
    if not args.no_entry:
        if entry:
            rc |= update_entry(expand(entry), vault, args.remove, args.dry_run, args.follow_symlink)
        else:
            print("入口：这个工具没有文件型入口，请把 assets/entry-snippet.md 填好路径后粘贴到它的规则设置里。")
    if not args.no_skill:
        if skills:
            rc |= update_skill(expand(skills), vault, args.remove, args.dry_run)
        else:
            print("Skill：没有指定 Skill 目录，跳过。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
