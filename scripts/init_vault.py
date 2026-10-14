#!/usr/bin/env python3
"""Create an AI memory vault from the bundled template.

Also copies this skill into <vault>/.kit/ai-memory-kit so data and tools travel
together, and records the vault location in ~/.config/ai-memory/path so every
agent finds it without being told. Never overwrites a non-empty folder.
Standard library only; works with Python 3.8+.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_VAULT, KIT_SUBDIR, POINTER, display_path, expand  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "template"
PLACEHOLDER = DEFAULT_VAULT
IGNORE = shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", ".git")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT_VAULT, help="vault location, default ~/ai-memory")
    parser.add_argument("--git", action="store_true", help="run git init inside the vault")
    parser.add_argument("--dry-run", action="store_true", help="list what would happen without writing")
    args = parser.parse_args()

    target = expand(args.path)
    shown = display_path(target)

    if not TEMPLATE.is_dir():
        print(f"错误：找不到模板目录 {TEMPLATE}", file=sys.stderr)
        return 1
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        print(f"停止：{target} 已存在且不是空目录。为避免覆盖，请换一个路径，"
              f"或先用 check_vault.py 检查它是不是已有的记忆库。", file=sys.stderr)
        return 2

    files = sorted(p for p in TEMPLATE.rglob("*") if p.is_file() and p.name != ".DS_Store")
    if args.dry_run:
        print(f"将创建记忆库：{target}（{len(files)} 个模板文件）")
        print(f"将复制工具到：{target / KIT_SUBDIR}")
        print(f"将记录路径到：{POINTER}")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    for src in files:
        dst = target / src.relative_to(TEMPLATE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".md":
            dst.write_text(src.read_text(encoding="utf-8").replace(PLACEHOLDER, shown), encoding="utf-8")
        else:
            shutil.copy2(src, dst)

    kit = target / KIT_SUBDIR
    if SKILL_DIR.resolve() != kit.resolve():
        shutil.copytree(SKILL_DIR, kit, ignore=IGNORE)

    POINTER.parent.mkdir(parents=True, exist_ok=True)
    previous = POINTER.read_text(encoding="utf-8").strip() if POINTER.is_file() else ""
    POINTER.write_text(shown + "\n", encoding="utf-8")

    print(f"已创建记忆库：{target}（文中路径写作 {shown}），共 {len(files)} 个文件。")
    print(f"工具已放进：{kit}")
    print(f"路径已记录到：{POINTER}" + (f"（原来指向 {previous}）" if previous and previous != shown else ""))

    if args.git:
        try:
            subprocess.run(["git", "init", "-q", str(target)], check=True)
            print("已在记忆库里执行 git init，可随时回滚 AI 的改动。")
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"git init 没有成功（{e}），记忆库本身不受影响。", file=sys.stderr)

    print("下一步：填写 00-索引/AI启动卡.md，然后用 connect_agent.py 接入你的 AI 工具。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
