# dddd-mod 国产企业资产扫描工具

dddd 二开版本，存储于 `~/dddd-mod/`。涵盖搜索引擎集成、JS 逆向、国产系统增强、扫描模式控制、WAF 检测五大模块。

## 架构概览

```
cmd/dddd/main.go          ← 工作流编排（searchEngine → 端口 → httpx → JSRecon → 目录 → 指纹 → nuclei）
├── internal/scan/          ← 扫描模式控制（light/normal/full）
├── internal/asset/         ← 资产中心数据结构
├── pkg/waf/                ← WAF 检测 + 绕过建议
├── common/quake/           ← Quake API 搜索
├── common/jsrecon/         ← JS 逆向分析
└── common/cnassets/        ← 国产系统增强（端口/路径/指纹）
```

## 完整 CLI 参数

| 参数 | 缩写 | 默认 | 说明 |
|------|------|------|------|
| `--mode` | `-m` | light | 扫描模式：light/normal/full |
| `--dry-run` | - | false | 只打印执行计划不扫描 |
| `--explain` | - | false | 每步输出执行原因 |
| `--quake` | - | false | 启用 Quake 搜索引擎 |
| `--quake-key` | `-qk` | "" | Quake API Key |
| `--quake-max-count` | `-qmc` | 100 | Quake 最大结果数 |
| `--jsrecon` | - | false | JS 逆向分析 |
| `--cnasset` | - | false | 国产系统增强 |
| `--skip-waf` | - | false | 跳过 WAF 检测 |
| `--no-nmap` | - | false | 跳过 gonmap 协议识别 |

## 一、扫描模式控制（internal/scan/）

三级模式，light → normal → full 逐级递增。

### 各模式执行步骤

| 步骤 | light（默认） | normal | full |
|------|:---:|:-----:|:---:|
| 端口扫描 + 服务识别 | ✅ | ✅ | ✅ |
| HTTP 探活 + 通用指纹 | ✅ | ✅ | ✅ |
| 国产系统指纹识别 | ✅ | ✅ | ✅ |
| WAF 检测 | ✅ | ✅ | ✅ |
| JS 逆向分析 | ❌ | ✅ | ✅ |
| 目录爆破（含国产路径） | ❌ | ✅ | ✅ |
| nuclei PoC 扫描 | ❌ | ❌ | ✅ |
| GoPoC 弱口令爆破 | ❌ | ❌ | ✅ |

### 使用场景

```bash
# light — 快速摸底，不触发 WAF
./dddd -t target.com --mode light --cnasset

# normal — 全量信息收集（不含攻击 payload）
./dddd -t target.com --mode normal --quake --jsrecon --cnasset

# full — 含漏洞验证
./dddd -t target.com --mode full --quake --cnasset

# dry-run — 预览执行计划
./dddd -t target.com --mode full --dry-run --explain
```

### 代码结构

```go
// internal/scan/options.go
type ScanMode int
const (
    ModeLight  ScanMode = iota
    ModeNormal
    ModeFull
)

type ScanOptions struct {
    Mode            ScanMode
    RateLimit       int
    ParallelTargets int
    TaskID          string
    DryRun          bool
    Explain         bool
}

func BuildPlan(mode ScanMode) []Step
```

### 工作流集成要点

`searchEngine()` 移到 dry-run 之前调用，确保 dry-run 模式下也能展示 Quake 搜索结果。searchEngine 中 Quake 搜索完成后用 `defer func() { structs.GlobalConfig.Quake = false }()` 防止搜索结果被再次送入 Quake 循环搜索。

### 目标验证绕过

搜索引擎模式下（--quake/--fofa/--hunter），dddd 原有的目标格式验证（要求 IP/域名/URL 格式）需要放宽——任意字符串都应作为搜索关键词接受。

`common/flag.go` 中两处修改：

1. 第一关（line ~387）：`--quake` 模式下跳过 `strings.Contains(tg, ":")` 检查
2. 第二关（line ~434）：搜索引擎模式下直接 `append` 到 Targets 并 `continue`

### 端口扫描优化

`--no-nmap` 模式：
- 跳过 gonmap 服务识别（减少指纹噪声）
- HTTP 探活阶段只探测常见 Web 端口（80/443/8443/9090/9060 等）
- 需要 `main.go` 中 `GlobalIPPortMap` 为空时回退到端口扫描结果

```go
if len(structs.GlobalIPPortMap) > 0 {
    // 正常流程：从 gonmap 结果取 HTTP 服务
} else if structs.GlobalConfig.NoNmap {
    // --no-nmap：只探测常见 Web 端口列表
    webPorts := map[int]bool{80:true, 443:true, 8080:true, ...}
    for _, ipPort := range ipPort {
        if webPorts[parsedPort] {
            urls = append(urls, "http://"+ipPort)
        }
    }
}
```

## 二、Quake 搜索引擎（common/quake/）

自写的 Quake API 客户端，替代原有 uncover.QuakeSearch。

### 自动查询构建

用户传入纯域名/IP 时自动构建 Quake 查询语法：

| 输入 | 自动转换 | 说明 |
|------|---------|------|
| `cdmxjt.com` | `domain:"cdmxjt.com"` | 包含 `.` → 域名查询 |
| `182.40.146.4` | `ip:"182.40.146.4"` | 有效 IP → IP 查询 |
| `"org:浙能"` | 原样 | 已有查询语法 |

### API 细节

```go
func Search(apiKey, query string, size int) ([]QuakeResult, int, error)

type QuakeResult struct {
    IP, Port, Hostname, Title, Server, Org string
}
```

**注意点：**
- Quake API 返回的 `code` 字段可能是 string 或 int → struct 中用 `interface{}` 接收
- 响应中的 `service.http` 可能嵌套多层 nil 指针
- 搜索成功但 `meta.total = 0` 说明语法正确但无匹配结果
- 中文 `org` 字段搜索精度不高，建议同时用 `domain` + `icp` 多路交叉验证

### Quake 响应字段类型

Quake API `code` 字段可能是 `int` (0) 或 `string` ("0")，Go struct 定义时用 `interface{}`：

```go
type quakeResponse struct {
    Code    interface{}    `json:"code"`  // int 或 string
    ...
}
```

判断成功时检查：

```go
if qr.Code != nil {
    codeStr := fmt.Sprintf("%v", qr.Code)
    if codeStr != "0" && codeStr != "" { /* error */ }
}
```

### 两次 searchEngine() 调用

`main.go` 中 `searchEngine()` 被调用了两次（line 44 和 line 99）。需要删除 line 99 的调用避免重复搜索。

## 三、JS 逆向分析（common/jsrecon/）

### 检测项

| 检测项 | 正则/模式 | 提取内容 |
|--------|----------|---------|
| config.js / window.g | `window\\.g\\s*=\\s*\\{[^}]+\\}` | baseUrl / token / appid / agentid |
| __NEXT_DATA__ | `<script id="__NEXT_DATA__".*?>({.*?})</script>` | runtimeConfig 全部字段 |
| RSA 公钥 | `-----BEGIN PUBLIC KEY-----...-----END PUBLIC KEY-----` | PEM 格式公钥 |
| 隐藏 URL | `https?://[a-zA-Z0-9./?=&_%-]+` | 过滤 CDN/统计域名 |

### 加密方法识别

共 10 类 27 个指纹，通过 body + JS 文件内容关键词匹配：

| 类别 | 识别指纹 |
|------|---------|
| RSA | JSEncrypt / forge / NodeRSA / PEM |
| AES | CryptoJS AES/CBC/ECB / WebCrypto subtle |
| SM2/SM3/SM4 | sm-crypto / gm-crypt |
| MD5 | md5.js / spark-md5 |
| JWT | jsonwebtoken / jwt-decode |
| Base64 | btoa / atob / js-base64 |
| XOR | charCodeAt + ^ 0x 模式 |
| DES/3DES | CryptoJS DES/TripleDES |

指纹定义在 `common/jsrecon/jsrecon.go` 的 `encryptionFingerprints` 切片中。

### main.go 集成

JS 逆向在 httpx 探活后执行，优先从 `GlobalHttpBodyHMap` 缓存读取 body（零额外请求），缓存未命中时退回到 `nethttp.Get()`。同时自动提取 `.js` 文件内容进行加密方法匹配。

```go
// 从缓存取 body
if pathEntity.Hash != "" {
    if bodyBytes, ok := structs.GlobalHttpBodyHMap.Get(pathEntity.Hash); ok {
        body = string(bodyBytes)
    }
}
```

## 四、国产系统资产增强（common/cnassets/）

### 非标端口（17 个）

```
9090(OA/ERP)  9060(明源)  50780(数据中心)  19051(健康检查)
9010/9070(内RPC)  9000/7213(备用)  8089/8443/8008/8888
5555(ADB)  11211(Memcached)  27017(MongoDB)  6379(Redis)
```

### 22 个国产系统指纹

| 类别 | 系统 | 判定方式 |
|------|------|---------|
| OA | 致远 `/seeyon`、泛微 `/weaver`、通达 `/ispirit`、蓝凌 `/landray`、万户 `/defaultroot` | body 关键词 + 状态码 200 |
| ERP | 用友 `/yyoa`、金蝶 `/kingdee`、明源 `/PubPlatform/Login` | body 关键词 |
| 报表 | 帆软 `/ReportServer`、FineBI `/webroot/decision` | body 关键词 |
| 中间件 | Nacos、Druid、Swagger | body 关键词 |
| 安全设备 | JumpServer、齐治 | body 关键词 |
| DevOps | Jenkins、GitLab、Confluence、Jira | body 关键词 |
| 框架 | Shiro（rememberMe cookie 头） | header 匹配 |

指纹匹配使用 `GlobalHttpBodyHMap` / `GlobalHttpHeaderHMap` 缓存，不额外发送 HTTP 请求。

## 五、WAF 检测（pkg/waf/）

### 支持识别的 WAF（8 种）

| WAF | 检测特征 |
|------|---------|
| Cloudflare | Server:cloudflare, cf-ray 头, Turnstile 验证 |
| 阿里云WAF | X-Powered-By:Alibaba Cloud WAF, 406 状态码 |
| 安全狗 | X-SafeDog 头, body 含"安全狗" |
| ModSecurity | 406 状态码, body 含"ModSecurity" |
| 腾讯云WAF | Server:tencent-waf |
| 深信服 | body 含"sangfor/深信服" |
| 百度云WAF | X-Powered-By:baidu-waf |
| 长亭SafeLine | body 含"SafeLine/chaitin" |

### 检测逻辑

1. 发送一次正常 GET 请求获取基准响应
2. 发送一次带恶意 payload（`?id=1' OR 1=1--`）的请求
3. 对比两次响应的状态码、响应头、body 关键词
4. 每种 WAF 指纹有匹配评分，总分 >0.5 判定为命中

### 绕过建议自动输出

```go
func SuggestBypass(waf *WAFInfo) string
// Cloudflare → 找未走CDN子域名/历史DNS
// 阿里云 → Content-Type变换/HPP/分块传输
// 安全狗 → 注释混淆/大小写/Ghost Bits
// ModSecurity → 分块传输/双重编码
```

### `web cache` 类自定义 WAF 判定

当响应头出现 `server: web cache` 且带 `x-ser: i<数字>_c<数字>` worker ID 时，说明是自建 WAF/CDN 产品。这类 WAF default-deny，所有路径/Host/XFF/SNI 绕过均无效。无法从外部识别后端服务类型。

## 六、SSL 证书取证技术

SSL 证书是识别匿名 IP 身份的关键突破口。即使端口返回 403/ACCESS DENIED，TLS 握手阶段仍会暴露证书信息。

```bash
# 获取证书主体信息
echo | openssl s_client -connect 182.40.146.4:8443 2>&1 | \
  openssl x509 -noout -subject -dates 2>/dev/null

# 输出示例
subject=C = CN, ST = fujian, L = xiamen, O = Nosveass, OU = Nosveass, CN = Nosveass
notBefore=Sep 16 08:09:33 2025 GMT
notAfter=Sep 15 08:09:33 2030 GMT
```

**提取的信息：**
- CN = 组织名（可能是内部域名或公司名）
- O = 公司名称
- L = 城市
- ST = 省/州
- C = 国家

**用途：** 证书中的组织名可用于 Quake 二次搜索（`cert.subject.org:"Nosveass"` 或 `domain:nosveass.com`），但注意可能无公开 DNS 记录（内部域名）。

## 七、C2 判定方法论

当目标 IP 返回大量 403/ACCESS DENIED 时，区分远控服务器还是 WAF 边缘节点。

### Godzilla vs WAF C2 判定

Godzilla（哥斯拉）是 Webshell 管理工具。当怀疑 IP 是远控服务器时，对比 Godzilla 的行为特征：

| 特征 | Godzilla Webshell | WAF 边缘节点 |
|------|------------------|---------------|
| 加密 | AES-256 + Base64 双层 | 标准 TLS（无自定义加密） |
| 路径 | 自定义 JSP/ASPX/PHP | 全 403，无路径可访问 |
| 响应 | 特定 Content-Type + 随机 key | 标准 nginx / web cache |
| 方法 | POST 带加密 payload | GET 全部 DENIED |
| 反向代理 | 无（直连） | 有（nginx + web cache） |

结论：Godzilla webshell 的服务器不会有 WAF default-deny。403/ACCESS DENIED + 专业 SSL 证书 + 自定义 WAF header → 排除远控/Webshell，定位为 WAF/CDN 边缘节点。

### C2 特征（不符合其中一个就不像 C2）
- 端口少（1-3 个），不暴露太多
- WAF 不会 default-deny（C2 需要双向通信）
- 通常挂境外云厂商或被控设备
- 不会有 nginx + 自定义 WAF 的完整部署链

### WAF 边缘节点特征
- 7+ 端口 OPEN，全部 403/ACCESS DENIED
- 统一的反代软件（nginx/IIS）+ 自定义 WAF 层
- 自定义 worker ID 格式（`x-ser: i<数字>_c<数字>`）
- 专业 SSL 证书（含组织名、城市）
- 所有 Host/XFF/SNI 绕过全失败

### 实战确认步骤

1. **Quake 查 IP** — 获取端口列表
2. **TCP connect** — 验证端口是否真实 OPEN
3. **SSL 证书提取** — 获取组织名（关键突破口）
4. **WAF 指纹匹配** — server 头 / x-ser 头 / 状态码
5. **绕过尝试** — Host/XFF/SNI/path 各试一次，全失败则实锤 default-deny WAF
6. **whois/IP 归属** — 中国电信家庭宽带 vs 云厂商 vs 海外主机

## 八、实战案例分析

### 案例 1：Nosveass — WAF 边缘节点 (182.40.146.4)

15 个端口返回，全部 403/ACCESS DENIED。SSL 证书暴露了身份：

```
CN = Nosveass, L = Xiamen, Fujian, O = Nosveass
```

**判定：** 非 C2。厦门某公司的自建 WAF/CDN 边缘节点，挂在中国电信山东宽带上。cAdvisor(18080) + kubelet(10250) 在 Quake 中有记录但 TCP 实测 CLOSED。

### 案例 2：传统企业 vs IT 教育

| 维度 | 明信集团 (cdmxjt.com) | 蜗牛学院 (woniuxy.com) |
|------|----------------------|----------------------|
| Quake 资产 | 15 条 | 52 条 |
| 国产系统命中 | 明源 ERP、蓝凌 OA、帆软 | 无 |
| JS 隐藏 URL | 少量 | 69 个（SPA 前端） |

传统企业 → 国产指纹命中高。IT 教育 → 指纹无，JS 暴露多。扫描策略差异：前者重 `--cnasset`，后者重 `--jsrecon`。

## 九、常见陷阱

### 1. 目标格式校验

`-t "cdmxjt.com" --quake` 会因 dddd 原有格式校验失败。需要改 `common/flag.go` 中两处检查（line ~387 和 ~434）。

### 2. Quake 循环搜索

Quake 搜索结果（IP:Port）被重新加入 Targets 后，会再次触发 searchEngine()。用 `defer func() { Quake = false }()` 在第一次搜索完成后关闭 Quake 开关。

### 3. gonmap 噪声

gonmap 会识别所有端口协议（dns/smtp/imap/pop3），在内网扫描中这些信息有用，但外网企业资产扫描中造成大量无用输出。`--no-nmap` 跳过 gonmap，只探测常见 Web 端口。

### 4. httpx 重定向污染

httpx 跟随 Host 头重定向到阿里云/腾讯云等服务商域名。59.82.x.x 段的阿里云企业邮 IP 会返回大量不相关内容。目前无完美解法，建议通过 IP 过滤排除已知云服务商 IP 段。

### 5. JSRecon 缓存未命中

`GlobalHttpBodyHMap` 只存储 httpx 探测时缓存的 body，非 200 响应不会缓存。JS 逆向分析时 body 为空会退回到 `nethttp.Get()`。如果页面需要 cookie/认证才能访问，缓存和 fallback 都会失败。

### 6. 国产路径 404 放大

22 条国产路径 + 原有路径对每个存活 IP 都请求一次。如果目标 IP 数量多（>50），路径扫描请求量会指数增长。

### 7. WAF 绕过引发封禁

WAF 检测使用 `?id=1' OR 1=1--` payload，部分 WAF 会记录并封禁 IP。默认 light 模式不触发。需要用户手动确认后才在 normal/full 模式启用。

## 十、完整一键扫描命令参考

```bash
# 场景 1：传统企业
./dddd -t target.com --quake --qk "$KEY" --mode normal --cnasset --jsrecon --no-nmap

# 场景 2：IT/互联网企业
./dddd -t target.com --quake --qk "$KEY" --mode normal --jsrecon --no-nmap

# 场景 3：纯 WAF 节点
./dddd -t "ip:X.X.X.X" --quake --qk "$KEY" --skip-waf --dry-run

# 场景 4：已知 IP 列表深度扫描
./dddd -t /tmp/targets.txt --mode normal --cnasset --jsrecon --no-nmap

# 场景 5：SSL 证书取证
echo | openssl s_client -connect X.X.X.X:443 2>&1 | openssl x509 -noout -subject -dates
```

### 扫描后输出解读

- `result.txt` — 端口扫描结果 + 指纹匹配结果
- `*.html` — HTML 报告（--mode full 时）
- stdout 中的 `[CN指纹]` — 国产系统命中
- stdout 中的 `[JSRecon]` — JS 逆向发现
- `[Finger]` 行 — 精确指纹匹配（含技术栈）
- `[Finger] http://ip:port/path [StatusCode] [指纹列表] [页面标题]`
