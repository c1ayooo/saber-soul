## 问题

SOC/SIEM 平台需要接入威胁情报查询能力，对 DNS 请求、外连 IP、可疑文件 Hash 等进行自动化研判，但 NGTIP 情报查询 API 的接口参数和响应结构复杂，需要一份清晰的参考。

## 认证方式

情报查询 API 支持两种认证方式：

- **API Key 校验**：每个请求带 `apikey` 参数
- **Token 校验**：请求带 `apikey` + `token` + `timestamp`，其中 `timestamp` 为秒级时间戳，`token = Base64URLEncode(HMAC_SHA1(apikey + auth_timestamp, salt))`

## 通用请求结构

- 服务地址：`http://<IP>:8090`
- 接口前缀：统一为 `/tip_api/v5`
- 通信协议：HTTP / HTTPS
- 请求方法：GET / POST
- 字符编码：UTF-8

---

## 一、失陷检测及恶意域名检测

对办公网/生产网对外访问场景的 IP/Domain 进行分析，识别远控（C2）、恶意软件（Malware）、矿池等威胁。

- **地址**：`GET/POST /tip_api/v5/dns`

**请求参数：**

| 参数 | 必须 | 说明 |
|------|:----:|------|
| `apikey` | ✅ | API Key |
| `value` | ✅ | 待查询的域名或 IP |
| `token` | 动态 | Token 校验时必传 |
| `timestamp` | 动态 | Token 校验时必传 |

**响应参数：**

- `verdict` — 判定结果（malicious / suspicious / clean / unknown）
- `severity` — 严重级别（high / medium / low / info）
- `confidence` — 可信度（1-10）
- `threat_types` — 威胁类型列表
- `tags` — 关联威胁标签

**cURL 示例：**

```bash
curl "http://<IP>:8090/tip_api/v5/dns?apikey=xxx&value=evil.example.com"
```

**Python 示例：**

```python
import requests

resp = requests.get("http://<IP>:8090/tip_api/v5/dns", params={
    "apikey": "xxx",
    "value": "evil.example.com",
})
print(resp.json())
```

---

## 二、IP 信誉查询

针对入站场景的 IP 进行分析，提供地理位置、ASN 信息和风险判定，识别漏洞利用（exploit）、傀儡机（Zombie）等。

- **地址**：`GET/POST /tip_api/v5/ip`

**请求参数：**

| 参数 | 必须 | 说明 |
|------|:----:|------|
| `apikey` | ✅ | API Key |
| `value` | ✅ | 待查询的 IP |

**响应参数：**

- `ip` — 查询 IP
- `location` — 地理位置（国家/城市）
- `asn` — ASN 信息
- `isp` — 运营商
- `verdict` — 判定结果
- `severity` — 严重级别
- `threat_types` — 威胁类型
- `history` — 历史情报记录

---

## 三、文件信誉检测

对文件 Hash（MD5/SHA1/SHA256）进行分析，返回多引擎检测结果和沙箱分析报告。

- **地址**：`GET/POST /tip_api/v5/hash`

**请求参数：**

| 参数 | 必须 | 说明 |
|------|:----:|------|
| `apikey` | ✅ | API Key |
| `value` | ✅ | 待查询的 Hash 值 |

**响应参数：**

- `md5` / `sha1` / `sha256` — 文件 Hash
- `threat_score` — 威胁评分（0-100）
- `threat_level` — 威胁等级
- `malware_family` — 病毒家族
- `tags` — 标签信息
- `analysis_env` — 分析环境

---

## 四、漏洞情报查询

按漏洞编号、状态、时间等条件组合查询漏洞信息，获取 0Day 和公开漏洞的基础信息、处置优先级（VPT）、PoC、处置建议。

- **地址**：`GET/POST /tip_api/v5/vuln`

**请求参数：**

| 参数 | 必须 | 说明 |
|------|:----:|------|
| `apikey` | ✅ | API Key |
| `cve_id` | ❌ | CVE 编号 |
| `status` | ❌ | 漏洞状态 |
| `start_time` | ❌ | 开始时间 |
| `end_time` | ❌ | 结束时间 |
| `is_highrisk` | ❌ | 仅高风险 |

> 若无筛选条件或仅为 `is_highrisk`，仅返回最近 24h 更新的漏洞列表。

**响应参数：**

- `cve_id` — CVE 编号
- `cvss_score` — CVSS 评分
- `vpt_score` — 处置优先级评分
- `status` — 漏洞状态
- `description` — 漏洞描述
- `poc` — PoC/EXP 信息
- `suggestion` — 处置建议
- `patch_info` — 补丁信息

---

## 五、IP 地理位置查询

获取 IP 地理位置信息。

- **地址**：`GET/POST /tip_api/v5/location`

**请求参数：**

| 参数 | 必须 | 说明 |
|------|:----:|------|
| `apikey` | ✅ | API Key |
| `value` | ✅ | 待查询的 IP |

**响应参数：**

- `ip` — 查询 IP
- `continent` — 大洲
- `country` — 国家
- `province` — 省份
- `city` — 城市
- `isp` — 运营商
- `latitude` — 纬度
- `longitude` — 经度

---

## 附录

### 响应 Code 对照

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 10001 | 认证失败 |
| 10002 | 参数错误 |
| 10003 | 无权限 |
| 10004 | 频率超限 |
| 10005 | 余额不足 |

### 威胁类型全集

| 威胁分类 | 子类 |
|----------|------|
| C2（远控） | Beacon、Trojan、RAT |
| Phishing | 钓鱼网站、钓鱼邮件 |
| Suspicious | 扫描器、代理、VPN、动态IP、矿池 |
| Brute Force | 暴力破解、撞库 |
| Info | 网关出口、IDC、爬虫、移动基站 |
