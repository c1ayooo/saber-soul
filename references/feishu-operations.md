# 飞书知识库执行手册 V4.2

## 一、目录结构（含 folder_token）

### 一、渗透测试（父 token: FpuYw493RimuENkv1fDcVP5knPe）
1.1 Web漏洞实战笔记：RUN_INIT_TO_GET_TOKEN
1.2 内网渗透技巧：RUN_INIT_TO_GET_TOKEN
1.3 渗透工具使用手册：RUN_INIT_TO_GET_TOKEN
1.4 漏洞挖掘&代码审计：RUN_INIT_TO_GET_TOKEN
1.5 思路整理：RUN_INIT_TO_GET_TOKEN

### 二、安全运营（父 token: ZZOOwks5xitgSIkyj2Gc235Hndg）
2.1 安全运营：RUN_INIT_TO_GET_TOKEN
2.2 应急响应：RUN_INIT_TO_GET_TOKEN
2.3 安全设备运维：RUN_INIT_TO_GET_TOKEN
2.4 威胁情报沉淀：RUN_INIT_TO_GET_TOKEN
2.5 威胁检测与狩猎：RUN_INIT_TO_GET_TOKEN

### 三、安全合规（父 token: SEglwYlokiUfYYkbGjTc6ZpnnZg）
3.1 等保核心知识点：RUN_INIT_TO_GET_TOKEN
3.2 合规自查清单：RUN_INIT_TO_GET_TOKEN
3.3 整改方案与台账：RUN_INIT_TO_GET_TOKEN

### 四、安全开发（父 token: BYZHwqEfoixpYxkJfYOcHvsxndd）
4.1 Python安全脚本：RUN_INIT_TO_GET_TOKEN
4.2 Go安全工具：RUN_INIT_TO_GET_TOKEN
4.3 自动化检测：RUN_INIT_TO_GET_TOKEN
4.4 工具封装：RUN_INIT_TO_GET_TOKEN

### 五、安全研究（父 token: {待创建}）
5 安全研究：RUN_INIT_TO_GET_TOKEN
99-待分类：RUN_INIT_TO_GET_TOKEN

---

## 二、2.4 威胁情报沉淀 — 三级自动分类

> 2.4 是唯一启用「厂商→产品」三级自动分类的目录。其他目录保持二级结构。

### 2.4 子目录（需首次运行自动建文件夹时 GET 枚举获取 token 后回填）

| 子目录名 | node_token | 说明 |
|---------|-----------|------|
| 2.4.1 中间件组件漏洞 | `{待回填}` | Apache/Nginx/Tomcat/Shiro/Redis/Grafana/Prometheus 等 |
| 2.4.2 Web应用系统漏洞 | `{待回填}` | 国产OA/CMS/企业应用/React/Next.js/Drupal 等 |
| 2.4.3 安全厂商设备漏洞 | `{待回填}` | 防火墙/WAF/堡垒机/VPN 等 |
| 2.4.4 系统&云平台漏洞 | `{待回填}` | Docker/K8s/云原生/Linux 内核/云存储 等 |
| 2.4.5 通用CVE/CNVD情报汇总 | `{待回填}` | 兜底分类，不建厂商/产品子层 |

### 路由逻辑

```
漏洞文档
  ↓ Step A：大类判断
  → 内核/驱动/LPE      ⇒ 1.4（不进 2.4）
  → 网络设备/安全设备   ⇒ 2.3（不进 2.4）
  → 其余（中间件/Web应用/云原生/数据库/CMS/国产应用）⇒ 进 2.4
  ↓ Step B：2.4 下 5 个子目录判断（查映射表）
  ↓ Step C：厂商/产品分层（查映射表，自动建文件夹）
```

### 漏洞分类规则

| 漏洞类型 | 归档路径 | 走厂商/产品分层 |
|---------|---------|---------------|
| Web 漏洞组件（Apache/Spring/Nginx等） | 2.4/中间件组件漏洞 | ✅ 是 |
| 内核/驱动/LPE | 1.4 | ❌ 否 |
| 网络设备/安全设备 | 2.3 | ❌ 否 |
| 国产应用/OA/ERP | 2.4/Web应用系统漏洞 | ✅ 是 |
| 云原生/容器 | 2.4/系统&云平台漏洞 | ✅ 是 |
| 数据库 | 2.4/中间件组件漏洞 | ✅ 是 |
| CMS/建站系统 | 2.4/Web应用系统漏洞 | ✅ 是 |

> CMS/建站系统从 1.1 调整到 2.4，按厂商子文件夹分类。

---

## 三、自动分类映射表

> 映射表完整内容在 `lib/auto_classifier.py` 的 `VENDOR_PRODUCT_MAP` 和 `ALIAS_MAP` 中维护。
> LLM 不需要读取映射表内容，只需调用 `AutoClassifier.resolve_folder()` 即可获得 folder_token。
> 映射表更新时改 Python 代码，不改本文件。

分类规则速查（仅用于 LLM 理解路由逻辑，具体厂商/产品匹配由代码完成）：

| 漏洞类型 | 归档路径 | 走厂商/产品分层 |
|---------|---------|---------------|
| Web 漏洞组件（Apache/Spring/Nginx等） | 2.4/中间件组件漏洞 | ✅ 是 |
| 内核/驱动/LPE | 1.4 | ❌ 否 |
| 网络设备/安全设备 | 2.3 | ❌ 否 |
| 国产应用/OA/ERP | 2.4/Web应用系统漏洞 | ✅ 是 |
| 云原生/容器 | 2.4/系统&云平台漏洞 | ✅ 是 |
| 数据库 | 2.4/中间件组件漏洞 | ✅ 是 |
| CMS/建站系统 | 2.4/Web应用系统漏洞 | ✅ 是 |

## 四、自动建文件夹流程

> 飞书 Wiki API 不支持创建文件夹类型节点（`obj_type` 仅支持 docx/sheet/bitable/mindnote/file）。
> **用 docx 节点当「文件夹」**：创建 `obj_type=docx` 的 wiki 节点，title=厂商/产品名，其 `node_token` 即可作为子节点的 `parent_node_token`。

### 前置 API

| 操作 | 方法 | 端点 |
|------|------|------|
| 列子节点 | GET | `/wiki/v2/spaces/{space_id}/nodes?parent_node_token={parent}&page_size=50` |
| 创建节点 | POST | `/wiki/v2/spaces/{space_id}/nodes`，body `{"parent_node_token":"...","obj_type":"docx","node_type":"origin","title":"..."}` |
| 移动节点 | POST | `/wiki/v2/spaces/{space_id}/nodes/{node_token}/move`，body `{"target_parent_token":"..."}` |

### 流程

```
输入: 2.4 子目录 token(父) + 厂商(可空) + 产品
  │
  ├─ Step 1  若需厂商层 → 父=子目录token；否则 → 父=子目录token（直接建产品层）
  │
  ├─ Step 2  【厂商层】GET 检查是否存在
  │   遍历 items，匹配 title==厂商
  │   ├─ 命中 → 取 node_token（写缓存）
  │   └─ 未命中 → POST 创建 docx 节点 {"obj_type":"docx","title":"Apache"}
  │
  ├─ Step 3  【产品层】GET 检查是否存在
  │   ├─ 命中 → 取 node_token（写缓存）
  │   └─ 未命中 → POST 创建 docx 节点 {"obj_type":"docx","title":"Tomcat"}
  │
  ├─ Step 4  write_feishu_doc.py --folder-token "{产品_token}"
  │
  └─ 输出: 2.4/子目录/厂商/产品/CVE-xxxx + 文档 URL
```

### 健壮性
- **缓存**：会话内已查/已建的 token 缓存到内存 dict，避免重复 GET/POST。
- **防重复**：POST 创建前必先 GET 检查；POST 失败重试 3 次。
- **持久化**：会话结束后把 token 映射回填到本文件 token 表，下次直接读跳过 Step 2/3。

---

## 五、编排器脚本（唯一入口）

**脚本路径：** `~/.hermes/skills/saber_soul/script/feishu_pipeline_orch.py`

### 用法
```bash
python3 ~/.hermes/skills/saber_soul/script/feishu_pipeline_orch.py "文档标题" "folder_token" "/path/to/content.md"
```

### 内部执行流（不可修改）
1. **Pre-Check**：调用 `read_feishu_doc.py --check-only`
2. **Route**：由 Hermes 调用 `kb-directory-structure` 传入 folder_token
3. **Auto-Classify**：【仅 2.4】查映射表 → 自动建文件夹 → 获取产品层 token
4. **Write**：调用 `write_feishu_doc.py`
5. **Verify**：读取 write 返回的内置验证结果（verify_blocks / verify_plain_text）。仅当内置验证返回 partial/失败时才调用 `read_feishu_doc.py --check --strict`
6. **Fix Loop**：失败 → `fix_feishu_doc.py` → 回到 Step 5 → 最多 3 次
7. **Supplement**：调用 `chart_renderer.py`（配图）、`mv_feishu_doc.py`（归档）
8. **Deliver**：输出链接

---

## 六、工具补丁

### 1. mv_feishu_doc.py（移动文档）
路径：`~/.hermes/skills/saber_soul/script/mv_feishu_doc.py`
功能：在 Wiki 目录间移动节点。

### 2. chart_renderer.py（Mermaid 图表渲染）
路径：`~/.hermes/skills/saber_soul/script/chart_renderer.py`
功能：Mermaid 语法渲染 PNG + PIL 裁剪空白边 + 飞书 Image Block 三步法插入文档。
用法：`python3 chart_renderer.py --mermaid-text 'graph TD; A-->B' --doc-token "xxx"`

### 3. feishu-tool CLI（补充能力，需单独安装）
安装：`npm install -g feishu-mcp@latest`
配置：`feishu-tool config set FEISHU_APP_ID xxx` / `feishu-tool config set FEISHU_APP_SECRET xxx`

补充 saber-soul 不具备的 3 个能力：

| 能力 | 命令 | 使用场景 |
|------|------|---------|
| 搜索文档 | `feishu-tool search_feishu_documents '{"searchKey":"CVE-2026-20253","searchType":"wiki"}'` | 入库前查重，避免重复文档 |
| 原生 Mermaid 白板 | `feishu-tool fill_whiteboard_with_plantuml '{"whiteboards":[...]}'` | 比 PNG 更原生，飞书内置渲染可编辑 |
| 原生表格 | `feishu-tool create_feishu_table '{"documentId":"xxx",...}'` | 资产列表/风险矩阵等多列表格场景 |

> 这 3 个能力通过 `feishu-tool` CLI 调用，不需要加载到提示词中（0 token）。
> 完整参数见 Feishu-Skill 的 `reference/document.md`。

### 4. quake CLI（360Quake 资产测绘，需单独安装）
安装：从 https://github.com/360quake/quake_go 下载或 `go build .`
配置：`quake init <QUAKE_API_KEY>`

| 命令 | 用途 |
|------|------|
| `quake search 'service:"Splunk" AND port:8000' -st 0 -sz 5` | 搜索服务暴露面 |
| `quake search 'response:"Server: Splunkd"' -st 0 -sz 1` | 精准指纹匹配 |
| `quake host 'service:http' -st 0 -sz 20` | 主机维度查询 |
| `quake info` | 查看账户配额 |

> CVE 文档「五、测绘」段必须调用 quake CLI 或 HTTP API 获取实际暴露数据，不可杜撰。

---

## 七、自动修复闭环

| 失败场景 | 自动行为 |
|---------|---------|
| 标题重复 | fix_feishu_doc.py 清理 |
| 命令混文本 | fix_feishu_doc.py 转换 |
| 字数不足 | 终止，要求补充内容 |
| `**bold**` | ❌ 不清理（write 支持） |
| 管道符表格 | ❌ 不清理（write 阶段自动转换） |

---

## 八、自检清单（每次执行前）

```
□ 通过 feishu_pipeline_orch.py 执行
□ folder_token 来自 kb-directory-structure
□ Pre-Check 通过
□ Verify 通过
□ 未直接调用 write_feishu_doc.py
□ 【2.4 专用】查了映射表确定厂商/产品？
□ 【2.4 专用】执行了自动建文件夹流程？
□ folder_token 使用了最终产品层 token？
```

---

## 九、自定义配置（feishu_config.json 可选项）

`~/.hermes/skills/saber_soul/feishu_config.json` 支持以下可选字段，不填则使用代码内置默认值。所有配置项优先级：**环境变量 > feishu_config.json > 代码默认值**。

### 环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `FEISHU_APP_ID` | — | 飞书应用 ID |
| `FEISHU_APP_SECRET` | — | 飞书应用密钥 |
| `FEISHU_API_BASE` | `https://open.feishu.cn/open-apis` | API 地址 |
| `FEISHU_SPACE_ID` | — | 飞书知识库 space_id |
| `SABER_CONFIG_DIR` | `~/.hermes/skills/saber_soul` | 自定义配置目录 |

### feishu_config.json 完整配置示例

```json
{
  "FEISHU_APP_ID": "cli_xxx",
  "FEISHU_APP_SECRET": "xxx",
  "SPACE_ID": "xxx",

  "classify_rules": [
    {
      "keywords": ["关键词1", "关键词2"],
      "negative_keywords": ["排除词"],
      "folder": "1.1",
      "type": "文档类型",
      "weight": 3
    }
  ],

  "vendor_map": {
    "中间件组件漏洞": {
      "YourVendor": ["Product1", "Product2"]
    }
  },

  "alias_map": {
    "别名": ["厂商", "产品"]
  },

  "garbage_rules": [
    {
      "name": "自定义垃圾规则",
      "keywords": ["test", "TODO"],
      "min_hits": 2,
      "reason": "测试残留"
    },
    {
      "name": "内容过少",
      "min_chars": 50,
      "reason": "内容极少"
    },
    {
      "name": "标题废弃",
      "title_patterns": ["^副本", "^copy"],
      "reason": "疑似废弃"
    }
  ],

  "prohibited_words": ["可能", "尝试", "看看"],
  "prohibited_map": {
    "可能": "可",
    "尝试": "执行"
  },

  "command_patterns": [
    "^curl\\b", "^nmap\\b", "^验证命令:"
  ],

  "log_level": "DEBUG"
}
```

### 合并规则

| 配置项 | 合并行为 |
|--------|---------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `SPACE_ID` | 直接取值 |
| `classify_rules` | **完全替换**默认规则（不合并） |
| `vendor_map` / `alias_map` | 与默认**深度合并** |
| `garbage_rules` | **完全替换**默认垃圾规则 |
| `prohibited_words` | **完全替换**默认禁词列表 |
| `prohibited_map` | 与默认**深度合并**（追加映射） |
| `command_patterns` | 与默认**合并去重**（追加模式） |
| `log_level` | 直接取值 |
