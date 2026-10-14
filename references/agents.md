# 各 AI 工具的接入位置

`connect_agent.py --status` 会列出下表工具在本机的状态。下表是各工具的公开约定或实测结果，版本更新后可能变化；动手前确认文件或目录真实存在，不存在就告诉用户，不要猜。

## 入口与 Skill 目录

| 工具 | `--agent` | 用户级入口（使用） | Skill 目录（维护） | 说明 |
|---|---|---|---|---|
| Codex | `codex` | `~/.codex/AGENTS.md` | `~/.codex/skills/` | |
| Claude Code | `claude` | `~/.claude/CLAUDE.md` | `~/.claude/skills/` | |
| WorkBuddy | `workbuddy` | `~/.workbuddy/RULES.md` | `~/.workbuddy/skills/` | 部分版本不会自动加载 RULES.md，需要用户在规则或工作区知识设置里手动选中它；接入后务必新开对话验证。WorkBuddy 自带 `USER.md`、`MEMORY.md` 记忆，建议以记忆库为准，自带记忆只放 WorkBuddy 特有的内容，避免出现两份不一致的画像 |
| Gemini CLI | `gemini` | `~/.gemini/GEMINI.md` | `~/.gemini/skills/` | Skill 目录以所装版本是否支持为准 |
| 通用 Agent Skills 目录 | `agents` | 无 | `~/.agents/skills/` | 部分工具从这里加载 Skill；入口要按具体工具另配 |
| Cursor | 无 | 设置里的 Rules（用户规则） | 以当前版本为准 | 入口交给用户粘贴 `assets/entry-snippet.md` |
| 其他工具 | 无 | 以该工具文档为准 | 以该工具文档为准 | `connect_agent.py --entry <文件> --skills-dir <目录>` |
| 网页版聊天 | 无 | 自定义指令 | 无 | 读不到本地文件，只能粘贴启动卡内容；偏好要用户转述到能写文件的工具里记录 |

注意：

- 入口文件可能已经有用户自己的内容。脚本只追加带标记的区块，并先备份；不要整体覆盖。
- 入口文件可能是软链接，多个工具共用一份。脚本默认拒绝修改，先告诉用户影响范围。
- Skill 目录里已有同名文件夹且不是指向本记忆库的链接时，脚本不会替换，让用户决定。
- 项目级入口（项目目录里的 `AGENTS.md`、`CLAUDE.md`）只影响那个项目；要全局生效就用上表的用户级入口。

## 会话记录（整理时读取）

| 工具 | 本机位置 | 说明 |
|---|---|---|
| Codex | `~/.codex/sessions/年/月/日/*.jsonl` | 每个会话一个文件 |
| Claude Code | `~/.claude/projects/<项目>/*.jsonl` | 按修改时间筛选当天 |
| WorkBuddy | 应用自己的数据库 | 格式未公开，暂不读取，靠收件箱 |
| 其他工具 | 未收录 | 先在用户机器上确认，再登记到记忆库的 `00-索引/同步任务说明.md` |

会话记录可能很大。读取时只提取用户消息和最终结论，读不到就标记“部分完成”，不凭文件名或时间补写。

## 定时整理

只在一个工具里设置，在记忆库 `00-索引/同步状态.md` 开头写明负责的工具。

| 工具 | 方式 |
|---|---|
| Codex | 应用里的自动化（Automations），新建每日任务，指令用记忆库里 `定时任务指令.md` 的那段话 |
| Claude Code、WorkBuddy | 有定时或计划任务功能时同上，以当前版本为准 |
| 不支持定时的工具 | 每周手动说一次“按同步任务说明做一次每周复盘” |

定时任务保存在各工具本机，不随记忆库迁移，换电脑后要重新设置。
