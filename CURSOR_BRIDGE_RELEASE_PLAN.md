# Cursor Bridge v1.9 — 开源发布框架

> 先看这个，别急着发布。每项确认后再动手。

---

## 当前状态审计

| 项目 | 现状 |
|------|------|
| 代码 | `cursor_bridge.pyw` 单文件 1479 行 |
| 版本 | 代码内 `v1.8`，commit message `v1.9` — **不一致，需统一** |
| 文档 | ❌ 无 README |
| 许可证 | ❌ 无 LICENSE |
| .gitignore | ❌ 无 |
| 测试 | 有 17 个内联测试，无独立测试文件 |
| CI/CD | ❌ 无 |
| 贡献指南 | ❌ 无 |
| Git 历史 | 单 commit `e4b6bbf`，推到 claude-config 私有仓库 |
| 依赖 | Python 3 stdlib only (tkinter + ctypes)，零第三方依赖 |
| 语言 | 中文注释，面向中文用户 |

---

## 第一阶段：发布前必须做（硬性要求）

### 1. 修复版本号不一致

```
代码内:  "=== Cursor Bridge v1.8 启动 ==="
commit:  "v1.9: fix ASCII-to-CJK garbled text"
```

统一为 `v1.0.0`（首次公开发布用 1.0.0 而非 1.9）。

### 2. LICENSE

**推荐 MIT** — Cursor Bridge 是工具类项目，MIT 最大化采用率。

- [ ] 在仓库根目录创建 `LICENSE` 文件
- [ ] README 中加许可证 badge
- [ ] 代码文件头部加 SPDX 标识：`# SPDX-License-Identifier: MIT`

MIT vs Apache 2.0 vs GPL：
- **MIT**：谁都能用，闭源商用都行，只要求保留版权声明。工具类项目首选。
- **Apache 2.0**：MIT + 专利保护。如果你担心别人申请相关专利反诉你。
- **GPL**：copyleft，用了你的代码就必须开源。对工具类项目太重。

### 3. README.md（英文）

必须包含：

```markdown
# Cursor Bridge

> Fix CJK text encoding when pasting into Cursor editor

## What it does
一句话：从任何地方复制中文 → Cursor Bridge 自动修复编码 → 粘贴到 Cursor 不乱码

## Features
- Auto clipboard monitor (500ms poll)
- Win+Shift+V manual hotkey
- System tray icon with context menu
- Popup window with dark Slate theme
- Two encoding recovery patterns (Pattern A + Pattern B)
- Zero dependencies (Python 3 stdlib only)

## Installation
```bash
# 1. Download cursor_bridge.pyw
# 2. Run it
pythonw cursor_bridge.pyw

# Auto-start: put cursor_bridge-startup.vbs in Startup folder
```

## How it works
简短技术说明 + 一张截图/GIF

## Tech Stack
Python 3, tkinter, ctypes, Win32 API

## Contributing
See CONTRIBUTING.md

## License
MIT — see LICENSE file
```

**要点：**
- 英文写（全球受众）
- 第一屏必须说清楚"这是什么、怎么装、能用吗"
- 放一张截图（托盘图标 + 弹窗）
- Badge 行：license、python version、status

### 4. .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.pyo
*.egg-info/
dist/
build/

# Virtual environments
venv/
.env

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Project specific
*.log
bridge_debug.log
```

### 5. 安全审计

- [ ] 扫描整个 git 历史是否有硬编码的路径/用户名/密钥
- [ ] `cursor_bridge.pyw` 里有没有个人路径（如 `C:\Users\Harry\...`）
- [ ] `.dropped.json` 确保不会误提交

当前代码里 `github.com/winter2815651645-collab/cursor-bridge` 已经写死 — 确认 `winter2815651645-collab` 是你的目标 GitHub 用户名。

### 6. GitHub 仓库设置

- [ ] 创建新仓库 `winter2815651645-collab/cursor-bridge`（Public）
- [ ] Description: `Windows clipboard bridge that fixes CJK text encoding for Cursor editor`
- [ ] Topics: `python`, `cursor`, `clipboard`, `cjk`, `encoding`, `windows`, `tkinter`, `win32-api`
- [ ] 不要勾选 "Initialize with README"（已有本地仓库）
- [ ] 推代码：`git remote add origin https://github.com/winter2815651645-collab/cursor-bridge.git && git push -u origin main`
- [ ] Settings → 勾选 "Discussions"（可选，小项目可以先不开）
- [ ] Settings → Branches → 加 branch protection rule（require PR for main）

---

## 第二阶段：强烈建议做

### 7. 项目结构重组

当前：
```
cursor-bridge/
└── cursor_bridge.pyw
```

建议：
```
cursor-bridge/
├── cursor_bridge.pyw          # 主程序
├── README.md
├── LICENSE
├── .gitignore
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── cursor-bridge-startup.vbs  # 开机自启脚本
├── tests/
│   └── test_cursor_bridge.py  # 17 个测试移到这里
└── .github/
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   └── feature_request.md
    └── workflows/
        └── test.yml           # GitHub Actions CI
```

### 8. 拆分测试

目前 17 个测试在 `if __name__ == "__main__"` 块里。建议：
- 提取到 `tests/test_cursor_bridge.py`
- 用 pytest 或 unittest 跑
- CI 里自动跑

### 9. GitHub Actions CI

最小可用的 `.github/workflows/test.yml`：

```yaml
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Run tests
        run: python tests/test_cursor_bridge.py
```

注意：Windows runner 才能跑 Win32 API 测试。Linux/macOS runner 会失败。

### 10. CONTRIBUTING.md

```markdown
# Contributing to Cursor Bridge

## Setup
1. Clone the repo
2. Python 3.10+ required
3. No dependencies — just run `pythonw cursor_bridge.pyw`

## Testing
```bash
python tests/test_cursor_bridge.py
```

## Pull Requests
1. Fork + branch
2. Add tests for new features
3. Run tests before submitting
4. Keep it simple — pure stdlib

## Code Style
- Follow PEP 8
- Comments in English (for public repo)
```

### 11. CODE_OF_CONDUCT.md

直接用 Contributor Covenant 2.1 模板。GitHub 新建文件时选 "Choose a code of conduct template"。

### 12. CHANGELOG.md

```markdown
# Changelog

## [1.0.0] - 2026-07-09
### Added
- Initial public release
- Auto clipboard monitor with 500ms polling
- Win+Shift+V global hotkey
- System tray icon with context menu
- Popup window with dark Slate theme
- Pattern A: byte-expanded UTF-8 in UTF-16LE recovery
- Pattern B: raw UTF-8 bytes in CF_UNICODETEXT recovery
- Alpha ratio guard (50%) for Pattern B safety
- 17 unit tests
```

### 13. 注释英文化？

当前代码全是中文注释。两个选择：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保持中文 | 零工作量，面向中文用户清晰 | 老外看不懂 |
| 翻译成英文 | 国际化，GitHub 上更专业 | 工作量大（1479行） |

**建议：** 先保持中文发布，README 用英文写清楚就行。代码注释后期逐步翻译。

---

## 第三阶段：锦上添花（发布后可做）

### 14. 加 Badge 到 README

```
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
```

### 15. 截图/GIF

用 ScreenToGif 录一段：复制中文 → Cursor 粘贴乱码 → Bridge 修复 → 粘贴正常。

放在 README 的 "How it works" 下面。

### 16. SECURITY.md

小项目不是必须的，但写了显得专业：

```markdown
# Security Policy

## Reporting a Vulnerability
Email [your-email] — do not open a public issue.
Response within 48 hours.
```

### 17. PyPI 发布？

Cursor Bridge 是 `.pyw` 单文件，不适合发 PyPI。但如果想，可以加 `pyproject.toml`：

```toml
[project]
name = "cursor-bridge"
version = "1.0.0"
requires-python = ">=3.10"
```

### 18. GitHub Sponsors

`.github/FUNDING.yml`：
```yaml
github: [winter2815651645-collab]
```

---

## 发布当天操作顺序

1. 修复版本号 `v1.8` → `v1.0.0`
2. 创建 `LICENSE` (MIT)
3. 写 `README.md`
4. 创建 `.gitignore`
5. 安全审计（扫 git diff、扫硬编码路径）
6. Commit 所有文件
7. 在 GitHub 上创建 `winter2815651645-collab/cursor-bridge` 公开仓库
8. Push
9. 仓库 Settings → Description + Topics + Branch protection
10. Tag `v1.0.0` + Create Release
11. 把链接发到相关社区（Cursor 论坛、V2EX、Reddit r/cursor）

---

## 常见发布错误（不要犯）

| 错误 | Cursor Bridge 的情况 |
|------|---------------------|
| 没有 LICENSE | ❌ 当前没有 |
| README 写得太简略或太啰嗦 | ❌ 当前没有 |
| 没放截图，用户不知道长什么样 | ❌ 需要补 |
| 没测试，CI 不跑 | ❌ 17 个测试需要放到 CI |
| git 历史里有密码/密钥 | ⚠️ 需审计 |
| 版本号混乱 | ❌ v1.8/v1.9 不一致 |
| 一上来就追求完美文档 | ✅ 单文件工具，README 写好就够了 |
| 发了就不管了 | ⚠️ Issue 要及时回 |

---

## 一句话总结

> Cursor Bridge 是单文件零依赖工具，发布门槛极低。**最少要做：LICENSE + README.md + .gitignore + 修复版本号。** 这四项做完就可以发布。剩下的逐步补。
