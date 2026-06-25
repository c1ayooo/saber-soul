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

## 4. 写入批次上限（45 blocks 会 1770001）

大文档写入时需分批，每批最多 **20 个 blocks**（45+ 返回 `1770001 invalid param`）。

```python
for i in range(0, len(blocks), 20):
    batch = blocks[i:i+20]
    requests.post(f".../children", json={"children": batch, "index": -1})
```

## 5. 分类器子串匹配陷阱

`auto_route()` 的关键词匹配使用 `kw.lower() in text.lower()`（子串匹配），导致：

| 目标词 | 意外触发词 | 影响 |
|--------|-----------|------|
| `EXP` | `exploit`、`exploits` 中的 "exp" | 非 CVE 文档被路由到 2.4 |
| `CVE-` | `CVE-2016-xxxx` 等参考链接 | 同上 |
| `漏洞利用` | 注释中的"内核漏洞利用程序" | 同上 |
| `内核漏洞` | 同上 | `non_24_routes` 重路由到 1.4 |

**处理方式：** 文档内容中避免使用含这些子串的词；或使用 `negative_keywords` 排除。

## 6. 搜索 API 不可用（/search/v2/search 返回 404/非 JSON）

飞书 `/search/v2/search` 端点需要 `search:search` scope 或特定应用权限，多数应用不可用。GET 请求返回 404（非 JSON），导致 `resp.json()` 抛出 `JSONDecodeError: Extra data`。

**修复方法（已合并到 feishu_doc.py）：** `FeishuDoc.search()` 改用 wiki 节点遍历 + 标题模糊匹配：

```python
def search(self, keyword):
    # 遍历根节点
    resp = GET /wiki/v2/spaces/{space_id}/nodes?page_size=100
    for item in items:
        if keyword.lower() in item.get('title','').lower():
            results.append(item)
    # 递归搜索子节点（最多2层）
    self._search_children(..., depth=0)
```

## 7. 分类器权重设计规则

决定文档路由的是 `weight` 字段和规则顺序：

| 规则 | 权重 | 说明 |
|------|:----:|------|
| CVE/2.4 | 3 | 最高，防止被其他规则覆盖 |
| 内网渗透/1.2 | 1 | 默认 |
| 思路整理/1.5 | 1（配合负数词防误判） | 需配合负数词使用 |

**经验：** 如果两个规则同时命中且权重相同，**列表中先出现的规则胜出**。因此：
- 同类文档（如提权类）应当路由到最具体的分类
- 使用 `negative_keywords` 而非提升权重来解决竞争
- 代码技巧综合（"方法论"+"决策树"+"攻击面"）归 1.5，"提权"+"横向移动"归 1.2

## 8. 文档写入标准流程

```python
# 完整写入流程
1. 创建 wiki 节点
   POST /wiki/v2/spaces/{id}/nodes
   {parent_node_token, obj_type:"docx", node_type:"origin", title}

2. 用 ContentParser 解析 markdown → blocks

3. 过滤 divider（type 22，不能做 root children）
   blocks = [b for b in blocks if b.get('block_type') != 22]

4. 分批写入（每批 ≤20）
   POST /docx/v1/documents/{doc}/blocks/{doc}/children
     json={"children": batch, "index": -1}

5. 验证
   GET /docx/v1/documents/{doc}/blocks/{doc}/children?page_size=5
   → 检查 len(items) > 0
```
