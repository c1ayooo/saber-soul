## 问题

运营团队需要将微步 NGTIP 平台的威胁情报、资产数据、联动处置等能力集成到内部自动化运维流程中，但缺乏统一的 API 接口参考。各接口的认证方式、请求格式、返回结构不统一，每次对接都需要重新查阅官方 PDF 文档。

## 认证方式

NGTIP 平台功能 API 统一通过 API Key 认证，支持两种模式：

- **API Key 校验（静态）**：每个请求 Header 中传入 `APIKEY` 即可
- **Token 校验（动态）**：Header 中传入 `APIKEY` + `TOKEN` + `TIMESTAMP`。`timestamp` 为秒级时间戳，`token = Base64URLEncode(HMAC_SHA1(apikey + auth_timestamp, salt))`

> 免密登录接口额外要求 Token 校验。

## 通用请求结构

- 服务地址：采用 Web 访问相同的协议、IP 和端口
- 接口前缀：统一为 `/tip/v5`
- 通信协议：支持 HTTP / HTTPS（平台管理-系统管理-安全配置 中切换）
- 请求方法：POST / GET
- 字符编码：UTF-8

---

## 一、情报管理

### 1.1 新增情报

写入手动添加类型情报源的新情报数据。

- **地址**：`POST /tip/v5/manually`
- **前置**：需先在 NGTIP 平台 → 情报源管理 → 创建手动添加类型情报源

**请求参数（Body JSON）：**

IP 信誉情报：

```json
{
  "data_source_id": "情报源ID",
  "mal_type": 2,
  "confidence": 3,
  "source_type": "ip",
  "value": "8.8.8.8"
}
```

失陷检测/恶意域名情报：

```json
{
  "data_source_id": "情报源ID",
  "mal_type": 9,
  "confidence": 3,
  "source_type": "domain",
  "value": "evil.example.com"
}
```

HASH 情报：

```json
{
  "data_source_id": "情报源ID",
  "mal_type": 11,
  "confidence": 3,
  "source_type": "hash",
  "value": "d41d8cd98f00b204e9800998ecf8427e"
}
```

漏洞情报：

```json
{
  "data_source_id": "情报源ID",
  "mal_type": 1,
  "confidence": 3,
  "source_type": "vuln",
  "value": "CVE-2024-12345"
}
```

### 1.2 情报导出

导出所有手动添加/文件下载的情报源数据。

- **地址**：`POST /tip/v5/ioc_list`

**请求参数（Body JSON）：**

```json
{
  "data_source_id": "情报源ID",
  "source_type": "ip"
}
```

### 1.3 情报数量查询

查询最近 1 年情报数量及命中信息。

- **地址**：`POST /tip/v5/intelligence_count`

### 1.4 重保情报导出

导出微步 HW 重保情报。

- **地址**：`GET /tip/hw/data`

---

## 二、资产管理

### 2.1 新增资产

写入资产数据。

- **地址**：`POST /tip/v5/add_asset`

### 2.2 更新/删除资产

更新已存在资产数据或执行删除操作。

- **地址**：`POST /tip/v5/update_asset`

---

## 三、用户管理

### 3.1 新增用户

通过 API 创建系统用户。

- **地址**：`POST /tip/v5/add_user`

### 3.2 免密登录

免密登录 NGTIP 平台。该接口需要额外的 Token 校验。

- **地址**：`GET /tip/v5/user/login_with_token`

---

## 四、情报生产

### 4.1 上传样本

上传样本文件触发情报生产。

- **地址**：`POST /tip/v5/sample_produce/upload_file`
- **频率限制**：1 次/秒
- **样本大小限制**：256MB

### 4.2 查询情报

查询已生产的样本情报结果。

- **地址**：`GET /tip/v5/sample_produce`

---

## 五、设备联动

### 5.1 下发规则

执行下发阻断规则、删除规则、添加/删除白名单操作。

- **地址**：`GET /tip/v5/distribution_rules`
- **频率限制**：1 次/秒
- **支持操作**：
- 下发阻断规则
- 下发删除规则
- 添加至白名单
- 从白名单中删除

---

## 六、漏洞情报

### 6.1 漏洞资产匹配

获取企业资产漏洞风险结果。

- **地址**：`POST /tip/v5/vuln_alert`
- **适用权限**：漏洞情报基础版 / 高级版

**响应参数：**

- `items[].vuln_info` — 漏洞详情
- `items[].asset_info` — 关联资产详情

---

## 七、态势情报

### 7.1 订阅查询

获取订阅标签关联的态势情报详情。

- **地址**：`POST /tip/v5/human_intel_subscription`
- **适用权限**：态势情报付费版

---

## 八、攻击画像

### 8.1 行业攻击情报

获取行业攻击情报结果。

- **地址**：`POST /tip/v5/industry_attack_share`

---

## 附录：响应 Code 对照

所有接口返回统一的 Code 和 Msg 响应结构：

```json
{
  "code": 0,
  "msg": "success",
  "data": {}
}
```

| Code | 含义 |
|------|------|
| 0 | 成功 |
| 10001 | 认证失败 |
| 10002 | 参数错误 |
| 10003 | 无权限 |
| 10004 | 频率超限 |
