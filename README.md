# 离线知识库与决策链管理系统

本项目实现了一个完全离线运行的知识库与决策链管理系统，支持从本地数据库中自动回答工艺问题，记录并检索决策链历史，并对历史决策进行评论评价。系统基于 Python 与 SQLite 实现，可在没有网络的环境中运行，并支持打包为单独的桌面应用。

## 功能特性

- **知识库管理**：添加、浏览工艺知识，支持标签分类。
- **知识维护**：支持查看、编辑、删除知识条目与决策链，保持资料最新。
- **智能问答**：根据本地知识库对输入问题进行匹配，返回相关答案。
- **决策链记录**：保存处理流程/决策链，包含背景、步骤、结果以及标签。
- **历史检索**：按关键词搜索历史决策记录，快速复用经验。
- **评论与评分**：为历史决策添加评论和评分，沉淀团队经验。
- **数据导出**：将全部数据导出为 JSON 文件，便于备份或迁移。
- **本地账户体系**：支持用户自助注册、管理员审批与停用控制。
- **后台管理总览**：提供管理员操作日志与全局统计，方便离线环境下的治理。 

## 快速开始

1. 安装 Python 3.10+。
2. 克隆或下载本仓库，进入项目目录：

   ```bash
   git clone <repo-url>
   cd Yinchuliang
   ```

3. 安装依赖（仅使用标准库，无需额外依赖）。
4. 运行命令行工具：

   ```bash
   python main.py --database my_kb.db add-knowledge "退火工序" "退火炉温度异常如何处理？" "检查温度传感器并重新校准，必要时调整 PID 参数。" --tags "退火,温度"
   python main.py --database my_kb.db ask "退火炉温度异常"
   ```

数据库文件默认保存在 `~/.local/share/offline_kb/knowledge.db`，也可以通过 `--database` 参数自定义位置。

## 主要命令

| 命令 | 说明 |
| ---- | ---- |
| `add-knowledge` | 添加知识条目：标题、问题、答案、标签 |
| `list-knowledge` | 列出知识库中所有条目 |
| `view-knowledge` | 查看单个知识条目的详细信息 |
| `update-knowledge` | 更新知识条目的标题、问题、答案或标签 |
| `delete-knowledge` | 删除指定的知识条目 |
| `ask` | 根据问题自动匹配知识库答案 |
| `add-history` | 保存决策链（背景、步骤、结果、标签） |
| `list-history` | 查看所有决策链及其评论 |
| `view-history` | 查看单条决策链以及评论详情 |
| `update-history` | 更新决策链的标题、背景、步骤、结果或标签 |
| `delete-history` | 删除决策链及其关联评论 |
| `search-history` | 按关键词搜索历史决策 |
| `comment-history` | 对指定决策链添加评论与评分 |
| `register-user` | 注册普通或管理员用户，支持指定执行人 |
| `list-users` | 查看所有用户及状态 |
| `promote-user` / `demote-user` | 授予或移除管理员权限（需要 `--actor`） |
| `activate-user` / `deactivate-user` | 启用或停用用户（需要 `--actor`） |
| `reset-password` | 重置指定用户密码（需要 `--actor`） |
| `change-password` | 用户自助修改密码 |
| `admin-summary` | 查看知识库、决策、用户等全局统计 |
| `admin-log` | 查看管理员操作审计记录 |
| `export` | 将所有数据导出为 JSON |
| `import` | 从 JSON 文件导入知识、决策链和评论 |

运行 `python main.py <command> --help` 可以查看具体参数说明。涉及后台管理的命令（如停用用户、提升管理员等）需使用 `--actor` 参数指定执行人，用于写入审计日志。知识与决策链的编辑命令支持仅更新部分字段，若需要清空标签，可使用 `--tags ""`。

## 打包为离线安装包

为了在目标机器上实现完全离线运行，可以使用 [PyInstaller](https://pyinstaller.org/) 将项目打包为单个可执行文件：

```bash
pip install pyinstaller
pyinstaller --onefile main.py
```

执行后将在 `dist/` 目录生成一个独立的可执行文件，复制到目标机器即可离线运行。若需要图形界面，可在此基础上接入 PyQt、Tkinter 等桌面框架。

如需在多台设备之间同步知识，可结合 `export` 与 `import` 命令：在源设备执行导出命令生成 JSON 文件，再在目标设备执行 `python main.py --database my.db import 导出的文件` 完成批量导入。

## 数据结构

- SQLite 数据库中包含以下数据表：
  - `knowledge`：知识条目（标题、问题、答案、标签、创建时间）。
  - `decision_history`：决策链记录（背景、步骤、结果、标签、创建时间）。
  - `history_comments`：对决策链的评论与评分。
  - `users`：本地账户信息（用户名、密码散列、管理员/启用状态、创建时间）。
  - `admin_events`：后台操作审计日志（执行人、操作、对象、时间戳）。

## 开发与测试

项目仅依赖 Python 标准库，便于在离线环境中维护。建议在提交代码前运行以下命令进行基本检查：

```bash
python -m compileall kb_app main.py
```

## 许可协议

本项目代码示例以 MIT License 发布，可自由使用与二次开发。
