# WSL Gateway 运维笔记

## 重启命令的风险

`hermes gateway restart` 在 WSL 上可能**静默失效**：

1. 命令发送 SIGTERM 给当前进程
2. 旧进程开始 draining（等待活跃 agent 结束）
3. 新进程启动，但被 `hermes gateway restart` 的第二阶段 SIGTERM 也杀死
4. 结果：旧进程已死、新进程没活下来、飞书断开

**症状**：`hermes gateway status` 显示 running，但日志最终停在 `Received SIGTERM — initiating shutdown`，没有 `✓ feishu connected`。

## 可靠恢复步骤

```bash
# 1. 先确认状态
hermes gateway status

# 2. 查看最新日志 - 检查是否有 feishu connected
tail -5 ~/.hermes/logs/gateway.log
# 应该看到: ✓ feishu connected

# 3. 如果网关假死，杀死旧 tmux 会话
tmux kill-session -t hermes-gateway
# 或用 PID
kill <PID>

# 4. 确认旧进程已消失
ps aux | grep "hermes gateway" | grep -v grep
# 应返回空

# 5. 重新启动
tmux new-session -d -s hermes-gateway "hermes gateway run"

# 6. 等待几秒，确认 feishu 连接
sleep 8 && tail -10 ~/.hermes/logs/gateway.log | grep "feishu connected"
```

## 验证检查清单

**重启后必须检查**，不能只看 `gateway status`：

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| 进程存在 | `ps aux \| grep gateway` | 有 tmux 进程 |
| 飞书连接 | `tail ~/.hermes/logs/gateway.log \| grep feishu` | `✓ feishu connected` |
| 无错误 | `tail ~/.hermes/logs/gateway.log \| grep -i error` | 空 |
| 无 SIGTERM | `tail ~/.hermes/logs/gateway.log \| grep SIGTERM` | 仅限旧会话，新会话没有 |

## WSL 背景

- WSL 上推荐手动模式（`hermes gateway run` + tmux）
- `hermes gateway install`（systemd）在 WSL 需要 `/etc/wsl.conf` 中 `systemd=true`
- WSL 重启后 tmux 会话丢失，需重新 `tmux new-session -d -s hermes-gateway "hermes gateway run"`
