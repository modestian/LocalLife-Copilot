# 项目 Git 分支、Commit 与 Push 协作规范

## 1. 文档目的

本规范用于统一项目成员的 Git 操作方式，使分支结构、提交记录和代码变更更加清晰，便于代码审查、问题追踪、版本回退和多人协作。

> 提交代码时，统一使用 `git commit` 进入 Vi 或 Vim 编辑器填写完整提交信息，不建议直接使用 `git commit -m`。

---

## 2. 核心规则

1. 普通功能不要直接在 `main` 分支上开发。
2. 每个相对独立的任务应创建单独分支。
3. 已拆分 Task 的工作，分支名统一使用“小写类型前缀 + `/` + 小写任务编号 + 英文描述”。
4. 一个 Commit 尽量只对应一个明确的修改目标。
5. Commit Message 必须包含标题、空行和具体修改内容。
6. 新分支第一次推送使用 `git push -u origin <分支名>`。
7. Push 前必须检查暂存区，避免提交敏感信息、临时文件和无关修改。
8. 不要随意对公共分支或多人共享分支执行 Rebase 和强制 Push。
9. 功能合并完成后，应及时清理本地和远程分支。

---

## 3. 分支管理

### 3.1 主分支

| 分支 | 用途 |
|---|---|
| `main` | 保存稳定代码，也是所有任务分支的创建基础 |

所有任务统一从最新的 `main` 创建独立任务分支，禁止直接在 `main` 上开发普通功能。

### 3.2 分支命名格式

本项目已经按 Epic → Story → Task 拆分任务。开发分支优先绑定最小可交付的 Task，推荐格式为：

```text
<类型>/<小写 Task ID>-<简短英文描述>
```

例如，`TK-201-01`“定义 DocumentRecord、ChunkRecord 与 Loader/Cleaner/Splitter 端口”的分支名为：

```text
feat/tk-201-01-etl-contracts
```

更多本项目示例：

| 任务 | 推荐分支名 |
|---|---|
| `TK-201-02` 实现六类文件 Loader 和 DataFrame 标准化 | `feat/tk-201-02-file-loaders` |
| `TK-201-06` 编写摄取链路测试 | `test/tk-201-06-ingestion-lifecycle` |
| `TK-202-03` 实现权限安全的双路召回 | `feat/tk-202-03-secure-hybrid-retrieval` |
| 修复 `TK-202-03` 的资源范围过滤缺陷 | `fix/tk-202-03-resource-scope-filter` |

没有对应 Task ID 的临时文档、维护或紧急修复，才使用兼容格式：

```text
<类型>/<简短英文描述>
```

例如：`docs/git-task-branch-naming`。

命名要求：

- 类型和描述统一使用小写英文；
- Task ID 必须与任务分配文档一致，并转换为小写；
- 保留 Task ID 中的短横线，例如使用 `tk-201-01`，不写成 `tk20101`；
- 多个单词使用短横线 `-` 连接；
- 不使用空格、中文、下划线或开发者姓名；
- 英文描述应概括交付物，通常使用 2～5 个单词；
- 一个分支原则上只对应一个 Task，不使用 Epic ID 代替 Task ID；
- 只有工作确实覆盖整个 Story 且无法继续拆分时，才可使用 `st-<编号>`；
- 分支名称应能同时体现任务编号和任务内容。

常用前缀：

| 前缀 | 使用场景 |
|---|---|
| `feat/` | 新增功能、模块、接口或页面 |
| `fix/` | 修复错误或功能缺陷 |
| `docs/` | 修改说明文档 |
| `refactor/` | 重构代码，不改变外部功能 |
| `style/` | 调整格式、排版或命名 |
| `test/` | 新增或完善测试 |
| `perf/` | 性能优化 |
| `chore/` | 依赖、配置或工具调整 |
| `build/` | 构建或打包配置调整 |
| `ci/` | 持续集成或部署配置调整 |
| `revert/` | 撤销某项修改 |

任务编号以 [人员分工任务分配](../project/大众点评AI智能助手-06-人员分工任务分配.md) 为准。分支中的 `tk-201-01`、提交说明和 Pull Request 标题应指向同一个 Task，便于从代码变更反查任务与验收标准。

---

## 4. 创建任务分支

开始新任务前，先同步基础分支：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/tk-201-01-etl-contracts
```

检查当前分支：

```bash
git branch --show-current
git status
```

确认分支正确后再开始开发。

---

## 5. Commit Message 规范

统一格式：

```text
<提交类型>：<工作概括>

1. <具体修改内容一>。
2. <具体修改内容二>。
3. <具体修改内容三>。
```

示例：

```text
feat：新增商品对比功能

1. 新增商品对比接口。
2. 完成商品参数差异展示。
3. 增加最多选择四个商品的限制。
```

格式要求：

- 第一行使用“提交类型 + 中文冒号 + 工作概括”；
- 第二行必须为空；
- 第三行起使用编号说明具体修改；
- 每条内容使用完整中文句子，并以中文句号结尾；
- 标题写整体目标，具体实现放在正文中；
- 不使用 `update`、`change`、`other` 等含义模糊的类型；
- 不同任务关联较弱时，应拆分为多个 Commit。

常用提交类型：

| 类型 | 使用场景 |
|---|---|
| `feat` | 新增功能、接口、页面或业务能力 |
| `fix` | 修复错误、异常或功能缺陷 |
| `docs` | 修改 README、接口文档或说明文件 |
| `refactor` | 调整代码结构，不改变外部功能 |
| `style` | 调整格式、缩进、命名或排版 |
| `test` | 新增或修改测试代码 |
| `perf` | 优化性能、响应速度或资源占用 |
| `chore` | 修改依赖、配置或开发工具 |
| `build` | 修改构建脚本或打包配置 |
| `ci` | 修改自动测试、集成或部署配置 |
| `revert` | 撤销之前的提交 |

---

## 6. 标准开发与提交流程

```bash
# 1. 查看当前状态
git status

# 2. 添加本次需要提交的文件
git add <文件或目录>

# 3. 检查暂存区
git diff --cached

# 4. 提交
git commit

# 5. 检查最近一次提交
git log -1 --stat

# 6. 同步远程更新
git pull --rebase

# 7. 推送
git push
```

新分支第一次推送：

```bash
git push -u origin feat/tk-201-01-etl-contracts
```

建立远程跟踪关系后，后续通常直接执行：

```bash
git push
```

### 暂存文件时的注意事项

优先明确指定文件或目录：

```bash
git add backend/app/api/user.py
git add frontend/src/views/
```

谨慎使用：

```bash
git add .
git add -A
```

提交前必须确认没有包含：

- `.env`、密钥、账号或密码；
- 日志、缓存、临时文件和编译产物；
- 大型数据文件；
- 调试代码、断点或无关修改。

建议通过 `.gitignore` 统一排除不应提交的文件。

---

## 7. Git Hooks 自动质量门禁

### 7.1 Hook 的作用和边界

仓库通过以下受版本控制的脚本统一本地质量门禁：

- `scripts/git_hooks/pre-commit`：创建 Commit 前检查后端 Ruff lint 和 Ruff 格式；
- `scripts/git_hooks/pre-push`：Push 前再次执行 Ruff，并运行完整后端测试及 70% 覆盖率门禁；
- `scripts/install_git_hooks.py`：把上述脚本安装到当前克隆的 `.git/hooks`。

Hook 安装后，日常 Git 命令不变。开发者仍然执行“创建分支 → 修改代码 → `git add` → `git commit` → `git push`”，检查会在对应 Git 命令内部自动触发，不需要每次手动运行 Hook 脚本。

Hook 有以下边界：

- Hook 只负责检查，不会代替开发者创建分支、暂存文件、生成 Commit 或 Push；
- 当前 Hook 检查整个 `backend`，不只检查暂存文件，因此其他未完成的后端改动也可能导致门禁失败；
- 当前 Hook 不执行前端 ESLint、Vitest 和构建，涉及前端的任务仍需按[本地开发与 CI 基线](本地开发与CI.md#本地检查)手动检查，CI 会执行完整前端门禁；
- Hook 不替代 CI，空 MySQL 库迁移、Compose 策略、镜像构建等仍由 CI 验证；
- 不得使用 `--no-verify` 绕过 `pre-commit` 或 `pre-push`。

### 7.2 首次安装前准备

后端开发和 Hook 统一使用 Python 3.13。Windows 推荐使用仓库约定的 `py -3.13`，安装 Hook 前先确认解释器和开发依赖可用：

```powershell
py -3.13 --version
cd backend
py -3.13 -m pip install -e ".[dev]"
cd ..
```

至少应能正常执行：

```powershell
py -3.13 -m ruff --version
py -3.13 -m pytest --version
```

Linux/macOS 可使用 `python3.13`；如果系统没有上述命令，Hook 最后会尝试 PATH 中的 `python`。无论使用哪个命令，都必须确认它实际指向 Python 3.13 且已安装后端开发依赖，避免在 Commit 或 Push 时才发现缺少 Ruff、Pytest 或 pytest-cov。

### 7.3 安装和确认 Hook

每次新 clone 仓库、重新创建 `.git` 目录或发现 `.git/hooks` 中缺少质量 Hook 时，在仓库根目录执行一次。普通 linked worktree 通常共享主克隆的 Git 目录和 Hook，不需要重复安装：

```powershell
py -3.13 scripts/install_git_hooks.py
```

成功时会输出两个安装位置：

```text
Installed pre-commit: <repository>/.git/hooks/pre-commit
Installed pre-push: <repository>/.git/hooks/pre-push
```

可以用 Git 解析实际 Hook 路径并确认文件存在：

```powershell
git rev-parse --path-format=absolute --git-path hooks/pre-commit
git rev-parse --path-format=absolute --git-path hooks/pre-push
```

`.git/hooks` 不进入版本控制，因此仅在一台电脑安装不会自动同步到其他电脑。

安装器不会静默覆盖内容不同的现有 Hook。如果出现 `Refusing to overwrite existing hook`：

1. 比较 `.git/hooks/<hook-name>` 和 `scripts/git_hooks/<hook-name>`；
2. 先备份并确认现有 Hook 是否含个人或其他工具逻辑；
3. 有自定义逻辑时手动合并，保证仓库质量检查仍会执行；
4. 确认旧文件只是上一版仓库 Hook 时，移走旧文件后重新运行安装器。

从远端拉取到 Hook 脚本更新后，也应重新比较并同步本地 `.git/hooks`，不要假设已安装的副本会自动更新。

### 7.4 日常命令之间会发生什么

完整时序如下：

```text
git add <本任务文件>
  └─ 只更新暂存区，不触发当前两个 Hook

git commit
  ├─ 自动执行 pre-commit
  │   ├─ Ruff lint：ruff check .
  │   └─ Ruff 格式检查：ruff format --check .
  ├─ 检查通过：创建 Commit
  └─ 检查失败：取消 Commit，暂存区和工作区保留，修复后重新提交

git push
  ├─ 自动执行 pre-push
  │   ├─ Ruff lint：ruff check .
  │   ├─ Ruff 格式检查：ruff format --check .
  │   └─ 完整 Pytest + 覆盖率：pytest --cov=app --cov-report=term-missing --cov-fail-under=70
  ├─ 检查通过：向远端发送 Commit
  └─ 检查失败：取消 Push，本地 Commit 保留，修复后重新推送
```

常用 Git 命令与当前仓库 Hook 的关系：

| 命令 | 是否触发当前 Hook | 说明 |
| --- | :---: | --- |
| `git switch` / `git branch` | 否 | 只创建或切换分支，仍需开发者主动从最新 `main` 建分支 |
| `git pull` / `git fetch` | 否 | 只同步远端；若拉取到 Hook 脚本更新，需按 7.3 节同步本地副本 |
| `git add` | 否 | 只更新暂存区，提交前仍要主动检查 `git diff --cached` |
| `git commit` | 是 | 在 Commit 写入历史前触发 `pre-commit` |
| `git push` | 是 | 在对象发送到远端前触发 `pre-push` |

因此，正常开发不需要增加新的日常命令：

```powershell
git switch main
git pull --ff-only origin main
git switch -c feat/tk-xxx-xx-description

# 修改代码

git status
git add <本任务文件>
git diff --cached
git commit
git push -u origin feat/tk-xxx-xx-description
```

同一分支第二次及后续 Push 通常只需：

```powershell
git push
```

### 7.5 pre-commit 失败后的处理

常见输出包括 lint 错误、导入顺序错误或 `Would reformat`。可以在 `backend` 目录中复现和修复：

```powershell
cd backend
py -3.13 -m ruff check .
py -3.13 -m ruff format --check .
```

确认是安全的机械修复后，可执行：

```powershell
py -3.13 -m ruff check . --fix
py -3.13 -m ruff format .
```

然后检查格式化是否触及其他任务文件，只重新暂存本任务需要提交的内容：

```powershell
cd ..
git status
git diff
git add <修复后的本任务文件>
git diff --cached
git commit
```

Hook 失败不会创建“半个 Commit”。如果提交日志中没有新记录，修复后重新执行 `git commit` 即可。

### 7.6 pre-push 失败后的处理

Push 被拦截后，本地 Commit 不会丢失，远端也不会收到不完整提交。先根据输出判断失败类型。

代码或测试失败时，在 `backend` 目录复现：

```powershell
cd backend
py -3.13 -m ruff check .
py -3.13 -m ruff format --check .
py -3.13 -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70
```

如果修复产生代码变化，需要创建新的 Commit，然后再次 Push：

```powershell
cd ..
git add <修复文件>
git commit
git push
```

如果只是依赖缺失、临时目录权限、网络或其他本机环境问题，且代码和暂存区没有变化，修复环境后直接重新执行 `git push`，不需要创建空 Commit。

Windows 上若 Pytest 的 `tmp_path` 因默认临时目录权限失败，可先选择一个当前用户可写的专用临时目录，再重试原命令：

```powershell
$gitHookTemp = Join-Path $env:LOCALAPPDATA "LocalLifeCopilot\Temp"
New-Item -ItemType Directory -Force $gitHookTemp | Out-Null
$env:TEMP = $gitHookTemp
$env:TMP = $gitHookTemp
git push
```

该设置只影响当前 PowerShell 会话。不要因为环境问题使用 `git push --no-verify`。

### 7.7 解释器选择规则

两个 Hook 使用相同的解释器选择顺序：

1. PATH 中存在 `py` 且 `py -3.13` 可启动时，使用 `py -3.13`；
2. 否则 PATH 中存在 `python3.13` 时，使用 `python3.13`；
3. 否则使用 PATH 中的 `python`。

选择规则只验证解释器能启动，不会提前验证 Ruff、Pytest 等包是否齐全。因此建议按 7.2 节先安装开发依赖并检查工具版本。团队成员不应通过修改 PATH 刻意跳过某个可用的质量环境；虚拟环境和系统解释器均可使用，但必须是 Python 3.13 且检查结果一致。

### 7.8 Hook 与 CI 的关系

Hook 是本地快速反馈，CI 是远端最终门禁：

| 检查项 | pre-commit | pre-push | CI |
| --- | :---: | :---: | :---: |
| 后端 Ruff lint | 是 | 是 | 是 |
| 后端 Ruff 格式检查 | 是 | 是 | 是 |
| 后端完整 Pytest | 否 | 是 | 是 |
| 后端覆盖率 ≥ 70% | 否 | 是 | 是 |
| 空 MySQL 库 Alembic 迁移 | 否 | 否 | 是 |
| 前端 ESLint、Vitest、生产构建 | 否 | 否 | 是 |
| Compose 策略和镜像构建 | 否 | 否 | 是 |

Push 成功只表示本地 `pre-push` 通过，不代表 Pull Request 的全部 CI 已通过。创建 PR 后仍需等待并检查远端质量门禁。

---

## 8. 使用 Vi 编写 Commit Message

首次使用前可配置编辑器：

```bash
git config --global core.editor "vi"
```

执行：

```bash
git commit
```

进入 Vi 后：

1. 按 `i` 进入插入模式；
2. 输入提交标题；
3. 连续按两次回车，使第二行为空；
4. 从第三行开始填写具体修改内容；
5. 按 `Esc`，输入 `:wq` 并回车，保存退出。

取消本次提交：

```vim
:q!
```

---

## 9. Rebase 使用规范

`git pull --rebase` 会先获取远程最新提交，再把本地尚未推送的提交依次放到最新提交之后，使提交历史更加清晰。

适合使用 Rebase 的情况：

- 尚未 Push 的本地提交；
- 仅由自己维护的任务分支；
- 当前任务分支同步远程更新；
- 将个人任务分支更新到最新 `origin/main`。

需要谨慎或避免使用的情况：

- `main` 等公共分支；
- 多人共同开发的共享分支；
- 无法确认远程是否存在他人提交；
- 可能覆盖他人工作时。

让任务分支基于最新 `main`：

```bash
git switch feat/tk-201-01-etl-contracts
git fetch origin
git rebase origin/main
```

Rebase 完成后应重新运行必要测试。

发生冲突时：

```bash
git status
# 手动解决冲突
git add <已解决的文件>
git rebase --continue
```

放弃本次 Rebase：

```bash
git rebase --abort
```

如果个人分支已经 Push，Rebase 后需要更新远程时，使用：

```bash
git push --force-with-lease
```

不要随意使用：

```bash
git push --force
```

> Rebase 会改变 Commit ID。公共分支和共享分支改写历史前，必须与相关成员确认。

---

## 10. Push、合并与分支清理

Push 只负责把本地提交上传到远程，不会自动完成合并，也不会自动删除分支。

完整流程：

```text
创建分支 → 开发 → Commit → Push → 创建合并请求 → 审查并合并 → 清理分支
```

Push 后应创建 Pull Request 或 Merge Request，例如：

```text
feat/tk-201-01-etl-contracts → main
```

合并前确认：

- 自动测试通过；
- 代码审查完成；
- 冲突已经解决；
- 目标分支选择正确；
- 提交内容与任务范围一致。

合并后清理本地分支：

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/tk-201-01-etl-contracts
```

删除远程分支：

```bash
git push origin --delete feat/tk-201-01-etl-contracts
```

清理失效的远程引用：

```bash
git fetch --prune
```

---

## 11. 多个任务同时存在时

如果工作区同时包含多个相对独立的任务，不要使用 `git add .` 将它们混入同一个 Commit。

推荐做法：

1. 为第一个任务创建分支；
2. 只暂存属于该任务的文件并提交；
3. 使用 `git stash -u` 保存剩余修改；
4. 切换到最新基础分支；
5. 为第二个任务创建新分支；
6. 执行 `git stash pop` 恢复修改；
7. 分别提交并创建独立的合并请求。

示例：

```bash
git switch -c feat/tk-202-03-secure-hybrid-retrieval
git add <第一个任务的文件>
git commit
git push -u origin feat/tk-202-03-secure-hybrid-retrieval

git stash push -u -m "待提交的项目文档"
git switch main
git pull --ff-only origin main
git switch -c docs/git-task-branch-naming
git stash pop
```

如果代码、测试、配置和文档都服务于同一个功能目标，可以放在同一个功能分支中，但仍应检查暂存区和敏感文件。

### 所有修改属于同一个任务的完整示例

适用场景：代码、测试和说明文档共同服务于同一个 Task，例如定义 `TK-201-01` 的 ETL 记录与处理端口。

```bash
# 1. 从最新 `main` 创建任务分支
git switch main
git pull --ff-only origin main
git switch -c feat/tk-201-01-etl-contracts

# 2. 完成开发后检查并暂存
git status
git add backend/app/etl
git add backend/tests/test_etl_contracts.py
git diff --cached --name-status
git diff --cached

# 3. 提交
git commit
git log -1 --stat
git status

# 4. 同步最新 `main` 并推送
git status
git rebase origin/main
# 重新运行必要测试
git push -u origin feat/tk-201-01-etl-contracts
git status
```

Commit Message 示例：

```text
feat：定义知识摄取记录与处理端口

1. 定义 DocumentRecord、ChunkRecord 和清洗状态约束。
2. 定义 Loader、Cleaner、Splitter 可替换处理端口。
3. 补充记录校验与端口契约自动化测试。
```

Push 后创建 Pull Request，将任务分支合并到 `main`。合并完成后清理分支：

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/tk-201-01-etl-contracts
git push origin --delete feat/tk-201-01-etl-contracts
git fetch --prune
```

同一任务可以包含多个相关文件，也可以拆分为少量目标清晰的 Commit，但不要机械拆成大量无意义的小提交。

---

## 12. 常见问题

### Commit Message 写错

尚未 Push：

```bash
git commit --amend
```

已经 Push，且该分支只有自己使用：

```bash
git commit --amend
git push --force-with-lease
```

### 文件误加入暂存区

```bash
git restore --staged <文件名>
```

该命令只取消暂存，不会删除本地修改。

### Push 被拒绝

```bash
git pull --rebase
git push
```

如发生冲突，解决后执行：

```bash
git add <已解决的文件>
git rebase --continue
git push
```

### 分支名写错

尚未 Push：

```bash
git branch -m <新分支名>
```

已经 Push：

```bash
git branch -m <新分支名>
git push -u origin <新分支名>
git push origin --delete <旧分支名>
```

### 错误地在基础分支上开始开发

尚未 Commit 时，可直接创建新分支：

```bash
git switch -c feat/tk-201-01-etl-contracts
git status
```

当前未提交修改通常会保留在新分支中。

---

## 13. 提交与 Push 检查清单

提交前确认：

- [ ] 当前分支和分支名称正确；
- [ ] 本次提交只对应一个明确目标；
- [ ] 已检查 `git diff --cached`；
- [ ] 没有敏感信息、临时文件或无关修改；
- [ ] 没有遗留调试代码；
- [ ] 代码能够正常运行；
- [ ] 必要的测试、接口和文档已同步更新；
- [ ] Commit Message 符合统一格式。

Push 前确认：

- [ ] 最近一次 Commit 内容正确；
- [ ] 当前分支不是误操作的 `main`；
- [ ] 已同步远程最新提交；
- [ ] 必要测试已经通过；
- [ ] 第一次 Push 使用了 `-u`；
- [ ] 不会改写或覆盖其他成员的提交历史。

---

## 14. 团队统一命令模板

### 新任务首次开发与 Push

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/tk-201-01-etl-contracts

git status
git add <文件或目录>
git diff --cached
git commit
git log -1 --stat
git push -u origin feat/tk-201-01-etl-contracts
git status
```

### 同一任务后续提交

```bash
git status
git add <文件或目录>
git diff --cached
git commit
git log -1 --stat
git pull --rebase
# 重新运行必要测试
git push
git status
```

### 合并后清理分支

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/tk-201-01-etl-contracts
git push origin --delete feat/tk-201-01-etl-contracts
git fetch --prune
```

---

## 15. 统一提交示例

```text
分支：feat/tk-201-01-etl-contracts

Commit：
feat：定义知识摄取记录与处理端口

1. 定义 DocumentRecord、ChunkRecord 和清洗状态约束。
2. 定义 Loader、Cleaner、Splitter 可替换处理端口。
3. 补充记录校验与端口契约自动化测试。
```

通过统一分支命名、Commit Message、Rebase、Push 和分支清理流程，可以保持项目历史清晰、修改内容可追溯，并降低多人协作成本。
