# Git 提交与推送示例

## 1. 使用说明

本文提供可复制的 Git 操作示例，适用于已经阅读并遵守 [Git 协作规范](Git协作规范.md) 的开发者。分支命名、Commit Message、Rebase、Hook 和禁止强制 Push 等规则以主规范为准。

示例默认条件：

- 命令在仓库根目录执行；
- Git Hooks 已按[自动质量门禁说明](Git协作规范.md#7-git-hooks-自动质量门禁)安装；
- Python 3.13 和后端开发依赖已经准备完成；
- `<...>` 是占位符，执行时必须替换为真实值，不要原样复制；
- 每次只提交当前 Task 的文件，不使用 `git add .` 混入其他任务。

## 2. 新任务首次开发、提交和推送

以下示例以 `TK-201-01` 为例。

### 2.1 从最新 main 创建任务分支

```powershell
git switch main
git pull --ff-only origin main
git switch -c feat/tk-201-01-etl-contracts
git status
```

预期结果：

- 当前分支为 `feat/tk-201-01-etl-contracts`；
- 分支基于最新 `origin/main`；
- 普通功能没有直接提交到 `main`。

### 2.2 修改完成后检查和暂存

```powershell
git status
git diff

git add backend/app/etl
git add backend/tests/test_etl_contracts.py

git diff --cached --name-status
git diff --cached
```

提交前确认暂存区只包含当前 Task 的代码、测试和必要文档，不包含 `.env`、密钥、日志、缓存、构建产物或其他人的未完成修改。

### 2.3 创建 Commit

```powershell
git commit
```

执行 `git commit` 后，`pre-commit` 会自动运行 Ruff lint 和格式检查：

- 检查通过：进入编辑器填写 Commit Message，保存后创建 Commit；
- 检查失败：Commit 不会创建，按输出修复后重新暂存并再次执行 `git commit`。

提交完成后检查：

```powershell
git log -1 --stat
git status
```

Commit Message 示例：

```text
feat：定义知识摄取记录与处理端口

1. 定义 DocumentRecord、ChunkRecord 和清洗状态约束。
2. 定义 Loader、Cleaner、Splitter 可替换处理端口。
3. 补充记录校验与端口契约自动化测试。
```

### 2.4 推送前同步最新 main

```powershell
git fetch origin
git rebase origin/main
```

如果发生冲突，先查看状态并解决冲突：

```powershell
git status
git add <已解决的文件>
git rebase --continue
```

无法安全解决时可以放弃本次 Rebase：

```powershell
git rebase --abort
```

Rebase 完成后重新运行与任务风险相匹配的必要测试。

### 2.5 首次推送任务分支

```powershell
git push -u origin feat/tk-201-01-etl-contracts
```

执行 `git push` 后，`pre-push` 会自动运行：

1. Ruff lint；
2. Ruff 格式检查；
3. 完整后端 Pytest；
4. 后端覆盖率 70% 门禁。

检查通过后才会向远端发送 Commit。最后确认本地与远端同步：

```powershell
git status
git rev-list --left-right --count '@{upstream}'...HEAD
```

预期 ahead/behind 为：

```text
0  0
```

## 3. 同一任务分支后续提交

分支已经建立远端跟踪关系后：

```powershell
git status
git diff
git add <本次修改的文件或目录>
git diff --cached --name-status
git diff --cached
git commit
git log -1 --stat

git fetch origin
git rebase origin/main
# 重新运行必要测试
git push
git status
```

只由自己维护且尚未 Push 的提交适合 Rebase。已经与他人共享的分支不要擅自改写历史。

## 4. 纯文档任务示例

没有对应 Task ID 的独立文档任务使用 `docs/` 前缀：

```powershell
git switch main
git pull --ff-only origin main
git switch -c docs/git-hooks-workflow

# 修改文档

git status
git add docs/development/Git协作规范.md
git add docs/development/本地开发与CI.md
git diff --cached
git commit

git fetch origin
git rebase origin/main
git push -u origin docs/git-hooks-workflow
```

Commit Message 示例：

```text
docs：完善 Git Hooks 提交与推送流程

1. 补充 Hook 安装、触发时序和检查范围说明。
2. 增加解释器选择与 Windows 临时目录排障步骤。
3. 独立整理首次提交、后续提交和分支清理示例。
```

## 5. pre-commit 失败示例

如果输出 `No module named ruff`，先确认 Hook 实际选择的解释器。Windows 上即使提示符显示 `(.venv)`，PATH 中可用的 `py -3.13` 仍具有更高优先级：

```powershell
Get-Command py -ErrorAction SilentlyContinue
Get-Command python
py -3.13 --version
python --version
```

有 `py -3.13` 时，在对应解释器中安装依赖：

```powershell
cd backend
py -3.13 -m pip install -e ".[dev]"
py -3.13 -m ruff --version
cd ..
git commit
```

没有 `py`、但已激活 Python 3.13 虚拟环境时：

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m ruff --version
cd ..
git commit
```

如果 Ruff 报告代码或格式问题：

```powershell
cd backend
python -m ruff check .
python -m ruff format --check .
```

确认修复安全后再执行 `--fix` 或格式化，随后检查 diff、重新暂存并 Commit。不得使用 `git commit --no-verify`。

## 6. pre-push 临时目录权限失败示例

典型错误：

```text
PermissionError: [WinError 5] 拒绝访问：...\Temp\pytest-of-<username>
```

即使摘要中已有数百个 `passed`，只要结尾存在 `ERROR`，Push 就没有发生。本地 Commit 仍然安全保留，不需要重新 `git add` 或创建空 Commit。

在当前 PowerShell 会话设置项目专用临时目录：

```powershell
$gitHookTemp = Join-Path $env:LOCALAPPDATA "LocalLifeCopilot\Temp"
New-Item -ItemType Directory -Force -Path $gitHookTemp | Out-Null
$env:TEMP = $gitHookTemp
$env:TMP = $gitHookTemp
python -c "import tempfile; print(tempfile.gettempdir())"
```

确认打印的是新目录后，直接重试：

```powershell
git push
```

首次推送尚未建立跟踪关系时重试原命令：

```powershell
git push -u origin <当前分支名>
```

不要使用 `git push --no-verify`。

## 7. 错误地在 main 上开始修改

尚未 Commit 时，直接创建正确的任务分支，工作区修改通常会被保留：

```powershell
git switch -c feat/tk-xxx-xx-description
git status
```

然后按本文第 2.2 节开始检查和暂存，不要先在 `main` 创建 Commit。

## 8. 暂存了无关文件

只取消暂存，不删除工作区修改：

```powershell
git restore --staged <误暂存文件>
git status
git diff --cached
```

## 9. Push 被远端拒绝

先同步并检查是否存在远端更新：

```powershell
git fetch origin
git status
```

个人任务分支可以根据实际情况执行：

```powershell
git rebase origin/main
# 解决冲突并重新运行必要测试
git push
```

不要直接使用 `git push --force`。只有确认分支由自己独占、且 Rebase 改写了已经 Push 的提交时，才使用 `git push --force-with-lease`。

## 10. Push 后创建 Pull Request

在代码托管平台创建：

```text
<任务分支> → main
```

确认目标分支是 `main`，PR 标题和 Task ID 一致，并等待以下检查通过：

- 自动测试和覆盖率；
- 代码审查；
- 冲突检查；
- CI 中本地 Hook 未覆盖的迁移、前端、Compose 和镜像检查。

## 11. 合并后清理分支

确认 PR 已经合并后：

```powershell
git switch main
git pull --ff-only origin main
git branch -d <已合并任务分支>
git push origin --delete <已合并任务分支>
git fetch --prune
```

删除前必须确认分支已合并且不再需要，不要对未合并分支使用强制删除。

## 12. 完整流程速查

```text
同步 main
  → 创建任务分支
  → 修改代码
  → 检查工作区
  → 明确暂存本任务文件
  → 检查暂存区
  → git commit（自动 pre-commit）
  → 检查 Commit
  → fetch + rebase origin/main
  → 重新运行必要测试
  → git push（自动 pre-push）
  → 创建 PR
  → CI 与审查通过
  → 合并
  → 清理本地和远端任务分支
```
