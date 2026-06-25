# 格式规则详细版

## 代码块 vs 行内代码 vs 正文

| 内容 | 格式 | 示例 |
|------|------|------|
| 多行命令/配置/代码 | 代码块 `block_type=14`，标注语言 | ````bash\nnmap -sV target\n```` |
| HTTP 请求/响应 | `http` 代码块 | ````http\nPOST /api HTTP/1.1\n```` |
| 行内工具名/参数/配置项 | `inline_code` | `nmap`、`--script`、`server.conf` |
| 文件/目录路径 | `inline_code` | `~/.hermes/.env`、`/etc/nginx/` |
| 变量/函数/字段名 | `inline_code` | `tenant_access_token`、`block_type` |
| CVE 编号 | `inline_code` | `CVE-2026-20253` |
| CVSS 评分值 | `inline_code` | `9.8` |
| HTTP 方法 | `inline_code` | `POST`、`GET` |
| 协议/端口/版本号 | `inline_code` | `HTTP/1.1`、`:8000`、`10.2.4` |
| 配置指令/字段名 | `inline_code` | `disabled = true`、`server.conf` |
| 组件/产品名 | **正文（无格式）** | Splunk Enterprise、Tomcat、Nginx |
| 漏洞类型名 | **正文（无格式）** | SQL注入、XSS、SSRF、RCE |
| 技术概念名 | **正文（无格式）** | 反序列化、沙箱逃逸 |
| 普通叙述 | **正文（无格式）** | 攻击者通过未授权接口写入恶意文件 |

**判断边界：** 有代码语义的标识符 → inline_code；自然语言名词（产品/漏洞类型/攻击手法）→ 正文无格式。

**禁止：** 命令裸写正文中（如"用 nmap -sV 扫描"→ 应写"用 `nmap` 扫描，完整命令见代码块"）  
**禁止：** 过度使用 inline_code（如"`SQL注入` 是一种 `Web` 漏洞"→ 错）

## Bold 处理
飞书写入**支持** `**bold**` 解析为加粗，**不要清理**。

## 管道符表格
写入阶段自动转子弹列表，源文件保留管道符即可。

## 分割线
`---` → block_type=22，可用，建议节制。

## 有序列表
12=bullet（无序），13=ordered（有序）。

## 长破折号
禁止 U+2014 em dash `—`，统一用两个半角 `--`。

## HTTP 请求格式（强制）

涉及 HTTP 交互时，代码块**必须**使用原始 HTTP 报文格式，**禁止**用 curl 命令。

✅ 正确：
```http
POST /api/v3/search/quake_service HTTP/1.1
Host: quake.360.net
Content-Type: application/json
X-QuakeToken: ${QUAKE_KEY}

{"query": "service:\"Splunk\"", "start": 0, "size": 5}
```

❌ 禁止：
```bash
curl -s -X POST "https://..." -H "X-QuakeToken: xxx" -d '{...}'
```

规则：
- 请求：请求行 + 关键头 + 空行 + 请求体
- 响应：状态行 + 关键头 + 空行 + 响应体（过长截断标注）
- 多步骤逐一展示每个请求/响应对
- 例外：本地工具操作（文件/数据库/脚本）用 `bash` 代码块

## 标点符号（强制）
- 句尾用 `。`，禁止 ASCII 句号 `.`
- 正文逗号用 `，`，冒号用 `：`，括号用 `（）`（代码块内除外）

## 文件路径
非代码块文本中必须用 `inline_code` 格式，不能裸写。

## inline_code 长度
≤ 120 字符，超长降级为代码块（block_type=14）。

## 标题编号
H2 用中文编号（一、二、三），H3 用阿拉伯编号（1. 2. 3.）。
