# ai-memory-kit：AI 记忆库 Skill

让 AI 记住你是谁。Codex、Claude Code、WorkBuddy、Gemini CLI 这类能装 Skill 的工具，都读同一个本地文件夹，也都能往里记、帮你整理。换工具也不用从头交代。不需要向量数据库，整个记忆库就是一堆 Markdown 文档。

## 它长什么样

```
~/ai-memory/                     你的记忆库（数据和工具在一个文件夹里）
├── 00-索引/                     启动卡、收件箱、整理规则
├── 01-用户记忆/                 我是谁、长期偏好、边界
├── 02-项目/  03-每日记录/  04-每周复盘/  99-原始资料/
└── .kit/ai-memory-kit/          本 Skill（各工具通过软链接共用这一份）
```

为什么放 `~/ai-memory`：Mac 的桌面、文稿、下载是隐私保护目录，命令行类 AI 工具常被拦；iCloud 和网盘的“优化存储”会把文件挪到云端。用户目录下的英文路径没有这些问题，Obsidian 也能直接打开。

## 安装（只需要做一次）

1. 把本仓库放进任意一个你在用的工具的 Skill 目录，比如 `~/.claude/skills/`、`~/.codex/skills/` 或 `~/.workbuddy/skills/`：

   ```bash
   git clone https://github.com/cxcxy/ai-memory-kit.git ~/.claude/skills/ai-memory-kit
   ```

   也可以下载压缩包，解压后把 `ai-memory-kit` 文件夹复制进去。
2. 在那个工具里新开对话，说：“帮我搭一个 AI 记忆库”。

它会建好 `~/ai-memory`、问你几个问题填好启动卡，然后问你还在用哪些工具，经你同意后把它们一并接上。之后 Skill 的正本在记忆库的 `.kit/` 里，第 1 步复制进去的那份可以删掉。

需要本机有 Python 3。

## 用法

| 你说 | 它做 |
|---|---|
| “帮我搭一个 AI 记忆库” | 建库、填启动卡、接入你的工具 |
| “把记忆库也接到 WorkBuddy 上” | 写入口、链接 Skill |
| “记住，以后周报别用表格” | 记进收件箱，整理时合并成长期偏好 |
| “按规则做一次每周复盘” | 整理、去重、更新你的画像 |
| “检查一下我的记忆库” | 体检，并列出每个工具的接入状态 |

不想用 Skill 也可以手动搭：`assets/template/` 就是记忆库模板，按里面的 README 走三步。

## 它会改什么

- 新建 `~/ai-memory`（或你指定的位置），并在 `~/.config/ai-memory/path` 记下路径。已有同名的非空文件夹时会停下，不覆盖。
- 经你同意后，在每个工具的用户级规则文件末尾加一段带标记的说明，改之前先备份；在它的 Skill 目录里放一个指向 `.kit/ai-memory-kit` 的软链接。用 `connect_agent.py --agent <工具> --remove` 可以完整撤销。
- 不上传任何东西。但要知道：AI 读到的记忆内容，会随对话发给该工具背后的云端模型，所以记忆库里不要写密码和密钥。

## 文件结构

```
ai-memory-kit/
├── SKILL.md                给 AI 看的操作说明
├── README.md               本文件
├── scripts/
│   ├── common.py           记忆库定位、各工具位置
│   ├── init_vault.py       建库（不覆盖已有文件夹）
│   ├── connect_agent.py    接入、查看、断开工具（入口 + Skill 链接）
│   └── check_vault.py      只读体检
├── references/agents.md    各工具的入口、Skill 目录、会话记录、定时任务
└── assets/
    ├── entry-snippet.md    写进入口文件的那段话
    └── template/           记忆库模板
```
