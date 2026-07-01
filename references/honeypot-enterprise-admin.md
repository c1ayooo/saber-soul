# 企业运维后台蜜罐（端口 8080）

## 概述

伪装成企业内部运维管理平台，运行在 8080 端口。5 个模块 25 个路由，不执行业务逻辑，所有请求仅用于记录攻击者行为。

## 模块结构

| 模块 | 路径 | 路由数 | 攻击面 |
|------|------|--------|--------|
| 登录 | `/login`, `/api/auth/login`, `/api/auth/verify`, `/api/auth/logout` | 4 | 登录绕过、账号枚举、凭证暴力破解、浏览器指纹采集 |
| 用户管理 | `/api/users/list`, `/api/users/info`, `/api/users/search`, `/api/users/role` | 4 | IDOR、参数注入、权限绕过 |
| 系统配置 | `/api/config/get`, `/api/config/update`, `/api/config/backup`, `/api/config/restore` | 4 | SSRF（ldap/redis/db 连接串泄露）、配置篡改 |
| 文件管理 | `/api/file/list`, `/api/file/upload`, `/api/file/download`, `/api/file/delete` | 4 | 文件上传、路径遍历、任意文件下载 |
| 接口调试 | `/api/debug/exec`, `/api/debug/proxy`, `/api/debug/invoke`, `/api/debug/sql` | 4 | 命令注入、SSRF、模板注入、SQL 注入 |

## 登录与指纹采集

### 核心设计

前端不执行 SHA256（纯 JS SHA256 实现在 Node.js 和浏览器环境下均有不可预料的位运算差异，各种实现均无法匹配标准结果）。改为**整体 XOR 加密字段**方案：

```
用户输入密码 → JS intercept submit
  ├─ 采集 Canvas/WebGL/UA/CPU/屏幕/时区 → JSON
  ├─ XOR(Base64(JSON), 固定密钥) → 指纹密文
  ├─ combined = "admin123" + "|||" + 指纹密文  （三重竖线避免和 Base64 字符冲突）
  └─ 整体 XOR(Base64(combined), 密钥) → 发送
       ↓ form submit
       密码字段抓包看到: T0dLaE...（纯密文）
```

**关键：纯 JS XOR+Base64，不依赖 Web Crypto API**（HTTP 下 `crypto.subtle` 不可用）。SHA256 由 Go 后端标准库完成。

### 前端函数

- `X(s,k)` — XOR 加密链：`Base64(s) → XOR(k) → Base64(result)`
- `C()` — 采集 Canvas/WebGL/UA/CPU/内存/屏幕/时区

### 后端流程（handler.go）

```
POST /api/auth/login
  ├─ handleLogin(body, srcIP)
  │   └─ checkLogin(username, password, srcIP)
  │       ├─ base64.StdEncoding.DecodeString(password)  // 外层 XOR 解码
  │       ├─ XOR(key) → 得到内层 Base64 → 再 Decode → "admin123|||加密指纹"
  │       ├─ strings.LastIndex("|||") → 分离密码和指纹密文
  │       ├─ SHA256(rawPwd)  // Go crypto/sha256，结果匹配标准
  │       ├─ 比较 hash vs validUsers[username]
  │       ├─ saveEnvReport(username, srcIP, 指纹密文)
  │       │   ├─ base64.StdEncoding.DecodeString
  │       │   ├─ xor[i] = raw[i] ^ key[i%len(key)]
  │       │   ├─ base64.StdEncoding.Decode(dst, xor)  // 用 byte buffer 避免 string 异常
  │       │   └─ json.Unmarshal → envJSON
  │       ├─ triggerEnvAlert(username, srcIP, envJSON) → Feishu 通知
  │       └─ return 302 → /dashboard 或 /login?error=1
  └─ handleHTTP 中:
      envData = handleLogin 的第 4 返回值
      if envData != nil → h.profiler.AttachEnvData(srcIP, envData)
```

### 为什么不用纯 JS SHA256

多次尝试均失败（包括 Paul Johnston、Chris Veness、emn178/js-sha256 等已知实现），Node.js v20 下测试 `sha256("admin123")` 返回 `220b6b5e...` 而非标准值 `240be518...`。浏览器位运算行为与 Node.js 存在差异，且 HTTP 下 `crypto.subtle` 不可用。**结论：前端 SHA256 不可靠，SHA256 应由后端 Go crypto/sha256 完成。**

### XOR 解密关键点

**完整加密链：** `Base64(明文) → XOR(密钥) → Base64(结果)`

后端解密链：
```go
// 外层：Base64 decode → XOR → Base64 decode
raw, _ := base64.StdEncoding.DecodeString(encData)
for i, b := range raw {
    xor[i] = b ^ key[i%len(key)]
}
// 内层：用 Decode(dst, xor) 而非 DecodeString(string(xor))
// 因为 string(xor) 可能产生无效 UTF-8 导致 DecodeString 失败
dst := make([]byte, base64.StdEncoding.DecodedLen(len(xor)))
n, _ := base64.StdEncoding.Decode(dst, xor)
decrypted = string(dst[:n])
```

**坑：** 
1. `base64.StdEncoding.DecodeString(string(xor))` 会因 XOR 结果含非 UTF-8 字节失败。必须用 `Decode(dst, xor)` 直接操作字节数组。
2. 分隔符用 `|||`（三重竖线）而非 `||`，因为 Base64 输出可能包含 `||` 导致误分割。
3. Form POST 会 URL 编码 body，虽然 XOR 密文外层 Base64 不含特殊字符，但 `checkLogin` 解析 form body 时仍须 `url.QueryUnescape(val)` 处理每个字段值。
4. **`url.QueryUnescape` 会把 `+` 转空格**：Base64 数据含 `+` 字符（标准 Base64 字符集的一部分），`url.QueryUnescape` 将 `+` 转换为空格，损坏 Base64。修复：密码字段必须用 `url.PathUnescape`（不处理 `+`→空格）。
5. **`base64.StdEncoding.Decode(dst, xor)` vs `DecodeString(string(xor))`**：XOR 结果可能含非 UTF-8 字节，用 `DecodeString(string(xor))` 会失败。必须用 `Decode(dst, xor)` 直接操作字节数组。

### 限流策略（handler.go）

**8080 企业后台不受限流影响。** 普通蜜罐端口（8081/8082/8083/7001/9200）受 `h.limiter.ShouldBlock(srcIP)` 限流，超过阈值返回 403。8080 的登录页、Dashboard 等正常浏览行为不应触发限流。代码中 `if portStr != "8080"` 包裹整个限流区块。

### 告警触发条件

仅 `saveEnvReport` 成功解密到浏览器指纹数据时调用 `triggerEnvAlert`。普通 HTTP 请求（/actuator/health、/manager/html 等扫描路径）**不触发**飞书通知。告警链路：`checkLogin → saveEnvReport (成功) → triggerEnvAlert → notify.SendCard → 飞书群`。

### 前端不显示 env_data 的排查

如果攻击者画像页面不显示浏览器指纹数据：

1. API 返回 `env_data: false` → 确认 `handleHTTP` 中 `h.profiler.AttachEnvData(srcIP, envData)` 被调用（`envData != nil`）
2. `checkLogin` 中的 `saveEnvReport` 必须返回非 nil（XOR 解密 + JSON 解析成功）
3. 检查日志是否有 `[EnvReport] 解析失败` 或 `[Login] envData=false`
4. 确认 `notify/feishu.go` 的 `SendCard` 中 `currentConfig.Enabled == true` 且 `AppID/ChatID` 非空

## 飞书告警

使用自定义应用机器人（非 webhook）：

```go
// 获取 token
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
{"app_id": "...", "app_secret": "..."}

// 发送卡片消息（content 必须是 JSON 字符串，不是对象）
POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id
Authorization: Bearer ***  "receive_id": "oc_xxx",
  "msg_type": "interactive",
  "content": "{\"header\":{\"title\":{\"tag\":\"plain_text\",\"content\":\"标题\"},\"template\":\"red\"},\"elements\":[{\"tag\":\"div\",\"text\":{\"tag\":\"lark_md\",\"content\":\"内容\"}}]}"
}
```

**Go 实现关键**：
- `content` 字段必须是 `string`（JSON 字符串化的卡片），不是 Go map/struct。先构建 card map → `json.Marshal` → `string(cardContent)` → 再塞入外层 map 的 `"content"` 字段
- 卡片元素用 `{"tag":"div","text":{"tag":"lark_md","content":"..."}}`，`markdown` 标签已弃用
- `hr` 和 `note` 元素在最新 API 中可能报错，直接去掉，只保留 `div` 元素
- 错误码 `200621`：卡片 JSON 结构无效，通常是元素标签不对或 content 类型不匹配
- 错误 `Invalid parameter type in json: content`：content 应是 string 但传了 object

配置存储在 `data/notify_config.json`，应用启动时由 `init()` 加载并通过 API 更新。

**触发时机**：仅当 `saveEnvReport` 成功解密到浏览器指纹数据时调用 `triggerEnvAlert`，不响应普通扫描流量。

## 防识别设计

| 手段 | 实现 |
|------|------|
| 密码不明文 | 整体 XOR 加密整个密码字段，抓包看到纯 Base64 密文 |
| 指纹数据似签名 | 密文拼接在密码后看起来像标准认证签名参数 |
| 登录页像真实业务 | 完整 CSS 布局、Logo、企业名称、版权信息 |
| Dashboard 有内容 | 4 指标卡 + 操作日志表格（模拟真实运维记录） |
| 响应延迟抖动 | 50-200ms 随机延迟 |
| 动态 403 | 超过阈值概率性返回 403（非全部封禁） |
| iptables 硬封禁 | 单 IP 超 200 次请求自动 iptables DROP 1 小时 |
| 各端口差异化 403 | Tomcat/Jenkins/ES/Spring 各返回不同风格的 403 页面 |
