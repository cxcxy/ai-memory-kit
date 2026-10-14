"""Small shared helpers for recording and applying confirmed personal memory."""
import contextlib
import datetime as dt
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

KINDS = ("decision", "experience", "preference", "correction", "withdrawal")
LABELS = {"decision": "决定", "experience": "经验", "preference": "偏好", "correction": "纠正", "withdrawal": "撤销"}


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="microseconds")


def inside(vault, relative):
    path = vault / relative
    path.resolve().relative_to(vault.resolve())
    return path


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        f.write(text)
        temporary = Path(f.name)
    try:
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def vault_lock(vault):
    path = inside(vault, "00-索引/.整理中")
    owner_id = uuid.uuid4().hex
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump({"owner_id": owner_id, "pid": os.getpid(), "time": now()}, f)
    try:
        yield
    finally:
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("owner_id") == owner_id:
                path.unlink()
        except (OSError, ValueError):
            pass


def block(text, name, body):
    start, end = "<!-- ai-memory-kit:" + name + ":start -->", "<!-- ai-memory-kit:" + name + ":end -->"
    replacement = start + "\n" + body.strip() + "\n" + end
    if start not in text and end not in text:
        return text.rstrip() + "\n\n" + replacement + "\n"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(end) < text.index(start):
        raise ValueError("受管理区块不完整：" + name)
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    return before + replacement + after


def project_file(name):
    slug = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip(". ")[:70]
    if not slug:
        raise ValueError("项目名不能为空")
    # Preserve readable names while avoiding collisions caused by sanitizing paths.
    if slug != name:
        import hashlib
        slug += "-" + hashlib.sha256(name.encode()).hexdigest()[:8]
    return "02-项目/" + slug + ".md"


def markdown_record(record):
    fields = [("内容", record["summary"]), ("原因", record.get("reason", "")),
              ("实践结果", record.get("result", "")), ("适用条件", record.get("conditions", "")),
              ("范围", record["scope"]), ("项目", record.get("project", "")),
              ("来源", record["source"]), ("记录时间", record["recorded_at"]), ("工具", record["agent"])]
    return "### " + LABELS[record["kind"]] + "｜" + record["key"] + "\n\n" + "\n".join(
        "- " + label + "：" + str(value).replace("\n", " ") for label, value in fields if value)


def load_state(vault):
    path = inside(vault, "00-索引/.已确认记录.json")
    if not path.exists():
        return {"schema": 1, "records": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("records"), dict):
        raise ValueError("已确认记录格式不正确，停止以保护原内容")
    for key, record in data["records"].items():
        validate(record)
        if key != record["id"]:
            raise ValueError("已确认记录 ID 不一致")
    return data


def validate(record):
    for field in ("id", "kind", "key", "summary", "scope", "source", "agent", "recorded_at"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError("缺少字段：" + field)
    if not re.fullmatch(r"[a-f0-9]{32}", record["id"]) or record["kind"] not in KINDS:
        raise ValueError("记录类型或 ID 不正确")
    if record["scope"] not in ("global", "project"):
        raise ValueError("范围必须是 global 或 project")
    timestamp = dt.datetime.fromisoformat(record["recorded_at"])
    if timestamp.tzinfo is None:
        raise ValueError("记录时间必须包含时区")
    if record["scope"] == "project" and not record.get("project", "").strip():
        raise ValueError("项目记录需要项目名")
    if record["kind"] in ("decision", "experience") and record["scope"] != "project":
        raise ValueError("决定和经验先保留在对应项目中")
    if record["kind"] == "decision" and not record.get("reason", "").strip():
        raise ValueError("决定需要保留原因")
    if record["kind"] == "experience" and not all(record.get(f, "").strip() for f in ("result", "conditions")):
        raise ValueError("经验需要实践结果与适用条件")
    from import_existing import redact
    if redact(json.dumps(record, ensure_ascii=False))[1]:
        raise ValueError("记录中含疑似凭据，请去掉后再保存")


def plan_apply(vault, record=None):
    if record is not None:
        validate(record)
    state = load_state(vault)
    if record is not None and record["id"] in state["records"]:
        return {}, state
    if record is not None:
        state["records"][record["id"]] = record
    active = {}
    # Delayed confirmation must not undo a newer correction.
    def order(item):
        return (dt.datetime.fromisoformat(item["recorded_at"]),
                {"correction": 1, "withdrawal": 2}.get(item["kind"], 0))

    for item in sorted(state["records"].values(), key=order):
        key = (item["scope"], item.get("project", ""), item["key"])
        previous = active.get(key)
        if previous is not None and order(previous) == order(item):
            content = ("kind", "summary", "reason", "result", "conditions")
            if any(previous.get(field, "") != item.get(field, "") for field in content):
                raise ValueError("同主题同时间存在冲突，请核对后记录一条新的明确要求")
        active.pop(key, None)
        active[key] = item
    globals_ = [item for key, item in active.items() if key[0] == "global"]
    updates = {}

    def update(relative, name, body, default):
        path = inside(vault, relative)
        old = path.read_text(encoding="utf-8") if path.exists() else default
        updates[path] = block(old, name, body)

    if globals_:
        body = "## 已确认要求\n\n" + "\n\n".join(markdown_record(item) for item in globals_)
        update("01-用户记忆/长期偏好.md", "confirmed-preferences", body, "# 长期偏好\n")
    projects = sorted({item["project"] for item in state["records"].values() if item["scope"] == "project"})
    for project in projects:
        items = [item for key, item in active.items() if key[0] == "project" and key[1] == project]
        body = "## 已确认的决定与经验\n\n" + "\n\n".join(markdown_record(item) for item in items)
        relative = project_file(project)
        update(relative, "project-memory", body, "# " + project + "\n")
    if projects:
        rows = ["| 项目 | 项目页 |", "|---|---|"]
        rows += ["| " + name.replace("|", "\\|") + " | [项目页](../" + project_file(name) + ") |" for name in projects]
        update("00-索引/项目索引.md", "project-index", "## 已确认记录对应项目\n\n" + "\n".join(rows), "# 项目索引\n")

    # A new confirmed requirement immediately changes the card seen by all Agents.
    recent = globals_ + [item for key, item in active.items() if key[0] == "project"][-5:]
    rows = ["## 近期已确认更新", "", "本节中的更新覆盖同主题旧摘要；项目要求仅适用于对应项目。完整来源在正式记忆与项目页。", ""]
    for item in recent:
        scope = "全局" if item["scope"] == "global" else "项目 " + item["project"]
        summary = item["summary"].replace("\n", " ")[:150]
        prefix = "已撤销旧要求：" if item["kind"] == "withdrawal" else ""
        rows.append("- " + scope + "｜" + item["key"] + "：" + prefix + summary)
    update("00-索引/AI启动卡.md", "recent-confirmed", "\n".join(rows), "# AI 启动卡\n")
    if record is not None:
        history = inside(vault, "03-每日记录/记忆/" + record["id"] + ".md")
        content = "# 已确认记录\n\n" + markdown_record(record) + "\n"
        if history.exists() and history.read_text(encoding="utf-8") != content:
            raise ValueError("历史记录 ID 已被不同内容占用")
        updates[history] = content
    return updates, state
