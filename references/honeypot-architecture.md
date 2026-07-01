# Honeypot / 安全工具 Go+Vue3 全栈架构

## 项目定位

Java 技术栈蜜罐，不实现业务逻辑，只仿真框架特征 + 部署错误 + 运维失误。
目标：捕获自动化扫描器 payload、手工渗透行为、0day / 新 POC 可见性。

**关键约束**：
- 只支持 Java 技术栈（Spring Boot / Tomcat / WebLogic / Jenkins / ES + 企业运维后台）
- 不做 PHP / Python / Node（但可模拟 phpinfo 等蜜罐页面）
- 不做业务功能 / 数据库 / ORM
- 所有响应均为仿真
- 所有路径、Header、Body 可配置

---

## 一、项目结构（方案一：按能力分层）

```
project/
├── cmd/honeypot/main.go       # 入口
├── api/
│   ├── api.go                 # Gin REST API（路由 + JWT 中间件 + handler）
│   └── jwt.go                 # HMAC-SHA256 自实现 JWT（零外部依赖）
├── internal/
│   ├── config/config.go       # JSON 配置加载 + 默认值填充
│   ├── config/routes.go       # 内置路由表填充器（builtin 字段→Go 函数）
│   ├── db/
│   │   ├── schema.sql         # 全量 DDL
│   │   └── db.go              # sqlx 连接 + 自动建表
│   ├── server/
│   │   ├── listener.go        # TCP Accept 循环 + goroutine 分发
│   │   └── handler.go         # HTTP ReadRequest + Raw TCP + 路由匹配 + 登录校验 + 画像同步
│   ├── limiter/rateLimiter.go # IP 追踪 → 动态 403（概率递增）+ iptables 封禁
│   ├── logger/logger.go       # JSONL 文件写入 + HTTP 转发
│   ├── response/errorPages.go # 各框架 404/401/500 模板
│   ├── profile/engine.go      # 画像引擎（技能评估/扫描器识别/威胁评分/日志重建）
│   ├── capture/capture.go     # 木马 URL 提取 + 真实下载 + SHA256 存档 + C2 提取
│   └── java/                  # 每个框架一个文件
│       ├── springBoot.go
│       ├── tomcat.go
│       ├── weblogic.go
│       ├── jenkins.go
│       ├── elasticsearch.go
│       └── enterpriseAdmin.go # 企业运维后台（8080 端口）
├── frontend/
│   ├── src/
│   │   ├── api/request.js     # Axios + JWT 拦截器
│   │   ├── router/index.js    # 路由守卫
│   │   └── views/             # Login / Layout / Dashboard / Logs / Profiles / Config
│   ├── package.json
│   └── vite.config.js
├── deploy/
│   ├── frps.toml              # FRP 服务端（云服务器）— TOML 格式
│   ├── frpc.toml              # FRP 客户端（WSL）
│   └── deploy.sh              # 一键部署脚本
└── services.json              # 端口→服务配置
```

**命名规范**：
- 函数命名：驼峰 `handleHTTP` `classifyRisk`
- 目录命名：全小写，不缩写 `limiter` `logger` `profile`
- 文件命名：同目录名 `rateLimiter.go` `errorPages.go`

---

## 二、配置体系

### 配置加载流程

1. JSON 文件 → `config.Load()` 解析
2. 内置路由填充：`cfg.ApplyBuiltinRoutes()` 根据 `builtin` 字段自动注入 Go 代码中的路由表
3. JSON 路由优先级高于内置路由（用户手工配置覆盖默认）

### 配置结构

```go
type Config struct {
    Services    map[string]ServiceConfig  // 端口号→服务
    LogDir      string
    Forward     ForwardConfig             // 日志 HTTP 转发
    RateLimit   RateLimitConfig           // 动态 403
    ListenAddr  string
    DB          DatabaseConfig
    FrontendDir string
    APIPort     int
}

type ServiceConfig struct {
    Name        string           // 服务名
    Type        string           // http / raw
    Description string
    Banner      string           // Server Header
    Builtin     string           // "spring-boot" / "tomcat" 等
    Routes      map[string]Route // 路径→响应定义
    BannerHex   string           // Raw TCP 十六进制 banner
    BannerRaw   string           // Raw TCP 纯文本 banner
}
```

### 内置框架路由（Go 函数生成）

每个框架一个 `XxxRoutes() map[string]Route` 函数，返回完整路由表。
注册方式：

```go
cfg.ApplyBuiltinRoutes(map[string]func() map[string]config.Route{
    "spring-boot":     java.SpringBootRoutes,
    "tomcat":          java.TomcatRoutes,
    "weblogic":        java.WeblogicRoutes,
    "jenkins":         java.JenkinsRoutes,
    "elasticsearch":   java.ESRoutes,
    "enterprise-admin": java.EnterpriseAdminRoutes,  // 8080 企业后台
})
```

---

## 三、企业运维后台（enterpriseAdmin.go）

运行在 8080 端口的假企业内部运维 / 管理后台。欺骗攻击者这是真实企业的运维控制台。

### 设计原则

| 原则 | 说明 |
|------|------|
| 业务化命名 | 参数用 `uid` `cfg` `url` `file` `op` `type`，禁用 `test` `payload` `demo` |
| 多种请求方式 | GET / POST / JSON / form / multipart 混合 |
| 固定响应 | 不执行任何命令、数据库操作或文件处理 |
| 非标准化字段 | 存在 `act` `op` `do` `tp` `flag` 等老代码遗留字段 |
| 模糊错误信息 | "操作失败" "系统异常" "执行出错"（不暴露具体原因） |
| 顺序依赖感 | 某些接口暗示需要先登录 / 先配置 / 有操作顺序 |

### 五个模块（18+ 接口）

#### 模块一：登录

| 路径 | 方法 | 表面功能 | 攻击者可能尝试 |
|------|------|---------|--------------|
| `/login` | GET | 登录页面（完整 HTML 表单 + CSS） | 直接访问未授权路径 |
| `/api/auth/login` | POST | 登录校验（支持 JSON + form） | 暴力破解、SQL 注入、参数混淆 |
| `/api/auth/verify` | GET/POST | 校验 token 有效性 | Session 伪造、JWT 攻击 |
| `/api/auth/logout` | GET | 登出 | CSRF 登出 |

**登录校验实现**：在 handler.go 中编写 `handleLogin()` 函数，解析 JSON body 或 form-encoded body，校验固定账号。

**密码传输安全**：
- 前端：`sha256(password) + "||" + AES_IV+密文(Base64)` 作为 password 字段
- 后端：`strings.LastIndex(password, "||")` 切分 → 前半部分 SHA256 对比 → 后半部分 AES-CBC 解密指纹
- 密码存储：SHA256 哈希值（非明文），Go 常量 `map[string]string{"admin": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"}`

**关键设计**：登录成功返回 **302 重定向**（不是 JSON），失败也返回 302（带 `?error=1`）。浏览器表单提交后正常跳转，不会显示裸 JSON。

**固定账号**：

| 用户名 | 密码（SHA256） |
|--------|--------------|
| `admin` | `240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9` |
| `admin@internal.company.cn` | `a36aef5a11c4073fbe60314fc9df530a9d5f986533594d1f5190742ff9e0e408` |

#### 模块二：用户管理

| 路径 | 方法 | 表面功能 | 攻击方向 |
|------|------|---------|---------|
| `/api/users/list` | GET | 用户列表 | IDOR、JSON 注入、水平越权 |
| `/api/users/info` | GET | 用户详情 | 权限绕过、信息泄露 |
| `/api/users/search` | GET | 搜索用户 | SQL 注入、模糊查询滥用 |
| `/api/users/role` | GET | 角色权限 | 权限提升、角色遍历 |

#### 模块三：系统配置

| 路径 | 方法 | 表面功能 | 攻击方向 |
|------|------|---------|---------|
| `/api/config/get` | GET | 获取全部配置（含 LDAP/Redis/DB 连接串） | SSRF、内网信息收集、配置泄露 |
| `/api/config/update` | POST | 更新配置 | 配置篡改、XSS、CRLF 注入 |
| `/api/config/backup` | GET | 备份配置 | 路径遍历、文件泄露 |
| `/api/config/restore` | POST | 恢复配置 | 任意文件覆盖 |

#### 模块四：文件管理

| 路径 | 方法 | 表面功能 | 攻击方向 |
|------|------|---------|---------|
| `/api/file/list` | GET | 文件列表 | 路径遍历、目录枚举 |
| `/api/file/upload` | POST | 上传文件 | webshell 上传、任意文件写入 |
| `/api/file/download` | GET | 下载文件 | 任意文件下载、路径穿越 |
| `/api/file/delete` | POST | 删除文件 | 任意文件删除 |

#### 模块五：接口调试

| 路径 | 方法 | 表面功能 | 攻击方向 |
|------|------|---------|---------|
| `/api/debug/exec` | GET/POST | 执行健康检查脚本（返回模拟日志） | 命令注入、RCE |
| `/api/debug/proxy` | GET/POST | 代理请求 | SSRF、内网端口扫描 |
| `/api/debug/invoke` | GET/POST | 调用内部接口 | 表达式注入、模板注入 |
| `/api/debug/sql` | GET/POST | 执行 SQL 查询 | SQL 注入、NoSQL 注入 |

### 登录页 HTML 设计

- 完整的企业风格登录页（标题「运维管理平台 v2.8.1」、用户名/密码输入框、记住我复选框、提交按钮）
- CSS 内联，纯白简洁背景，4a6cf7 蓝色主色调（类似飞书风格）
- 页面底部标注「企业内部运维控制台」
- 未登录返回 302 到 `/login`（保持登录流程一致性）

### Dashboard HTML

- 顶栏：logo + 用户下拉 + 退出链接
- 侧栏：总览 / 用户管理 / 系统配置 / 文件管理 / 接口调试 / 系统状态
- 主区域：4 个统计卡片（注册用户 / 今日请求 / 系统可用率 / 连续运行）+ 最近操作日志表格

### 防蜜罐识别要点

| 要素 | 正确做法 | 错误做法 |
|------|---------|---------|
| 邮箱 | **不要包含邮箱**（永远显得假） | 添加 `admin@company.cn` 类邮箱 |
| Site URL | 用内网 IP：`http://10.88.0.100:8080` | 用外网域名 `ops.company.cn` |
| 内部服务地址 | 10.88.0.x 内网 IP | 外网域名或公网 IP |
| 配置泄露 | 包含 LDAP/Redis/DB 连接串 | 只返回基本配置 |
| 管理员账号 | `admin/admin123` | 空的或默认 admin/admin |
| 登录流程 | 302 重定向 + Set-Cookie | 返回 JSON 不做跳转 |
| 密码传输 | SHA256 哈希 | 明文密码 |
| 错误提示 | 模糊："操作失败" | 精确："SQL error at line 42" |

### 红队视角最可能的行为

1. **利用 `/api/config/get` 泄露的内网地址进行 SSRF** — 攻击者拿到 LDAP/Redis/DB 连接串后，尝试从蜜罐服务器对内网发起探测。值得记录的原因：能捕获 SSRF 类扫描器的 payload，且 SSRF 请求中的 URL 可暴露攻击者的后续目标。

2. **利用 `/api/file/upload` 上传 webshell 后尝试命令执行** — 攻击者上传 jsp/php 文件后，会访问该文件并执行 `whoami` `id` `ls` 等命令。值得记录的原因：命令执行参数（`cmd` `exec` `op`）可反映攻击者使用的工具链和后渗透手法。

3. **利用 `/api/debug/exec` 尝试命令注入** — 攻击者会在 `cmd` `op` `args` 参数中注入 shell 命令（管道、分号、反引号）。值得记录的原因：命令注入尝试中的命令内容直接反映了攻击者的 C2 基础设施偏好（wget/curl 的目标 IP）。

---

## 四、浏览器指纹采集（XOR 加密，HTTP 兼容）

在 8080 企业后台登录页（`enterpriseAdmin.go`）内嵌纯 JS 脚本，静默采集浏览器信息并 XOR 加密后发送。**不依赖 Web Crypto API**（HTTP 下不可用）。**SHA256 由 Go 后端完成**（纯 JS SHA256 实现经多次测试均无法产生标准结果）。

### 数据流

```
用户打开 /login → 页面加载 → 立即采集：
   Canvas → m1, WebGL → m2, uaData → u1/u2
   CPU → c1, 内存 → c2, 语言 → l1/l2
   屏幕 → s1/s2/s3, 时区 → z1/z2

用户输入密码 → 点击登录 → JS 截获 submit：
   采集指纹 → JSON → Base64 → XOR(密钥) → Base64  → 指纹密文
   组合: "admin123" + "|||" + 指纹密文
   整体加密: Base64(组合) → XOR(密钥) → Base64  → 最终密文
   password 字段 = 最终密文（抓包看到纯 Base64，无明文）
   ↓ form submit

后端 handler.go:
   1. URL 解码 form body
   2. base64 decode → XOR → base64 decode → "admin123|||指纹密文"
   3. strings.LastIndex("|||") → 密码 + 指纹密文
   4. SHA256(密码) → 比较 validUsers
   5. saveEnvReport: 指纹密文 → base64 decode → XOR → base64 decode → JSON
   6. AttachEnvData(srcIP, envJSON) → 画像关联
   7. triggerEnvAlert → 飞书群通知
   8. 302 → /dashboard 或 /login?error=1
```

### 前端的加密函数

```
X(s, k):
  step1 = Base64(s)        // 明文 → Base64
  step2 = XOR(step1, k)    // Base64 → XOR 混淆
  result = Base64(step2)   // XOR 结果 → Base64
```

采集编码在 8080 登录页 HTML 的 `<script>` 中，跟随 HTTP 响应下发，不依赖外部 JS 库。

### 后端 XOR 解密（handler.go）

```go
// 外层解密：Base64 → XOR → Base64 (decode)
raw, _ := base64.StdEncoding.DecodeString(encData)
xor := make([]byte, len(raw))
for i, b := range raw {
    xor[i] = b ^ key[i%len(key)]
}
// 内层解码：必须用 Decode(dst, xor)，不要用 DecodeString(string(xor))
// XOR 结果可能含非 UTF-8 字节，DecodeString(string(xor)) 会失败
dst := make([]byte, base64.StdEncoding.DecodedLen(len(xor)))
n, _ := base64.StdEncoding.Decode(dst, xor)
decrypted := string(dst[:n])
```

### SHA256 由 Go 后端完成

```go
hash := sha256.Sum256([]byte(rawPwd))
pwdHash := hex.EncodeToString(hash[:])
if pwdHash != expected {
    // 登录失败
}
```

### 字段命名规范

| 前端字段 | 采集内容 | 含义 |
|---------|---------|------|
| `m1` | Canvas toDataURL（前 200 字符） | 绘图兼容性 |
| `m2` | WebGL 厂商/渲染器 | 图形驱动 |
| `u1/u2` | uaData platform/brands | 终端类型 |
| `c1` | CPU 核数 | 硬件容量 |
| `c2` | deviceMemory | 可用内存 |
| `l1` | 语言 | 用户偏好 |
| `s1/s3` | 屏幕/窗口分辨率 | 显示参数 |
| `z1` | 时区 | 时区配置 |

**严禁使用**：`fp` `fingerprint` `canvas` `browser` `honeypot` `test` `demo` `payload`

### 日志格式

```json
{"ts":"2026-07-01T10:30:00Z","src_ip":"115.198.202.226","username":"admin","env_data":{"m1":"data:image/png;...","m2":"Google|ANGLE","c1":8,"s1":"1920x1080","z1":"Asia/Shanghai"}}
```

---

## 五、高级模式

### 5.1 画像持久化：从历史日志重建

画像引擎纯内存运行，重启后通过扫描 JSONL 文件重建：

```go
pe := profile.New()
pe.RebuildFromLogs(cfg.LogDir)
```

RebuildFromLogs 读取 `_all.jsonl`，按行 JSON 解析后逐个调用 `e.Process(entry)` 重建画像。

### 5.2 原始 HTTP 请求+响应捕获

使用 `httputil.DumpRequest` 捕获完整 HTTP 请求，响应则保存构造好的响应字符串：

```go
reqDump, _ := httputil.DumpRequest(req, true)  // true = 包含 body
respStr := fmt.Sprintf("HTTP/1.1 %d %s\r\n...", status, ...)

h.logger.Write(logger.Entry{
    ReqHeader:  truncateStr(reqHeaderStr, 5000),
    RespHeader: truncateStr(respStr, 5000),
})
```

前端日志详情弹窗：**请求/响应标签页切换**（BurpSuite 风格）。白底黑字等宽字体 + 灰边框。颜色映射：GET=绿 POST=蓝 PUT=橙。旧日志显示「旧日志，无请求包」提示。

### 5.3 前端日志筛选

四维筛选：风险等级 + 框架 + 源 IP（后端 API 参数过滤）。客户端路径关键字过滤。

### 5.4 攻击链路可视化（ECharts Sankey）

仪表盘中用 ECharts Sankey 图展示源 IP → 目标蜜罐的流量流向。数据从日志聚合（`src_ip → framework`）。ECharts 全量引入约 1MB。

### 5.5 攻击者画像详情（右侧抽屉）

点击攻击者行打开右侧抽屉，包含：
- **概览卡片**：威胁评分 / 总请求 / 并发峰值 / 平均间隔 / 技能等级
- **IP 归属地**：通过 `/api/ipinfo/:ip` 自动获取（国家/省份/城市/ISP/经纬度/风险评分）
- **扫描器指纹**：类型 + UA 列表
- **访问路径**：完整路径列表 + 高危路径 ⚠️ 标记
- **Payload + C2 + 木马**
- **标签**：自动分类（含 emoji 前缀）
- **最近攻击日志时间线**：可展开 RAW HTTP（请求/响应标签切换）

### 5.6 前端框架管理

每框架配置项：启停开关 / 强度三档(轻/中/高) / Banner 文本输入 / 路由清单。
全局策略开关：动态 403 / 延迟抖动 / 偶发 500 / Webshell 仿真。

### 5.7 IP 归属地查询

使用 `api.ip77.net` IP 地理定位 API，Go 后端代理（POST + 随机 UA）：

```go
// POST https://api.ip77.net/ip2/v4/
// Content-Type: application/x-www-form-urlencoded
// Body: ip=X.X.X.X
// 返回: country/province/city/isp/latitude/longitude/risk_score
```

**必须用 POST**（GET 返回"无效的IP地址"），无需 API Key。

### 5.8 移动端适配

侧栏默认收起，☰ 汉堡菜单展开 + 遮罩层。表格 `overflow-x: auto` 横向滑动。指标卡 2×2（桌面 4×1）。

---

## 五B、飞书告警

### 配置方式

前端框架管理页面 → 飞书告警区域。使用应用机器人（不是 webhook）：

- App ID：`cli_xxxxxxxx`
- App Secret：飞书应用密钥
- Chat ID：群聊的 `oc_xxx` ID
- 最低风险等级：high / medium

### 配置持久化

数据存入 `data/notify_config.json`，`init()` 时自动加载。API 端 `PUT /api/config/notify` 更新后保存。

```json
{"app_id":"cli_xxxx...","app_secret":"xxxx...","chat_id":"oc_xxxx...","enabled":true,"min_risk":"medium"}
```

### 触发逻辑

**仅在捕获到浏览器指纹时触发**（saveEnvReport 成功时），不在普通扫描流量时触发。调用链：

```
handleLogin() → checkLogin() → saveEnvReport() → triggerEnvAlert() → notify.SendCard()
```

### SendCard 实现

```go
func SendCard(title, template, content, footer string) {
    // 1. POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
    //    Body: {"app_id":"xxx","app_secret":"xxx"} → token + expire
    // 2. POST https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id
    //    Authorization: Bearer ***    //    Body: interactive card JSON
}
```

### 触发函数

```go
func triggerEnvAlert(username, srcIP string, envData map[string]interface{}) {
    canvas := envData["m1"].(string)[:10] + "..."
    title := "🖥️ 攻击者浏览器指纹捕获"
    content := fmt.Sprintf("**用户名:** %s\n**源 IP:** `%s`\n**CPU:** %v\n**屏幕:** %v\n**时区:** %v\n**Canvas:** `%s`",
        username, srcIP, envData["c1"], envData["s1"], envData["z1"], canvas)
    notify.SendCard(title, "red", content, "HoneyPot 自动告警 · 查看画像 → http://118.25.109.41:24808/profiles")
}
```

---

## 六、框架管理启停

前后端同步启停：

1. `listener.go`: Honeypot 新增 `disabled map[string]bool` + `SetEnabled(port, enabled)` 
2. `handler.go` handleHTTP: 先检查 `h.disabled[portStr]`，停用返回 503
3. `api.go`: Server 新增 `onToggle` 回调 + `SetToggleCallback()` 
4. `main.go`: 用 `SetToggleCallback` 连接 API Server 和 Honeypot 实例
5. Config.vue PUT `/api/config/services/:port` 带 `{enabled: bool}`
6. TCP listener 无法动态关闭，停用端口仍 LISTEN，handler 直接返回 503

---

## 七、防蜜罐指纹检测清单

## 六、框架管理启停

| 问题 | 错误示范 | 正确做法 |
|------|---------|---------|
| **ES build_date 造假** | ES 8.11.0 声称 `build_date: 2026-03-15`（真实发布于 2023-11） | 使用真实发布日期 |
| **ES build_hash 占位符** | `"build_hash": "abc123"` | 40 位 hex 哈希 |
| **Favicon 是文本** | 返回 "404 page not found" 文本冒充图片 | 返回真实 favicon 二进制 |
| **多端口统一 403** | 全部返回相同 403 页面 | 每端口差异化（Tomcat HTML / Spring JSON / ES 风格 / Jenkins CSRF 风格） |
| **密码明文传输** | `"password":"admin123"` | SHA256 哈希后传输 |
| **邮箱字段** | `admin@company.cn` | **不要包含邮箱**（永远显得假） |
| **site_url 用域名** | `ops.company.cn` | 用内网 IP `http://10.88.0.100:8080` |
| **登录返回 JSON** | 表单提交后显示裸 JSON | 302 重定向跳转 Dashboard |
| **所有请求固定 200** | 无状态码变化 | 概率性 403 + 随机延迟 50-200ms |
| **指纹加密太弱** | XOR 固定密钥 | AES-CBC + 随机 IV（Web Crypto API） |

### iptables 自动封禁

超过 200 次请求的 IP → 自动 `iptables -A INPUT -s IP -j DROP`（1 小时后解封）。
硬封禁后返回 503（非 403），伪装成服务不可用。

---

## 七、数据库设计（高水位日志场景）

| 策略 | 说明 |
|------|------|
| 按季度分区 | `logs_2026_q3` / `logs_2026_q4` / `logs_default` |
| BRIN 索引 | `created_at` 用 BRIN（比 B-tree 小 50 倍） |
| B-tree 索引 | `src_ip` / `risk_level` / `dst_port` |
| 物化视图 | `mv_hourly_stats` 仪表盘聚合 |

---

## 八、部署

**推荐直接部署到云服务器**（FRP 隧道丢失源 IP）：

```bash
go build -o honeypot ./cmd/honeypot/
scp honeypot services.json root@cloud:/opt/honeypot/
scp -r frontend/dist/* root@cloud:/opt/honeypot/frontend/dist/
# 启动（需 root）
ssh root@cloud "cd /opt/honeypot && setsid ./honeypot -config services.json > honeypot.log 2>&1 &"
```

### 端口表

| 服务 | 端口 | 说明 |
|------|------|------|
| 企业运维后台 | 8080 | 登录页 + 控制台 + 5 模块 |
| Spring Boot | 8081 | |
| Jenkins | 8082 | |
| Tomcat | 8083 | |
| WebLogic | 7001 | |
| ES | 9200 | |
| MySQL | 63306 | |
| Redis | 56379 | |
| 管理 API | 24808 | JWT 保护，Vue3 SPA |

### WSL 环境坑点

| 问题 | 解决 |
|------|------|
| Windows npm 无法在 WSL 安装依赖 | 下载 Linux node tarball 到 `/tmp`，用 `/tmp/node-xx/bin/npm` |
| vite build 权限拒绝 | `node node_modules/vite/bin/vite.js build` |
| 代理干扰 | `unset http_proxy https_proxy ...` |
| 前端更新无需重启后端 | Go 运行时加载 `frontend/dist/` 静态文件 |
| 日志时间 Invalid Date | 先 `.endsWith('Z')` 去掉原 `Z` 再 `new Date(ts+'Z')` |

---

## 九、JWT 认证（零外部依赖）

HMAC-SHA256 自实现，不依赖 jwt-go。前端 Axios 拦截器自动附加 Bearer token。

---

## 十、踩坑总结

| 问题 | 修复 |
|------|------|
| 重启后画像丢失 | `RebuildFromLogs()` 重建 |
| 源 IP 全是 127.0.0.1 | FRP TCP 隧道导致 → 直接部署云服务器 |
| Go 模块路径 | `module github.com/c1ayooo/honeypot`，import 必须完整路径 |
| FRP TOML 报错 | 用 `fatedier/frps:v0.53.2` 替代 `snowdreamtech/frps:0.58.0` |
| 画像引擎未关联 | 将 `profile.Engine` 注入 `server.New(cfg, pe)` |
| 公网 502 但 FRP 正常 | WSL 代理干扰 |
| IP 查询无效 | 必须 POST + `Content-Type: application/x-www-form-urlencoded` |
| nohup 被拦截 | 用 `terminal(background=true)` 或在 SSH 中用 `setsid cmd &` |
| 密码明文传输 | 前端 SHA256 + 后端哈希对比 |
| 指纹加密用 XOR | 改为 AES-CBC + 随机 IV（Web Crypto API + Go crypto/aes） |
