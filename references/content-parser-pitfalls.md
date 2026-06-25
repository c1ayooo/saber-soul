# ContentParser Block Format Pitfalls

## 1. 标题块 key 必须是字符串名，不是数字

```python
# ❌ 错误：用数字 level 做 key
{"block_type": 4, 4: {"elements": [...]}}  # → 1770001 invalid param

# ✅ 正确：用 heading1~heading6 做 key
{"block_type": 4, "heading2": {"elements": [...]}}
```

| block_type | key | 示例 |
|-----------|-----|------|
| 3 | heading1 | `# 标题` |
| 4 | heading2 | `## 标题` |
| 5 | heading3 | `### 标题` |
| 6 | heading4 | `#### 标题` |
| 7 | heading5 | `##### 标题` |
| 8 | heading6 | `###### 标题` |

**修复方法：** `_make_heading()` 中加映射 `{3:"heading1", 4:"heading2", ...}`

## 2. 子弹列表/有序列表 key 必须对应 block_type

```python
# ❌ 错误：全部用 "text" 做 key
{"block_type": 12, "text": {...}}  # → 1770001 invalid param

# ✅ 正确：type 12 → "bullet", type 13 → "ordered"
{"block_type": 12, "bullet": {"elements": [...]}}
{"block_type": 13, "ordered": {"elements": [...]}}
```

**修复方法：** `_make_text_block()` 中映射 `{12: "bullet", 13: "ordered", 2: "text"}`

## 3. 分隔线（type 22）不可作为根级 children

`block_type: 22` 的 divider 块不能直接 POST 为 `doc_token` 的 children。返回 `1770001 invalid param`。

**处理方式：** 解析阶段直接跳过 `---`，不在 blocks 中生成 divider。

## 4. 分类器子串匹配陷阱

`auto_route()` 的关键词匹配使用 `kw.lower() in text.lower()`（子串匹配），导致：

| 目标词 | 意外触发词 | 影响 |
|--------|-----------|------|
| `EXP` | `exploit`、`exploits` 中的 "exp" | 非 CVE 文档被路由到 2.4 |
| `CVE-` | `CVE-2016-xxxx` 等参考链接 | 同上 |
| `漏洞利用` | 注释中的"内核漏洞利用程序" | 同上 |
| `内核漏洞` | 同上 | `non_24_routes` 重路由到 1.4 |

**处理方式：** 文档内容中避免使用含这些子串的词；或使用 `negative_keywords` 排除。
