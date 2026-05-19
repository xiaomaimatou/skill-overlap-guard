# skills-manager

[English](README.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)](https://www.python.org/)
[![GitHub](https://img.shields.io/badge/GitHub-EfanWang%2Fskills--manager-181717.svg)](https://github.com/EfanWang/skills-manager)

`skills-manager` 是一个面向 `SKILL.md` 生态的简单好用的技能管理器。它会扫描当前 skills 根目录下的同级技能，记录每个技能的来源，并帮助智能体完成清单查看、来源追踪、更新检查、技能更新、安装和删除。

它适用于任何支持 `SKILL.md` 的智能体：

| 智能体 | 支持情况 |
|---|---|
| [Claude Code](https://code.claude.com/docs/en/skills) | 支持 skills 目录 |
| [Cursor](https://cursor.com/changelog/2-4) | 2.4+ 支持 skills |
| [Codex CLI](https://developers.openai.com/codex/skills) | 支持 Codex skills |

## 为什么需要它

当你在同一个环境中安装了多个技能之后，常见问题会很快出现：

- 不知道当前到底安装了哪些技能
- 不知道某个技能来自哪个 GitHub 仓库
- 无法及时获知技能更新情况
- 手动更新技能时容易覆盖本地文件
- 来源未知的技能难以继续维护

`skills-manager` 用一个轻量的 `sources.json` 注册表解决这些问题。它只管理自身父目录下的同级技能，不跨 Claude Code、Cursor、Codex CLI 等不同工具聚合清单，因此行为清晰、范围可控。

## 功能概览

| 功能 | 说明 |
|---|---|
| 技能清单 | 扫描同级技能目录，列出名称、类型、描述和状态 |
| 来源追踪 | 对来源未知的技能进行本地证据分析，并交给智能体继续网页检索 |
| 更新检查 | 对已注册 GitHub 来源的技能执行远程版本检查 |
| 技能更新 | 拉取上游最新版，替换前自动创建备份 |
| 技能安装 | 从 GitHub URL 克隆技能，原子放置并登记来源 |
| 技能删除 | 删除前自动备份，便于手动恢复 |

## 安装

将本仓库克隆到你的 skills 根目录：

```bash
cd ~/.claude/skills          # 或你的智能体 skills 根目录
git clone https://github.com/EfanWang/skills-manager.git
```

常见 skills 根目录如下：

| 智能体 | 典型 skills 根目录 |
|---|---|
| Claude Code | `~/.claude/skills/` 或项目 `.claude/skills/` |
| Cursor | `~/.cursor/skills/` 或项目 `.cursor/skills/` |
| Codex CLI | `~/.codex/skills/` 或 `~/.agents/skills/` |

安装后即可使用。运行脚本只需要：

- Python 3.9+
- `git` 已加入 PATH

## 快速开始

列出所有技能，并检查远程技能是否有更新：

```powershell
python scripts/inventory.py --check-remote --audit-unclaimed
```

查看某个远程技能的上游状态：

```powershell
python scripts/check_remote.py my-skill
```

更新一个已过期的技能：

```powershell
python scripts/update_skill.py my-skill
```

从 GitHub 安装一个技能：

```powershell
python scripts/install_skill.py https://github.com/user/repo/tree/main/skills/my-skill
```

## 运行说明

首次执行全量清单和来源审计时，`skills-manager` 会遍历当前 skills 根目录下的所有同级技能，并尝试建立或补全 `sources.json` 中的来源记录。因此，第一次运行可能需要更长时间；当来源记录逐步完善后，后续清单扫描和更新检查通常会更快。

## 命令速查

所有脚本都位于 `scripts/` 目录，并将 JSON 输出到 stdout。错误会输出到 stderr，并使用结构化退出码：

| 退出码 | 含义 |
|---|---|
| 2 | 输入错误 |
| 3 | `sources.json` 损坏 |
| 4 | 远程操作失败 |
| 5 | 文件系统替换失败 |

| 脚本 | 用途 |
|---|---|
| `inventory.py [--check-remote] [--audit-unclaimed]` | 扫描并分类所有同级技能 |
| `audit_unclaimed.py [--dry-run]` | 批量识别未认领技能的来源 |
| `check_remote.py <name>` | 对照上游检查单个远程技能 |
| `update_skill.py <name> [--dry-run]` | 通过克隆和原子替换拉取最新上游版本 |
| `install_skill.py <url> [--name N] [--branch B]` | 克隆、原子安装并注册来源 |
| `sources.py list\|remove\|claim-local\|claim-remote` | 管理 `sources.json` 条目 |
| `similarity.py <local.md> <remote.md>` | 比较两个 `SKILL.md` 文件的相似度 |

## 状态模型

每个技能会被归类为三种类型之一：

| 类型 | 含义 | 可检查更新 |
|---|---|---|
| `remote` | 在 `sources.json` 中登记了 GitHub 来源 | 是 |
| `local` | 用户标记为私有或自行编写 | 否，始终视为当前版本 |
| `unclaimed` | 来源未知，尚未完成追踪 | 否 |

inventory 返回的状态包括：

| 状态 | 含义 |
|---|---|
| `up_to_date` | 本地版本与上游 HEAD 匹配 |
| `update_available` | 上游存在更新提交 |
| `unknown` | 无法确定，通常是未认领或网络错误 |

## 来源追踪工作流

`skills-manager` 使用分层证据来判断一个技能来自哪里：

1. **读取 `.git/config`**：如果技能目录本身是一个 Git checkout，直接读取 remote URL。
2. **检查 `SKILL.md` 中的 GitHub URL**：如果文件内包含 GitHub 链接，将其作为显式来源线索，并通过相似度检查验证。
3. **交给智能体继续网页检索**：对于仍未解决的技能，脚本会输出 `search_query_hint`，由智能体结合网页搜索判断来源，此功能需要联网。

识别来源后，可以手动登记：

```powershell
# 来自 GitHub 的远程技能
python scripts/sources.py claim-remote my-skill --url https://github.com/owner/repo --branch main --subpath skills/my-skill

# 本地或私有技能
python scripts/sources.py claim-local my-skill
```

## 安全设计

- **默认非破坏性**：`audit_unclaimed.py` 只写入 `sources.json`，不会改动技能文件。
- **自动备份**：安装、更新、删除等替换性操作会在 `.backup/` 下创建备份。
- **原子替换**：目录替换使用 rename-based swap，降低中途失败导致损坏状态的风险。
- **可手动恢复**：备份路径形如 `.backup/<name>-<timestamp>-<uuid>/`，可手动移回。
- **无遥测**：没有分析和遥测；网络访问仅限 `git ls-remote` 以及用于验证的原始文件获取。
- **最小作用域**：只管理同级技能目录，不触碰插件缓存、Cursor 内置技能或 skills 根目录之外的文件。

## 限制

- 仅支持 GitHub 作为远程来源，不支持 GitLab、zip URL、npm 等来源
- 不检测或合并本地编辑；更新会在备份后用上游版本替换目录
- 不管理 Cursor 的内置技能目录 `skills-cursor/`
- 不管理插件缓存中的技能，例如 `~/.claude/plugins/cache/...`

## 开发

运行测试：

```powershell
python -m unittest tests.test_contract
```

项目结构：

```text
skills-manager/
|-- SKILL.md               # 面向智能体的技能说明
|-- sources.json           # 已知技能来源注册表
|-- scripts/
|   |-- _common.py         # 共享工具
|   |-- inventory.py       # 列出并分类技能
|   |-- audit_unclaimed.py # 批量识别来源
|   |-- check_remote.py    # 对照上游检查单个技能
|   |-- update_skill.py    # 更新到最新上游版本
|   |-- install_skill.py   # 从 GitHub 安装
|   |-- sources.py         # sources.json CRUD
|   `-- similarity.py      # SKILL.md 文件比较
|-- tests/
|   `-- test_contract.py
|-- .backup/               # 自动创建的备份，已 gitignore
`-- .tmp/                  # 临时文件，已 gitignore
```

## 获取帮助

如果你遇到来源识别错误、更新失败或脚本输出不符合预期，可以在 [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager) 提交 issue，并附上相关命令、JSON 输出和错误信息。

## 许可证

MIT
