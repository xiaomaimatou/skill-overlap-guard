# Skill Overlap Guard

Skill 防重助手

**安装前先查重，避免 Skill 越装越重复。**

Check before you install. Avoid redundant Agent Skills.

## Why

Skill 越装越多，很难知道新 Skill 是否已经被现有能力覆盖。

## What it does

- 安装前功能查重
- 存量 Skill overlap audit
- `HIGH` / `partial` / `complementary` 判断
- 中英文语义匹配
- Codex 自然语言安装前检查
- Terminal `npx skills add` Guard
- Decision Registry

## Safety

- 不自动删除
- 不自动合并
- 不自动替换
- 不自动禁用
- 修改存量 Skill 必须用户明确授权

## Install

将仓库克隆到 Agent Skills 根目录：

```bash
git clone https://github.com/EfanWang/skill-overlap-guard.git
```

运行环境：Python 3.9+，并确保 `git` 在 PATH 中。

## Usage

Codex：

```text
$skill-overlap-guard 安装这个 skill https://github.com/owner/repo
```

自然语言：

```text
安装这个 skill https://github.com/xxx
```

Terminal：

```text
npx skills add owner/repo
```

Terminal Guard 默认关闭。如需可逆的 dry-run 检查，可显式启用：

```bash
python scripts/terminal_guard.py enable
python scripts/terminal_guard.py status
python scripts/terminal_guard.py disable
```

## How it works

```text
Source
  → Inventory
  → Recall
  → Semantic Review
  → Overlap Warning
  → User Confirmation
```

v0.1 只报告重叠结果；未经用户明确确认，不会安装 Skill。

## Status

v0.1.0 MVP

## Known Limitations

- 目前只支持 GitHub 远程来源。
- v0.1 只报告安装决策，不执行安装。
- 不自动合并本地编辑。
- 插件托管 Skill 和 Cursor 内置 Skill 不在扫描范围内。

## Credits

基于 / 衍生自 [EfanWang/skills-manager](https://github.com/EfanWang/skills-manager)。

保留 MIT License 和原作者版权声明，详见 [LICENSE](LICENSE)。
