# Skill Overlap Guard

English · 简体中文

> 给 Agent Skill 安装流程加一道语义查重闸门：先确认新 Skill 是否已经被现有能力覆盖，再决定是否继续。

Skill Overlap Guard 是一个面向 Codex、Claude Code 和 Cursor 等 Agent Skills 用户的本地工具。它会扫描已安装的 Skill，提取能力画像，识别重复或部分重叠，并把用户对重叠关系的判断记录下来。

## 目录

- [为什么需要](#为什么需要)
- [核心能力](#核心能力)
- [安装](#安装)
- [快速开始](#快速开始)
- [工作原理](#工作原理)
- [扫描范围](#扫描范围)
- [安全边界](#安全边界)
- [已知限制](#已知限制)
- [开发与测试](#开发与测试)
- [许可证](#许可证)

## 为什么需要

Skill 越装越多，名称却不能说明真实能力。两个名称完全不同的 Skill，可能都在做同一件事；反过来，一个父 Skill 和它的子 Skill 也可能只是上下级关系，不应被误判为重复。

Skill Overlap Guard 将安装前检查变成一个可解释的决策流程：

- 找出当前已经安装的 Skill；
- 对比能力、触发词、工作流、输入和输出，而不是只比较名称；
- 区分 `HIGH`、`partial`、`complementary`、`parent-child` 等关系；
- 在高重叠时暂停默认安装，等待用户确认；
- 保存用户的保留、忽略或偏好决定，供后续报告参考。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| Inventory | 递归扫描 Skill，并识别父子目录关系、来源和远程更新状态。 |
| Capability Profile | 从 `SKILL.md` 提取能力、触发词、工作流、输入、输出、工具和依赖。 |
| Overlap Audit | 对存量 Skill 做候选召回和语义复核，输出可解释的重叠关系。 |
| Pre-install Check | 在新 Skill 进入安装流程前，与现有 Skill 做功能查重。 |
| Dedup Gate | 对 `HIGH` / `DUPLICATE` 关系给出阻断式提醒，不替用户做决定。 |
| Decision Registry | 将用户决定写入 `decisions.json`，避免每次重复讨论同一对 Skill。 |
| Terminal Guard | 可选地拦截 `npx skills add`，仅做可逆 dry-run 检查。 |

## 安装

将仓库克隆到某个 Agent Skills 根目录的同级位置：

```bash
git clone https://github.com/EfanWang/skill-overlap-guard.git
```

运行要求：

- Python 3.9 或更高版本；
- `git` 已安装并位于 `PATH`；
- 目标 Agent 的 Skill 根目录可读；
- 如果检查远程来源或版本，需要网络访问 GitHub。

安装到 Codex 后，可通过显式 Skill 调用：

```text
$skill-overlap-guard 安装这个 skill https://github.com/owner/repo
```

也可以直接使用自然语言：

```text
安装这个 skill https://github.com/owner/repo
```

## 快速开始

### 查看 Skill 清单和更新状态

```bash
python scripts/inventory.py --check-remote --audit-unclaimed
```

只读预览，不登记未声明来源：

```bash
python scripts/inventory.py --check-remote
```

### 审计存量 Skill 的重叠

```bash
python scripts/duplicate_scan.py audit --top 10
```

结果会按候选分数列出需要语义复核的 Skill 对。语义复核由 Agent 根据两份 `SKILL.md` 的证据完成，不把偶然提到的工具或平台名称当成核心能力。

### 启用 Terminal Guard（可选）

Terminal Guard 默认关闭。启用后，它只拦截 `npx skills add` 并执行 dry-run；普通 `npx` 命令不受影响。

```bash
python scripts/terminal_guard.py enable
python scripts/terminal_guard.py status
python scripts/terminal_guard.py disable
```

启用后请重新打开一个 shell，使 `.zshrc` 中的可逆 guard 生效。

### 记录一条用户决定

```bash
python scripts/decision_registry.py set \
  skill-a skill-b keep_both \
  --relationship complementary \
  --reason "职责互补，保留两个 Skill"
```

可用决定包括：`keep_both`、`ignore`、`preferred_a`、`preferred_b`、`manual_review` 和 `pending`。

## 工作原理

```text
新 Skill 来源
    ↓
读取 SKILL.md / 建立能力画像
    ↓
扫描已安装 Skill / 候选召回
    ↓
语义复核与父子关系保护
    ↓
输出重叠报告
    ↓
用户确认并记录决定
```

关系等级的含义：

- `DUPLICATE`：核心能力和使用范围基本相同；
- `HIGH`：共享核心能力较多，默认应先暂停安装；
- `MEDIUM` / `partial-overlap`：部分能力重叠，但仍有明显差异；
- `LOW` / `complementary`：能力互补，通常可以共存；
- `parent-child`：目录结构上的父子 Skill，不直接判定为重复；
- `uncertain`：证据不足，需要人工判断。

V0.1 的 Dedup Gate 只负责分析、提醒和记录决定。它不会在用户明确确认前自动安装新 Skill，也不会因为发现重叠而自动删除、合并、替换或禁用现有 Skill。

## 扫描范围

默认检查以下位置：

```text
~/.agents/skills/
~/.codex/skills/
当前项目/.agents/skills/
```

默认排除：

```text
~/.codex/skills/.system/
.backup/
.tmp/
缓存目录和临时下载目录
```

每个 Skill 以包含 `SKILL.md` 的目录为单位。嵌套 Skill 会被递归发现，并保留 `parent_skill` / `children` 信息。

## 安全边界

- 所有扫描和查重默认在本地完成；
- Terminal Guard 是显式开启、可随时关闭的 dry-run wrapper；
- 决策登记只写入 `decisions.json`，不改变 Skill 内容；
- 不会自动删除、合并、替换或禁用 Skill；
- 远程来源和更新检查只针对已登记的远程 Skill；
- 使用带登录态的 Agent 或浏览器时，请只对可信来源的 Skill 执行安装前检查。

## 已知限制

- V0.1 的远程来源主要支持 GitHub；
- V0.1 的安装入口以“分析并报告”为主，不在查重完成后自动执行安装；
- 本地编辑不会自动合并到远程版本；
- 插件托管的 Skill 和 Cursor 内置 Skill 不在默认扫描范围内；
- 语义复核依赖 `SKILL.md` 中的可读证据，描述过短或结构不完整时可能返回 `uncertain`；
- 当前实例只扫描其所在 Skills 根目录下的 sibling Skill，不自动汇总 Claude Code、Cursor 和 Codex 的多个根目录。

## 开发与测试

在项目目录运行测试：

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

主要目录：

```text
scripts/      扫描、查重、来源、决策和 Terminal Guard
tests/        V0.1 行为测试
decisions.json 用户决策登记
example*.png  使用示例
```

## 致谢

本项目基于 / 衍生自 [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager)。

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
