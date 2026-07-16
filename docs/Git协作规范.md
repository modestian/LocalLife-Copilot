# 项目 Git 分支、Commit 与 Push 协作规范

## 1. 文档目的

本规范用于统一项目成员的 Git 操作方式，使分支结构、提交记录和代码变更更加清晰，便于代码审查、问题追踪、版本回退和多人协作。

> 提交代码时，统一使用 `git commit` 进入 Vi 或 Vim 编辑器填写完整提交信息，不建议直接使用 `git commit -m`。

---

## 2. 核心规则

1. 普通功能不要直接在 `main` 分支上开发。
2. 每个相对独立的任务应创建单独分支。
3. 分支名统一使用“小写类型前缀 + `/` + 英文描述”。
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

```text
<类型>/<简短英文描述>
```

示例：

```text
feat/product-compare
fix/login-timeout
docs/deploy-guide
refactor/recommend-service
```

命名要求：

- 类型和描述统一使用小写英文；
- 多个单词使用短横线 `-` 连接；
- 不使用空格、中文、下划线或开发者姓名；
- 分支名称应能直接体现任务内容。

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

如项目使用 Issue 或 Jira，可在分支名中加入任务编号：

```text
feat/123-product-compare
fix/SMART-156-login-timeout
```

---

## 4. 创建任务分支

开始新任务前，先同步基础分支：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/product-compare
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
git push -u origin feat/product-compare
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

## 7. 使用 Vi 编写 Commit Message

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

## 8. Rebase 使用规范

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
git switch feat/product-compare
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

## 9. Push、合并与分支清理

Push 只负责把本地提交上传到远程，不会自动完成合并，也不会自动删除分支。

完整流程：

```text
创建分支 → 开发 → Commit → Push → 创建合并请求 → 审查并合并 → 清理分支
```

Push 后应创建 Pull Request 或 Merge Request，例如：

```text
feat/product-compare → main
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
git branch -d feat/product-compare
```

删除远程分支：

```bash
git push origin --delete feat/product-compare
```

清理失效的远程引用：

```bash
git fetch --prune
```

---

## 10. 多个任务同时存在时

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
git switch -c feat/langchain-opensearch-rag
git add <第一个任务的文件>
git commit
git push -u origin feat/langchain-opensearch-rag

git stash push -u -m "待提交的项目文档"
git switch main
git pull --ff-only origin main
git switch -c docs/update-project-documents
git stash pop
```

如果代码、测试、配置和文档都服务于同一个功能目标，可以放在同一个功能分支中，但仍应检查暂存区和敏感文件。

### 所有修改属于同一个任务的完整示例

适用场景：后端、前端、测试、配置和说明文档共同服务于同一个功能，例如新增商品对比功能。

```bash
# 1. 从最新 `main` 创建任务分支
git switch main
git pull --ff-only origin main
git switch -c feat/product-compare

# 2. 完成开发后检查并暂存
git status
git add backend/app backend/tests
git add frontend/src
git add README.md .env.example
git diff --cached --name-status
git diff --cached

# 3. 提交
git commit
git log -1 --stat
git status

# 4. 同步最新 `main` 并推送
git fetch origin
git rebase origin/main
# 重新运行必要测试
git push -u origin feat/product-compare
git status
```

Commit Message 示例：

```text
feat：新增商品对比功能

1. 新增商品对比接口和业务处理逻辑。
2. 完成商品参数差异展示页面。
3. 增加商品选择数量限制和异常提示。
4. 补充自动化测试、环境配置和使用说明。
```

Push 后创建 Pull Request，将任务分支合并到 `main`。合并完成后清理分支：

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/product-compare
git push origin --delete feat/product-compare
git fetch --prune
```

同一任务可以包含多个相关文件，也可以拆分为少量目标清晰的 Commit，但不要机械拆成大量无意义的小提交。

---

## 11. 常见问题

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
git switch -c feat/product-compare
git status
```

当前未提交修改通常会保留在新分支中。

---

## 12. 提交与 Push 检查清单

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

## 13. 团队统一命令模板

### 新任务首次开发与 Push

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/product-compare

git status
git add <文件或目录>
git diff --cached
git commit
git log -1 --stat
git push -u origin feat/product-compare
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
git branch -d feat/product-compare
git push origin --delete feat/product-compare
git fetch --prune
```

---

## 14. 统一提交示例

```text
分支：feat/product-qa

Commit：
feat：新增商品知识问答功能

1. 新增商品参数查询接口。
2. 接入商品知识检索服务。
3. 增加知识不足时的兜底提示。
```

通过统一分支命名、Commit Message、Rebase、Push 和分支清理流程，可以保持项目历史清晰、修改内容可追溯，并降低多人协作成本。
