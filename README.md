# Saber Soul — 飞书知识库 Agent Skill

飞书知识库自动化维护工具集，配合 Hermes/LLM Agent 使用。

## 快速开始

```bash
git clone https://github.com/c1ayooo/saber-soul.git ~/.hermes/skills/saber_soul
cd ~/.hermes/skills/saber_soul
python3 scripts/init_config.py
```

按提示输入 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `SPACE_ID`，自动扫描知识库目录树并生成 `feishu_config.json`。

将 `SKILL.md` 设为你的 Agent 系统提示词即可使用。

## 项目结构

```
saber_soul/
├── SKILL.md                    # 【必选】主指令
├── feishu_config.json          # 用户配置（运行时生成，gitignore）
├── .gitignore
├── README.md
├── references/                 # 扩展文档（Agent 按需加载）
│   ├── document-templates.md   # 16 种文档模板
│   ├── feishu-operations.md    # 执行手册
│   └── classification_config.json  # 19 条分类规则 + 厂商/产品映射
├── scripts/                    # 辅助脚本
│   ├── pipeline.py             # 【唯一入口】编排器
│   └── init_config.py          # 首次初始化
├── lib/                        # 核心模块
│   ├── config.py               # 统一配置管理
│   ├── feishu_auth.py          # 认证模块
│   ├── auto_classifier.py      # 自动分类 + 建文件夹
│   ├── auto_organizer.py       # 垃圾检测 + 整理
│   └── feishu_doc.py           # 文档核心（读/写/修/验/删/移/图）
└── assets/                     # 素材
```

## 核心功能

| 功能 | 命令 |
|------|------|
| 写入文档 | `python3 scripts/pipeline.py write --title "标题" --content-file doc.md` |
| 扫描整理 | `python3 scripts/pipeline.py organize` |
| 清理 99 待分类 | `python3 scripts/pipeline.py cleanup-99` |
| 删除文档 | `python3 scripts/pipeline.py delete --doc-token xxx --confirm` |
| 移动文档 | `python3 scripts/pipeline.py move --doc-token xxx --target-token xxx` |

### 写入全流程

```
Pre-Check → Dedup查重 → Route分类 → Auto-Classify建文件夹 → Write写入 → Verify验证
```

- 分类用关键词匹配优先（0 token），不命中才 LLM fallback
- CVE 文档无 PoC 时自动暂停，等待用户决策
- 写入后内置验证，失败自动修复（最多 3 次）

### 文档类型支持

覆盖渗透测试、安全运营、安全合规、安全开发、安全研究五大板块共 16 种文档模板。

## 配置

| 变量 | 必须 | 说明 |
|------|------|------|
| `FEISHU_APP_ID` | 是 | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 是 | 飞书应用密钥 |
| `FEISHU_SPACE_ID` | 是 | 知识库 space_id |
| `SABER_CONFIG_DIR` | 否 | 自定义配置目录 |

详细配置见 `references/feishu-operations.md` 第九节。

## 更新

```bash
cd ~/.hermes/skills/saber_soul && git pull
```

## License

MIT
