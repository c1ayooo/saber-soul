# Pipeline 常见坑与修复

## 1. 搜索 API SSL 错误（mihomo 代理）

**现象**：`pipeline.py write` 在 Step 2 Dedup 阶段报 `SSLEOFError` / `SSL: UNEXPECTED_EOF_WHILE_READING`。

**原因**：mihomo 代理对飞书 `/search/v2/search` API 的不稳定 TLS 处理。

**状态**：已修复（2026-06-25）。`lib/feishu_doc.py` 的 `search()` 方法现在用 try/except 包裹整个 HTTP 请求，失败时输出警告并返回空列表，不阻断流水线。

## 2. 2.4 子目录标题匹配失败

**现象**：`auto_classifier.py` 报 `未找到 2.4 子目录: Web应用系统漏洞`。

**原因**：wiki 节点标题为 `2.4.2 Web应用系统漏洞`（带编号前缀），但 `_get_subdir_token()` 使用精确匹配 `item.get("title") == subdir_name`（`subdir_name` = `Web应用系统漏洞`，无前缀）。

**状态**：已修复（2026-06-25）。改为 `title == subdir_name or subdir_name in title`。

## 3. classification_config.json 缺失

**现象**：所有文档被路由到 99-待分类（`关键词未命中且无 LLM 回调，返回 99-待分类`）。

**原因**：`lib/config.py` 从 `CONFIG_DIR/references/classification_config.json` 加载分类规则。`CONFIG_DIR` 默认是 `SABER_CONFIG_DIR` 或 `~/.hermes/skills/saber_soul`，但该目录下无 `references/classification_config.json`。

**修复**：
```bash
mkdir -p ~/.hermes/skills/saber_soul/references
ln -sf ~/saber-soul/references/classification_config.json \
  ~/.hermes/skills/saber_soul/references/classification_config.json
```

## 4. pipeline.py 运行时缺少 `import re`

**现象**：`pipeline.py write` 直接报 `NameError: 're' is not defined`。

**状态**：已修复（2026-06-25）。`scripts/pipeline.py` 补了 `import re`。

## 5. feishu_doc.py 跨模块导入失败

**现象**：`__import__("saber_soul.lib.feishu_auth", fromlist=[...])` 在非标准 `PYTHONPATH` 下失败。

**状态**：已修复（2026-06-25）。改为标准相对导入 `from .feishu_auth import get_tenant_access_token`。
