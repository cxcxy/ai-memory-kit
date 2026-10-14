#!/usr/bin/env python3
"""Health check for an AI memory vault. Read-only.

Reports missing structure, unfilled placeholders, startup-card length,
pending inbox items, stale sync, and anything that looks like a credential.
Exit code 0 = no problems, 1 = problems found, 2 = not a vault.
Standard library only; works with Python 3.8+.
"""
import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import AGENTS, KIT_SUBDIR, resolve_vault, skill_linked  # noqa: E402

# each entry: acceptable names (older vaults may use the alternative folder names)
REQUIRED = [
    ("00-索引/AI启动卡.md",), ("00-索引/读取协议.md",), ("00-索引/收件箱.md",),
    ("00-索引/同步任务说明.md",), ("00-索引/同步状态.md",), ("00-索引/项目索引.md",),
    ("01-用户记忆",), ("02-项目",), ("03-每日记录", "03-每日沉淀"), ("04-每周复盘",),
    ("99-原始资料", "99-来源快照"),
]
SECRET_PATTERNS = [
    (re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"), "API Key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub Token"),
    (re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"), "Slack Token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
    (re.compile(r"(?i)(password|passwd|密码|api[_-]?key|secret|token|cookie)\s*[:：=]\s*\S{6,}"), "疑似凭据赋值"),
]
DATE_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", help="vault path; default from ~/.config/ai-memory/path or ~/ai-memory")
    args = parser.parse_args()
    vault = resolve_vault(args.path)

    if not (vault / "00-索引" / "AI启动卡.md").is_file():
        print(f"不是记忆库：{vault} 里没有 00-索引/AI启动卡.md")
        return 2

    problems, notes = [], []
    for names in REQUIRED:
        if not any((vault / n).exists() for n in names):
            problems.append(f"缺少：{' 或 '.join(names)}")
    daily_dir = next((n for n in ("03-每日记录", "03-每日沉淀") if (vault / n).is_dir()), "03-每日记录")

    card = (vault / "00-索引" / "AI启动卡.md").read_text(encoding="utf-8")
    lines = len(card.splitlines())
    if lines > 80:
        problems.append(f"启动卡有 {lines} 行，超过 80 行，每次开工读得太多")
    blanks = card.count("【")
    if blanks:
        notes.append(f"启动卡还有 {blanks} 处【】没填")

    inbox = vault / "00-索引" / "收件箱.md"
    if inbox.exists():
        body = inbox.read_text(encoding="utf-8").split("## 待处理", 1)[-1]
        pending = [l for l in body.splitlines() if l.strip() and "|" in l]
        notes.append(f"收件箱待处理 {len(pending)} 条")

    today = dt.date.today()
    for folder, label, limit in ((daily_dir, "每日记录", 2), ("04-每周复盘", "每周复盘", 8)):
        d = vault / folder
        if folder == daily_dir:
            dates = [dt.date.fromisoformat(m.group(1)) for p in d.glob("*.md")
                     if (m := DATE_FILE.match(p.name))] if d.exists() else []
            if dates:
                gap = (today - max(dates)).days
                (problems if gap > limit else notes).append(f"最近一篇{label}是 {max(dates)}，距今 {gap} 天")
            else:
                notes.append(f"还没有{label}")
        else:
            reviews = [p for p in d.glob("*.md") if not p.name.startswith("_")] if d.exists() else []
            if reviews:
                latest = max(reviews, key=lambda p: p.stat().st_mtime)
                gap = (today - dt.date.fromtimestamp(latest.stat().st_mtime)).days
                (problems if gap > limit else notes).append(f"最近一次{label}是 {latest.name}，距今 {gap} 天")
            else:
                notes.append(f"还没有{label}")

    for p in vault.rglob("*.md"):
        if ".kit" in p.parts or ".git" in p.parts or "99-来源快照" in p.parts or "99-原始资料" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for pat, label in SECRET_PATTERNS:
                if pat.search(line):
                    problems.append(f"疑似泄露{label}：{p.relative_to(vault)} 第 {i} 行")
                    break

    if not (vault / KIT_SUBDIR / "SKILL.md").is_file():
        notes.append("记忆库里没有 .kit/ai-memory-kit，各工具无法共用同一份 Skill")
    connected = [n for n, loc in AGENTS.items() if skill_linked(loc["skills"], vault)]
    notes.append("已链接 Skill 的工具：" + ("、".join(connected) if connected else "无"))

    print(f"记忆库：{vault}")
    for n in notes:
        print(f"  信息：{n}")
    for pr in problems:
        print(f"  问题：{pr}")
    print("结论：" + ("发现问题，见上方" if problems else "结构完整，没有发现问题"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
