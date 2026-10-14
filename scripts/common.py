"""Shared helpers: where the vault lives, and where each agent keeps its entry and skills."""
import os
from pathlib import Path

DEFAULT_VAULT = "~/ai-memory"
POINTER = Path("~/.config/ai-memory/path").expanduser()
ENV = "AI_MEMORY_HOME"
SKILL_NAME = "ai-memory-kit"
KIT_SUBDIR = Path(".kit") / SKILL_NAME

# entry: user-level rules file the agent reads at the start of every session
# skills: directory the agent scans for SKILL.md folders
AGENTS = {
    "codex": {"entry": "~/.codex/AGENTS.md", "skills": "~/.codex/skills"},
    "claude": {"entry": "~/.claude/CLAUDE.md", "skills": "~/.claude/skills"},
    "gemini": {"entry": "~/.gemini/GEMINI.md", "skills": "~/.gemini/skills"},
    "workbuddy": {"entry": "~/.workbuddy/RULES.md", "skills": "~/.workbuddy/skills"},
    "agents": {"entry": None, "skills": "~/.agents/skills"},
}


def expand(p) -> Path:
    return Path(os.path.expanduser(str(p))).resolve()


def resolve_vault(explicit=None) -> Path:
    """Order: --path argument, $AI_MEMORY_HOME, ~/.config/ai-memory/path, ~/ai-memory."""
    if explicit:
        return expand(explicit)
    if os.environ.get(ENV):
        return expand(os.environ[ENV])
    if POINTER.is_file():
        text = POINTER.read_text(encoding="utf-8").strip()
        if text:
            return expand(text)
    return expand(DEFAULT_VAULT)


def display_path(path: Path) -> str:
    """Prefer ~/... so text stays portable across usernames."""
    try:
        return "~/" + str(Path(path).relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


def skill_linked(skills_dir, vault: Path) -> bool:
    """True only when the agent's skill entry is our link to <vault>/.kit."""
    link = expand(skills_dir) / SKILL_NAME
    return link.is_symlink() and link.resolve() == (vault / KIT_SUBDIR).resolve()
