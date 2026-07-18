# Hook 故障排查指南

> 适用版本：Claude Code v2.1.x+
> 最后更新：2026-06-28
> 关联错题本：[[hook-operation-stopped-settings-json]]

---

## 故障现象

- 对话一开始就提示 `Operation stopped by hook`
- 所有工具调用（读文件、写文件、执行命令等）都被 PreToolUse hook 拦截
- 普通聊天回复也可能被拦截
- Claude Code 本体正常启动，但无法执行任何实际操作

```
User: 帮我查下文件
Claude: Operation stopped by hook
```

---

## 原因分析

Claude Code 在每次工具调用前会执行 `settings.json` 中配置的 hooks。当 hooks 配置出现以下任一情况时，PreToolUse hook 会拦截所有操作：

| 原因 | 表现 |
|------|------|
| settings.json 文件损坏 | JSON 解析失败，hook 引擎异常 |
| hook 脚本路径不存在 | 配置指向了已删除/移动的脚本 |
| hook 脚本返回 exit code 2 | 脚本逻辑判定拒绝执行 |
| hook 脚本自身崩溃 | Python/Node 异常导致非零退出 |
| 两个 hook 相互冲突 | 多个 PreToolUse hook 竞争同一操作 |

**最常见但最容易被忽略的原因：settings.json 文件损坏。**

---

## 排查步骤

按以下优先级依次排查，不要跳步：

### 第 1 步：检查 settings.json（最多 30 秒）

```bash
# 查看文件是否可正常解析
python -c "import json; json.load(open(r'$HOME\.claude\settings.json'))" && echo "OK" || echo "DAMAGED"
```

如果输出 `DAMAGED` 或报错 → **直接跳到解决方案 A**。

即使 JSON 解析正常，也可能存在逻辑损坏。快速验证：

```bash
# 重命名 settings.json，让 Claude Code 重新生成
mv ~/.claude/settings.json ~/.claude/settings_old.json
# 重启 Claude Code
```

如果重启后恢复正常 → 确认是 settings.json 的问题。

### 第 2 步：检查 hooks 配置

```bash
# 列出所有配置的 hooks
python -c "
import json
with open(r'$HOME\.claude\settings.json') as f:
    s = json.load(f)
hooks = s.get('hooks', {})
for event, handlers in hooks.items():
    for h in handlers:
        print(f'{event}: {h.get(\"command\", \"???\")}')
"
```

重点检查：
- hook 脚本路径是否存在
- 脚本是否有执行权限
- 是否有重复配置的 hook

### 第 3 步：检查 hook 脚本退出码

```bash
# 手动执行 hook 脚本，看退出码
python ~/.claude/hooks/your-hook-script.py 2>&1
echo "Exit code: $?"
```

- `exit 0` — 正常，允许操作
- `exit 2` — hook 拒绝执行，需要查看脚本逻辑
- 其他非零 — 脚本崩溃

### 第 4 步：检查 pinrule hook

```bash
python ~/.pinrule/pinrule_pre_tool_use.py --help
```

如果脚本能正常运行且输出帮助信息，说明 pinrule 本身没问题。

### 第 5 步：最后才怀疑 API / Python 环境

```bash
python --version
curl -s https://api.deepseek.com/v1/models -H "Authorization: Bearer $DEEPSEEK_API_KEY" | head -20
```

---

## 解决方案

### 方案 A：重置 settings.json（推荐首选）

```bash
# 1. 备份旧文件
mv ~/.claude/settings.json ~/.claude/settings_backup_$(date +%Y%m%d).json

# 2. 重启 Claude Code，自动生成新的 settings.json
# Claude Code 会在启动时创建包含默认配置的新文件

# 3. 恢复需要的自定义配置（从备份文件手动复制）
# 只恢复你明确需要的配置项，不要整文件覆盖

# 4. 确认正常后删除备份
rm ~/.claude/settings_backup_*.json
```

### 方案 B：修复特定 hook

如果确定是某个特定 hook 导致的：

```bash
# 编辑 settings.json，找到问题 hook 并删除或修复
# 只改出问题的那个 hook，不要动其他配置
```

### 方案 C：回滚到已知良好的配置

```bash
# 如果你有备份（D:\ClaudeBackup 或手动备份）
cp /d/ClaudeBackup/settings.json ~/.claude/settings.json
# 重启 Claude Code
```

---

## 预防措施

1. **定期备份 settings.json** — 修改前先 `cp settings.json settings.json.bak`
2. **不要手动编辑 settings.json** — 优先用 `claude config` 命令或 settings 编辑界面
3. **新增 hook 后立刻测试** — 安装任何 hook 后立即验证工具调用是否正常
4. **利用 D:\ClaudeBackup** — 备份脚本已经默认包含 settings.json，确认备份在有效期内
5. **记录每次修改** — 在 `session-live.md` 中记录 settings.json 的变更，方便回滚时定位

---

## 常见误区

| 误区 | 事实 |
|------|------|
| "DeepSeek API 挂了" | DeepSeek 正常，hook 拦截发生在 API 调用之前 |
| "Python 环境坏了" | hook 脚本是独立的，Python 坏的概率远低于配置文件损坏 |
| "pinrule 出 bug 了" | pinrule 只是众多 hook 之一，先查配置层再查脚本层 |
| "需要重装 Claude Code" | 99% 的情况重命名 settings.json 就能解决 |

---

## 快速诊断脚本

将此脚本保存为 `~/.claude/scripts/diagnose-hook.sh`：

```bash
#!/bin/bash
echo "=== Hook 快速诊断 ==="
echo ""

# 1. settings.json 完整性
echo -n "[1/4] settings.json: "
python -c "import json; json.load(open(r'$HOME/.claude/settings.json'))" 2>/dev/null && echo "OK" || echo "DAMAGED or MISSING"

# 2. hooks 数量
echo -n "[2/4] Hook entries: "
python -c "
import json
with open(r'$HOME/.claude/settings.json') as f:
    s = json.load(f)
hooks = s.get('hooks', {})
total = sum(len(v) for v in hooks.values())
print(f'{total} hooks across {len(hooks)} events')
for event, handlers in hooks.items():
    for h in handlers:
        cmd = h.get('command', '???')
        print(f'  {event}: {cmd}')
" 2>/dev/null || echo "CANNOT PARSE"

# 3. Python 环境
echo -n "[3/4] Python: "
python --version 2>&1

# 4. hook 脚本存活
echo "[4/4] Hook scripts:"
for f in ~/.claude/hooks/*.py ~/.pinrule/*.py; do
    if [ -f "$f" ]; then
        python -c "compile(open('$f').read(), '$f', 'exec')" 2>/dev/null && echo "  $f: OK" || echo "  $f: SYNTAX ERROR"
    fi
done

echo ""
echo "=== 诊断完成 ==="
```

---

## 恢复验证清单

恢复后逐项确认：

- [ ] `Operation stopped by hook` 不再出现
- [ ] 工具调用正常（读/写/执行）
- [ ] PIN 验证正常
- [ ] MCP 服务器全部在线
- [ ] 自定义命令生效
- [ ] 恢复的配置项没有遗漏关键功能
