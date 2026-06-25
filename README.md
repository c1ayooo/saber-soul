# Saber Soul — 飞书知识库 Agent Skill

飞书知识库自动化维护工具集，配合 Hermes/LLM Agent 使用。

> ⚠️ **本工具依赖飞书知识库 API，没有飞书知识库环境无法直接使用。**
> 下方「使用前提」列出了完整的前置条件。

---

## 使用前提

### 1. 飞书应用

需要自行注册一个飞书应用，获得 `APP_ID` 和 `APP_SECRET`：

1. 打开 [飞书开发者控制台](https://open.feishu.cn/app) → 创建企业自建应用
2. 开通权限：`wiki:wiki`、`wiki:wiki:readonly`、`docx:document`
3. **发布应用**（添加权限后必须发布才生效）
4. 把应用加到目标知识库成员（管理员角色）

> 如果只需要分类器功能、不写知识库，可以跳过此步骤。见「独立模块复用」。

### 2. 配置

```bash
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
export FEISHU_SPACE_ID=xxx   # 知识库 space_id
```

或在 `feishu_config.json` 中配置（运行 `init_config.py` 自动生成）。

---

## 快速开始

```bash
git clone https://github.com/c1ayooo/saber-soul.git ~/.hermes/skills/saber_soul
cd ~/.hermes/skills/saber_soul

# 扫描知识库目录树，生成 feishu_config.json
python3 scripts/init_config.py

# 写入一篇文档
python3 scripts/pipeline.py write --title "标题" --content-file doc.md
```

将 `SKILL.md` 设为 Agent 系统提示词即可让 LLM Agent 自动调用。

---

## 项目结构

```
saber_soul/
├── SKILL.md                    # 【必选】主指令（LLM Agent 系统提示词）
├── feishu_config.json          # 用户配置（运行时生成，.gitignore）
├── .gitignore
├── README.md
├── references/                 # Agent 按需加载的参考文档
│   ├── document-templates.md   # 16 种文档模板
│   ├── feishu-operations.md    # 执行手册与目录结构
│   ├── classification_config.json  # 分类规则 + 厂商/产品映射
│   └── format-rules.md         # 格式规则细则
├── scripts/                    # 入口脚本
│   ├── pipeline.py             # 【唯一入口】全流程编排器
│   └── init_config.py          # 首次初始化（扫描目录树）
├── lib/                        # 核心模块
│   ├── config.py               # 统一配置管理
│   ├── feishu_auth.py          # 飞书认证模块
│   ├── auto_classifier.py      # 自动分类 + 建文件夹
│   ├── auto_organizer.py       # 垃圾检测 + 整理
│   └── feishu_doc.py           # 文档核心（读/写/修/验/删/移/图）
└── assets/
```

---

## 核心功能

| 功能 | 命令 |
|------|------|
| 写入文档 | `python3 scripts/pipeline.py write --title "标题" --content-file doc.md` |
| 扫描整理 | `python3 scripts/pipeline.py organize` |
| 清理 99 待分类 | `python3 scripts/pipeline.py cleanup-99` |
| 删除文档 | `python3 scripts/pipeline.py delete --doc-token xxx --confirm` |
| 移动文档 | `python3 scripts/pipeline.py move --doc-token xxx --target-token xxx` |
| 仅分类 | `python3 scripts/pipeline.py classify --title "..." --content-file doc.md` |

### 写入全流程

```
Pre-Check → Dedup查重 → Route分类 → Auto-Classify建文件夹 → Write写入 → Verify验证
```

- 分类：关键词匹配优先（0 token），不命中走 LLM fallback
- 查重：默认开启，命中直接返回已有文档链接
- 验证：写入后内置验证，失败自动修复（最多 3 次）

### 文档类型支持

| 板块 | 模板 |
|:----|:-----|
| 渗透测试 | 作战记录、JS逆向分析、内网渗透、工具文档、思路整理 |
| 安全运营 | 安全运营、应急响应、设备运维、CVE情报、威胁检测 |
| 安全合规 | 等保、合规自查、整改台账 |
| 安全开发 | Python脚本、Go工具、自动化检测、工具封装 |
| 安全研究 | 自由段 |

---

## 配置

| 变量 | 必须 | 说明 |
|------|:----:|------|
| `FEISHU_APP_ID` | ✅ | 飞书应用 ID |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用密钥 |
| `FEISHU_SPACE_ID` | ✅ | 知识库 space_id |
| `SABER_CONFIG_DIR` | ❌ | 自定义配置目录（默认 `~/.hermes/skills/saber_soul`） |

详细配置见 `references/feishu-operations.md`。

---

## 独立模块复用

无需飞书知识库也能独立使用的模块：

| 模块 | 功能 | 依赖 |
|:----|:----|:-----|
| `lib/auto_classifier.py` + `classification_config.json` | 自动分类（关键词匹配，0 token） | 无 |
| `lib/feishu_doc.py` 中的 `ContentParser` | Markdown 转飞书 Block 数组 | 无 |
| `lib/config.py` | 配置管理框架 | 无 |

```python
from lib.auto_classifier import auto_route

result = auto_route("MySQL UDF 提权 — 决策树", "文档正文...")
print(result.folder_key, result.doc_type)  # → "1.2" "内网渗透"
```

---

## 更新

```bash
cd ~/.hermes/skills/saber_soul && git pull
```

---

## License

MIT
