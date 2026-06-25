#!/usr/bin/env python3
"""
首次初始化脚本 — 扫描飞书知识库目录树，生成 feishu_config.json

用法：
  python3 init_config.py

交互式输入 FEISHU_APP_ID / FEISHU_APP_SECRET / SPACE_ID 后，
自动扫描知识库目录树并将 folder_tokens 持久化到 feishu_config.json。
"""

import json
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # saber_soul/
sys.path.insert(0, str(HERE))

from lib.config import get_config, CONFIG_FILE
from lib.feishu_auth import api_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("saber.init")


# 知识库一级目录映射
FOLDER_KEYS = [
    ("1.1", "Web漏洞实战笔记"),
    ("1.2", "内网渗透技巧"),
    ("1.3", "渗透工具使用手册"),
    ("1.4", "漏洞挖掘&代码审计"),
    ("1.5", "思路整理"),
    ("2.1", "安全运营"),
    ("2.2", "应急响应"),
    ("2.3", "安全设备运维"),
    ("2.4", "威胁情报沉淀"),
    ("2.5", "威胁检测与狩猎"),
    ("3.1", "等保核心知识点"),
    ("3.2", "合规自查清单"),
    ("3.3", "整改方案与台账"),
    ("4.1", "Python安全脚本"),
    ("4.2", "Go安全工具"),
    ("4.3", "自动化检测"),
    ("4.4", "工具封装"),
    ("5", "安全研究"),
    ("99", "99-待分类"),
]

# 2.4 子目录
SUBDIR_24 = [
    "2.4.1",
    "2.4.2",
    "2.4.3",
    "2.4.4",
    "2.4.5",
]

SUBDIR_24_NAMES = [
    "中间件组件漏洞",
    "Web应用系统漏洞",
    "安全厂商设备漏洞",
    "系统&云平台漏洞",
    "通用CVE/CNVD情报汇总",
]


def main():
    cfg = get_config()

    # ── 收集凭证 ──
    app_id = os.environ.get("FEISHU_APP_ID") or input("FEISHU_APP_ID: ").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET") or input("FEISHU_APP_SECRET: ").strip()
    space_id = os.environ.get("FEISHU_SPACE_ID") or input("SPACE_ID (飞书知识库 space_id): ").strip()

    # 临时写入以便认证模块使用
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret
    os.environ["FEISHU_SPACE_ID"] = space_id

    # ── 持久化配置 ──
    config_data = _load_or_create_config()
    config_data["FEISHU_APP_ID"] = app_id
    config_data["FEISHU_APP_SECRET"] = app_secret
    config_data["SPACE_ID"] = space_id

    # ── 扫描知识库目录树 ──
    logger.info("正在扫描知识库目录树 ...")
    folder_tokens = _scan_tree(space_id)
    config_data["folder_tokens"] = folder_tokens

    # ── 保存 ──
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    logger.info("配置已保存到 %s", CONFIG_FILE)
    _print_summary(folder_tokens)


def _load_or_create_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _scan_tree(space_id: str) -> dict:
    """
    扫描知识库一级目录，返回 folder_tokens 映射。

    对所有一级目录递归枚举子节点，匹配 FOLDER_KEYS 中的名称。
    对 2.4 目录额外扫描 5 个子目录。
    """
    folder_tokens: dict[str, str] = {}

    try:
        root_nodes = api_request(
            "GET", f"/wiki/v2/spaces/{space_id}/nodes",
            query={"page_size": 50},
        )
    except RuntimeError as e:
        logger.error("扫描失败: %s", e)
        return folder_tokens

    items = root_nodes.get("items", [])

    # 匹配一级目录
    for item in items:
        title = item.get("title", "")
        token = item["node_token"]

        for key, name in FOLDER_KEYS:
            if title == name or name in title:
                folder_tokens[key] = token
                logger.info("  ✓ %s → %s", key, token[:20])
                break

    # 扫描 2.4 子目录
    token_24 = folder_tokens.get("2.4", "")
    if token_24:
        try:
            sub_nodes = api_request(
                "GET", f"/wiki/v2/spaces/{space_id}/nodes",
                query={"parent_node_token": token_24, "page_size": 50},
            )
            for item in sub_nodes.get("items", []):
                title = item.get("title", "")
                token = item["node_token"]
                for i, name in enumerate(SUBDIR_24_NAMES):
                    if title == name:
                        folder_tokens[f"2.4_{name}"] = token
                        logger.info("  ✓ 2.4/%s → %s", name, token[:20])
                        break
        except RuntimeError:
            pass

    return folder_tokens


def _print_summary(tokens: dict[str, str]):
    print("\n" + "=" * 50)
    print("  扫描完成！已映射的目录：")
    print("=" * 50)
    for key in sorted(tokens.keys()):
        print(f"  {key:20s} → {tokens[key][:24]}...")
    print(f"\n  共 {len(tokens)} 个目录")
    print(f"  配置文件: {CONFIG_FILE}")


if __name__ == "__main__":
    main()
