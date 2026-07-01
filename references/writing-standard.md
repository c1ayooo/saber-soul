# 文档写作规范

> 从问题/trade-off 出发 → 因果链 → 安全三棱镜 → 实操验证 → 代码块

## 五条硬性标准（缺一不可）

1. **从问题/trade-off 出发**：不以定义开头。第一句必须是"为什么有这个问题→设计者做了什么 trade-off→为什么现在成了问题"
2. **因果链分析**：不是堆现象，追问条件/前提/链路每一步/触发条件
3. **安全三棱镜**：H3 分三节：🔴攻击面 / 🛡️防御 / 🔍检测
4. **实操验证对应因果链**：针对因果链第 N 步，用命令验证——预期输出是 X，如果看到 Y 则表明存在风险
5. **所有命令在代码块**：block_type=14，标注语言

例外：基础技能文档（Linux/网络/数据库）只需标准 1 + 5。

## CDID 深度标准（Command → Output → Interpret → Decide）

技术流程类文档必须遵循 CDID 结构。这个标准直接来自用户"太浅了"的反馈：

| 环节 | 要求 | 反例 |
|------|------|------|
| Command（命令） | 完整可执行命令，不含占位符 | 只写"用 nmap 扫描"不写参数 |
| Output（执行结果） | 真实的输出示例（终端输出/JSON/HTML），标注关键部分 | 贴了输出不解释 |
| Interpret（解读） | 逐项解释输出中每个关键字段的含义 | 只展示数据不给判断逻辑 |
| Decide（决策） | 根据输出结果给出明确的后续动作：发现什么就停，发现什么就继续 | 展示数据不给结论 |

**检查方法：**找一个没做过这件事的人看文档，如果他能一步不差地复现出来，才算达标。

## HTTP 请求格式

涉及 HTTP 交互时，必须用原始报文格式，禁止 curl：

```http
POST /api/v3/search/quake_service HTTP/1.1
Host: quake.360.net
Content-Type: application/json
X-QuakeToken: ${TOKEN}

{"query": "domain: target.com"}
```

格式：请求行 + 关键请求头 + 空行 + 请求体。响应同理：状态行 + 关键响应头 + 空行 + 响应体。

例外：本地工具操作（文件处理、数据库查询、脚本执行）用 bash 代码块。

## 加密流量文档的特殊要求

当文档涉及加密通信工具（冰蝎、哥斯拉、CS Beacon 等）时，CDID 标准升级为五步：

1. **原始报文** — 展示客户端发出去的加密请求和服务器返回的加密响应
2. **解密后内容** — 展示攻击者客户端解密后看到的明文（如 whoami 返回的 administrator）
3. **三次抓包对比** — 同场景下正常流量 vs 加密工具流量 vs 其他工具流量的差异（如正常页面有 <!DOCTYPE>，冰蝎返回纯 Base64）
4. **判定逻辑** — 几层特征同时出现可确认（如 Accept 头 + POST 体 + 响应体无标签三层确认冰蝎）
5. **误报分析** — 什么场景会触发误报，如何排除

## 格式规则

- 句尾全角句号 `。`，禁止 ASCII `.`
- 逗号/冒号/括号全角（代码块内和 URL 内除外）
- 文件路径用 `inline_code`，不能裸写正文
- `inline_code` 长度 ≤ 120 字符，超长降级为代码块
- H2 用中文编号（一、二、三），H3 用阿拉伯（1. 2. 3.）
- **禁止在源文件中使用管道符表格（Markdown `|` 表格）** — 飞书渲染效果不可靠，必须从源文件杜绝。一律替换为子弹列表：`• **header**: value`。不可依赖 pipeline 自动转换。
- 禁止占位章节（待补充 / TODO）
- 禁止"可能/大概/尝试/看看/应该是/似乎"等模糊词
- 禁止"你会看到什么"、"你将看到"等预设式引导语言——直接写操作步骤即可

## 配图原则

- 所有知识性文档必须配图
- 必须图文结合，内容规划阶段就要设计图的位置
- 拓扑图/流程图用 Excalidraw 手绘风格
- 图片必须裁剪到无空白边
- 不能有 ASCII 字符画代替拓扑图

## 图片插入三步法 + 空块清理

1. 创建空图片块（block_type=27）→ 拿 block_id
2. POST `/drive/v1/medias/upload_all` 上传 PNG（`parent_node=block_id`）→ 拿 file_token
3. PATCH `/docx/v1/documents/{doc_id}/blocks/{block_id}` 设置 `{"replace_image": {"token": file_token}}`

⚠️ 上传失败会残留空图片块。插入后必须扫描文档，删除 token 为空的 type=27 块。

```python
# 扫描文档找出空图片块
items = api_request("GET", f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children?page_size=100").get("items", [])
for i, block in enumerate(items):
    if block.get("block_type") == 27:
        img = block.get("image", {}) or {}
        if not img.get("token", ""):
            api_request("DELETE", f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children/batch_delete",
                       body={"start_index": i, "end_index": i + 1})
```

## 文档类型决策

| 用户意图 | 文档类型 | 归档路径 |
|---------|---------|---------|
| CVE 分析 | 9段模板 | 2.4-威胁情报沉淀 |
| 渗透打点 | 6段模板 | 1.1-作战记录 |
| 工具使用 | 7段模板 | 1.3-渗透工具使用手册 |
| 内网渗透 | 6段模板 | 1.2-内网渗透技巧 |
| 应急响应 | 6段模板 | 2.2-应急响应 |
| 思路整理 | 自由 | 1.5-思路整理 |
