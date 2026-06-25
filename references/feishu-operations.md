# 飞书知识库执行手册 V5.0

## 一、目录结构

### 渗透测试（父 token: FpuYw493RimuENkv1fDcVP5knPe）
- 1.1 Web漏洞实战笔记
- 1.2 内网渗透技巧
- 1.3 渗透工具使用手册
- 1.4 漏洞挖掘&代码审计
- 1.5 思路整理

### 安全运营（父 token: ZZOOwks5xitgSIkyj2Gc235Hndg）
- 2.1 安全运营
- 2.2 应急响应
- 2.3 安全设备运维
- **2.4 威胁情报沉淀**（启用三级自动分类）
- 2.5 威胁检测与狩猎

### 其他（父 token 见 feishu_config.json）
- 3.x 安全合规、4.x 安全开发、5.x 安全研究、99-待分类

> 运行 `init_config.py` 自动扫描并回填 folder_token。

## 二、2.4 三级自动分类

2.4 是唯一启用「子目录→厂商→产品」三层目录的目录。

### 2.4 子目录

| 子目录 | 说明 |
|--------|------|
| 2.4.1 中间件组件漏洞 | Apache/Nginx/Tomcat/Shiro/Redis/Grafana |
| 2.4.2 Web应用系统漏洞 | 国产OA/CMS/企业应用/Drupal |
| 2.4.3 安全厂商设备漏洞 | 防火墙/WAF/堡垒机/VPN |
| 2.4.4 系统&云平台漏洞 | Docker/K8s/云原生/Linux内核 |
| 2.4.5 通用CVE/CNVD情报汇总 | 兜底，不建厂商/产品层 |

### 路由逻辑

```
漏洞文档
  ↓ Step A：大类判断
  → 内核/驱动/LPE ⇒ 1.4
  → 网络设备/安全设备 ⇒ 2.3
  → 其余 ⇒ 2.4
  ↓ Step B：5 个子目录（auto_classifier 映射表）
  ↓ Step C：厂商/产品分层（自动 GET → POST 创建 docx 当文件夹）
  → 输出: 2.4/子目录/厂商/产品/CVE-xxx
```

### 缓存机制
- 会话内查过的 folder_token 缓存到内存 dict
- POST 创建前必先 GET 检查，防重复
- 映射表见 `lib/auto_classifier.py` 的 `VENDOR_PRODUCT_MAP`

## 三、编排器入口

```bash
# 写文档（dedup 默认开启）
python3 pipeline.py write --title "CVE-xxx" --content-file doc.md

# 查重命中 → status: "already_exists" + doc_url
# 查重未命中 → 走完整流程（分类→写入→验证→修复）

# 其他命令
python3 pipeline.py organize        # 垃圾扫描
python3 pipeline.py cleanup-99      # 清理待分类
python3 pipeline.py delete --doc-token xxx --confirm
python3 pipeline.py move --doc-token xxx --target-token xxx
python3 pipeline.py classify --title "xxx" --content-file doc.md
```

## 四、健壮性
- **防重复**：POST 创建前必先 GET 检查，失败重试 3 次
- **Fix Loop**：写入验证失败后最多 3 次自动修复
- **Dedup**：默认开启，搜到已有文档直接返回链接，不走写入流程
