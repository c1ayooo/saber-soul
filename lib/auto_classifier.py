"""
自动分类模块 — 关键词匹配优先（0 token），LLM fallback 兜底

分类逻辑：
  1. 关键词匹配 → 返回文档类型、目标文件夹（folder key）
  2. 不命中 → LLM 回调分类（仅此时消耗 token）
  3. CVE/漏洞情报 → 进 2.4，自动解析厂商/产品 → 建文件夹 → 返回产品层 token
"""

import json
import logging
import os
import re
from typing import Callable
from dataclasses import dataclass, field

from .config import get_config
from .feishu_auth import api_request

logger = logging.getLogger("saber.classifier")


@dataclass
class ClassifyResult:
    """分类结果"""
    folder_key: str          # 目录编号，如 "2.4"
    doc_type: str            # 文档类型，如 "cve" / "作战记录" / "JS逆向分析"
    vendor: str = ""         # 厂商名（仅 2.4）
    product: str = ""        # 产品名（仅 2.4）
    subdir_key: str = ""     # 2.4 子目录编号，如 "2.4.1"
    subdir_name: str = ""    # 2.4 子目录名，如 "中间件组件漏洞"


class AutoClassifier:
    """
    自动分类器。

    用法：
        cls = AutoClassifier()
        result = cls.classify(title, content)

    关键词匹配（0 token）覆盖绝大多数场景。
    仅当所有规则都不命中时才通过 llm_callback 走 LLM fallback。
    """

    # 非 2.4 的大类路由（内核/网络设备等不进 2.4，直接跳到对应目录）
    NON_24_PATTERNS: dict[str, str] = {}  # 从 config 延迟加载

    def __init__(self):
        cfg = get_config()
        self.rules = cfg.classify_rules
        self.vendor_map = cfg.vendor_product_map
        self.alias_map = cfg.alias_map
        self.non_24 = cfg.non_24_routes

        # 2.4 子目录到编号映射
        self._subdir_index: dict[str, str] = {
            "中间件组件漏洞": "2.4.1",
            "Web应用系统漏洞": "2.4.2",
            "安全厂商设备漏洞": "2.4.3",
            "系统&云平台漏洞": "2.4.4",
            "通用CVE/CNVD情报汇总": "2.4.5",
        }

        # 会话级缓存：已查/已建的 folder_token
        self._token_cache: dict[str, str] = {}
        # 2.4 子目录 token 表：从 config 或运行时获取
        self._subdir_tokens: dict[str, str] = {}

    # ── 主入口 ────────────────────────────────────────────

    def classify(
        self,
        title: str,
        content: str,
        llm_callback: Callable[[str], str] | None = None,
    ) -> ClassifyResult:
        """
        对文档分类。

        Args:
            title: 文档标题
            content: 文档正文
            llm_callback: LLM 回调，仅在关键词不命中时调用。
                          接收提示词字符串，返回 JSON {"folder_key":"...","doc_type":"..."}
        """
        full_text = f"{title}\n{content}"

        # Step 1: 关键词匹配（0 token）
        result = self._keyword_match(full_text)
        if result is not None:
            logger.info("关键词匹配成功 → folder=%s type=%s", result.folder_key, result.doc_type)
            return result

        # Step 2: LLM fallback（仅此时消耗 token）
        if llm_callback is None:
            logger.warning("关键词未命中且无 LLM 回调，返回 99-待分类")
            return ClassifyResult(folder_key="99", doc_type="待分类")

        logger.info("关键词未命中，调用 LLM fallback ...")
        prompt = self._build_llm_prompt(title, content)
        llm_response = llm_callback(prompt)
        return self._parse_llm_response(llm_response)

    def _keyword_match(self, text: str) -> ClassifyResult | None:
        """关键词匹配，按权重排序，匹配最高分规则"""
        best = None
        best_weight = -1

        for rule in self.rules:
            if not self._match_rule(rule, text):
                continue

            weight = rule.get("weight", 1)
            if weight > best_weight:
                folder_key = rule["folder"]
                doc_type = rule.get("type", "")
                best_weight = weight

                # 检查文档类型是否是 CVE/漏洞（需要进一步路由）
                if doc_type in ("cve", "CVE情报"):
                    # 检查是否应该进 2.4
                    route = self._resolve_non_24(text)
                    if route:
                        folder_key = route

                best = ClassifyResult(folder_key=folder_key, doc_type=doc_type)

        return best

    def _match_rule(self, rule: dict, text: str) -> bool:
        """单条规则匹配"""
        keywords = rule.get("keywords", [])
        negatives = rule.get("negative_keywords", [])

        # 负面影响词先排除
        for nk in negatives:
            if nk.lower() in text.lower():
                return False

        # 关键词命中计数
        hits = 0
        for kw in keywords:
            if kw.lower() in text.lower():
                hits += 1
                if hits >= 1:
                    return True

        return False

    def _resolve_non_24(self, text: str) -> str | None:
        """检查是否属于非 2.4 类别（内核/网络设备等）"""
        if not self.non_24:
            return None
        t = text.lower()
        for keyword, folder in self.non_24.items():
            if keyword.lower() in t:
                return folder
        return None

    # ── 2.4 厂商/产品分层 ─────────────────────────────────

    def resolve_folder(
        self,
        cve_id: str = "",
        product_name: str = "",
        component: str = "",
    ) -> tuple[str, str]:
        """
        解析 CVE 文档应放置的 2.4 子目录 + 厂商/产品层，
        必要时自动创建文件夹，返回产品层 folder_token。

        Args:
            cve_id: CVE 编号（如 CVE-2026-20253）
            product_name: 受影响产品全名
            component: 受影响组件的额外描述

        Returns:
            (folder_token, full_path)  如 ("Bw3n...", "2.4.1/Apache/Tomcat")
        """
        cfg = get_config()
        space_id = cfg.space_id
        if not space_id:
            raise RuntimeError("SPACE_ID 未配置，无法创建文件夹")

        # Step A: 确定子目录
        subdir_name = self._detect_subdir(product_name, component)
        subdir_index = self._subdir_index.get(subdir_name, "2.4.5")

        # Step B: 解析厂商/产品（从 alias_map → vendor_map）
        vendor, product = self._resolve_vendor_product(product_name)
        if not vendor:
            # 无法确定厂商，直接放入子目录
            parent_token = self._get_subdir_token(subdir_name, space_id)
            return parent_token, f"{subdir_index}/{subdir_name}"

        # Step C: 获取或创建厂商文件夹
        subdir_token = self._get_subdir_token(subdir_name, space_id)
        vendor_token = self._ensure_folder(subdir_token, vendor, space_id)

        # Step D: 获取或创建产品文件夹
        if product_name:
            product_token = self._ensure_folder(vendor_token, product_name, space_id)
        else:
            product_token = vendor_token

        full_path = f"{subdir_index}/{subdir_name}/{vendor}/{product_name}" if product_name else f"{subdir_index}/{subdir_name}/{vendor}"
        return product_token, full_path

    def _detect_subdir(self, product_name: str, component: str = "") -> str:
        """
        检测 2.4 下的子目录。
        通过遍历 vendor_map 查找产品归属的子目录。
        """
        search = f"{product_name} {component}".lower()

        for subdir, vendors in self.vendor_map.items():
            for vendor, products in vendors.items():
                # 检查厂商名
                if vendor.lower() in search:
                    return subdir
                # 检查产品名
                for prod in products:
                    if prod.lower() in search:
                        return subdir

        # alias map 回退
        for alias, (vendor, product) in self.alias_map.items():
            if alias.lower() in search:
                for subdir, vendors in self.vendor_map.items():
                    for v, products in vendors.items():
                        if (vendor.lower() in search or v.lower() in search or
                                product.lower() in search):
                            return subdir
                break

        return "通用CVE/CNVD情报汇总"

    def _resolve_vendor_product(self, product_name: str) -> tuple[str, str]:
        """
        从产品名解析厂商和产品。
        Returns: (vendor, product) 或 ("", "")
        """
        if not product_name:
            return "", ""

        name_lower = product_name.lower()

        # 先查 alias_map
        for alias, (vendor, product) in self.alias_map.items():
            if alias.lower() in name_lower:
                return vendor, product

        # 再查 vendor_map（产品名中包含厂商名的情况）
        for subdir, vendors in self.vendor_map.items():
            for vendor, products in vendors.items():
                if vendor.lower() in name_lower:
                    for prod in products:
                        if prod.lower() in name_lower:
                            return vendor, prod
                    return vendor, product_name

        return "", ""

    def _get_subdir_token(self, subdir_name: str, space_id: str) -> str:
        """获取 2.4 子目录的 node_token"""
        cache_key = f"2.4_{subdir_name}"
        if cache_key in self._subdir_tokens:
            return self._subdir_tokens[cache_key]

        cfg = get_config()
        token = cfg.get_folder_token(cache_key)
        if token:
            self._subdir_tokens[cache_key] = token
            return token

        # 从 2.4 父目录枚举子节点
        parent_24 = cfg.get_folder_token("2.4")
        if not parent_24:
            raise RuntimeError("2.4 父目录 token 未配置，请先运行 init_config.py")

        children = api_request("GET", f"/wiki/v2/spaces/{space_id}/nodes",
                               query={"parent_node_token": parent_24, "page_size": 50})
        for item in children.get("items", []):
            if item.get("title") == subdir_name:
                token = item["node_token"]
                self._subdir_tokens[cache_key] = token
                cfg.set_folder_token(cache_key, token)
                return token

        raise RuntimeError(f"未找到 2.4 子目录: {subdir_name}")

    def _ensure_folder(self, parent_token: str, title: str, space_id: str) -> str:
        """
        确保文件夹存在：先 GET 查，不存在则 POST 创建（docx 节点当文件夹）。
        返回 node_token。
        """
        cache_key = f"{parent_token}/{title}"
        if cache_key in self._token_cache:
            return self._token_cache[cache_key]

        # GET 检查是否存在
        children = api_request("GET", f"/wiki/v2/spaces/{space_id}/nodes",
                               query={"parent_node_token": parent_token, "page_size": 100})
        for item in children.get("items", []):
            if item.get("title") == title:
                token = item["node_token"]
                self._token_cache[cache_key] = token
                logger.info("文件夹已存在: %s → %s", title, token[:16])
                return token

        # POST 创建（docx 节点作为文件夹容器）
        resp = api_request("POST", f"/wiki/v2/spaces/{space_id}/nodes", body={
            "parent_node_token": parent_token,
            "obj_type": "docx",
            "node_type": "origin",
            "title": title,
        })
        token = resp["node"]["node_token"]
        self._token_cache[cache_key] = token
        logger.info("文件夹已创建: %s → %s", title, token[:16])
        return token

    # ── LLM Fallback ──────────────────────────────────────

    def _build_llm_prompt(self, title: str, content: str) -> str:
        """构建 LLM 分类提示词（简洁，低 token 消耗）"""
        return f"""对以下飞书文档进行分类，返回 JSON：
文档标题: {title}
文档正文前500字: {content[:500]}

目录结构:
1.1 Web漏洞实战笔记  1.2 内网渗透技巧  1.3 渗透工具使用手册
1.4 漏洞挖掘&代码审计  1.5 思路整理
2.1 安全运营  2.2 应急响应  2.3 安全设备运维
2.4 威胁情报沉淀（CVE/漏洞情报）  2.5 威胁检测与狩猎
3.1 等保核心知识点  3.2 合规自查清单  3.3 整改方案与台账
4.1 Python安全脚本  4.2 Go安全工具  4.3 自动化检测  4.4 工具封装
5 安全研究  99 待分类

返回: {{"folder_key":"目录编号","doc_type":"文档类型"}}
文档类型: 作战记录/CVE情报/JS逆向分析/应急响应/工具文档/安全运营/思路整理/等保/合规自查/整改台账/代码审计/威胁检测/安全研究/设备运维/待分类"""

    def _parse_llm_response(self, response: str) -> ClassifyResult:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试提取 JSON
            match = re.search(r'\{[^}]+\}', response)
            if match:
                data = json.loads(match.group())
                return ClassifyResult(
                    folder_key=data.get("folder_key", "99"),
                    doc_type=data.get("doc_type", "待分类"),
                )
        except json.JSONDecodeError:
            pass
        logger.warning("LLM 返回解析失败，fallback 到 99-待分类")
        return ClassifyResult(folder_key="99", doc_type="待分类")


# ── 便捷函数 ──────────────────────────────────────────────

_classifier_instance: AutoClassifier | None = None


def get_classifier() -> AutoClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = AutoClassifier()
    return _classifier_instance


def auto_route(
    title: str,
    content: str,
    llm_callback: Callable[[str], str] | None = None,
) -> ClassifyResult:
    """便捷函数：自动路由分类"""
    return get_classifier().classify(title, content, llm_callback)
