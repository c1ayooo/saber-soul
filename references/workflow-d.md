# 工作流 D：流量特征/威胁检测文档写作规范

用于响应"写 XX 工具的流量特征"类请求。

## 每工具三层结构

**第1层：攻击者的 HTTP 请求**

展示完整的原始 HTTP 报文（请求行 + 关键头 + 空行 + 请求体）。禁止使用 curl 命令（Quake API 除外）。

```http
POST /shell.jsp HTTP/1.1
Host: vulnweb.com
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Accept: application/xhtml+xml
Cache-Control: no-cache
Content-Type: application/x-www-form-urlencoded
Content-Length: 2192

payload=k7U3mF9qL2xP4wR6...
```

**第2层：服务端响应体（抓包看到的数据）**

展示原始 HTTP 响应，包含完整的响应头和响应体。响应体展示密文/hex/Base64 形态。

```http
HTTP/1.1 200 OK
Content-Type: text/html; charset=UTF-8
Content-Length: 4096

aJ7kL2xP9mQ4rW6vY8zB0cN3fH5sD1gK...
```

**第3层：解密后的内容 + 判定逻辑 + 检测规则**

- 解密/解码后在攻击者客户端中显示的内容
- 三层判定逻辑（每层一个可验证的特征）
- Suricata + Sigma 检测规则各一条
- 误报分析：什么场景会误报
- 三次抓包对比：正常流量 vs 本工具 vs 同类工具

## 格式规则

- 禁止管道符表格。一律使用子弹列表 `• **header**: value`
- HTTP 示例用原始报文格式（不用 curl）
- 每个工具独立成节，不合并
- 覆盖工具按分类顺序：Webshell → 商业 C2 → 开源 C2 → 传统远控 → 后门生成器
