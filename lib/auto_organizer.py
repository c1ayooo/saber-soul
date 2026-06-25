"""
自动整理模块 — 99-待分类清理 + 垃圾检测 + 错位文档归位

危险操作（删除）必须通过 confirm_callback 获取用户确认。

用法：
    organizer = AutoOrganizer()
    garbage, misplaced = organizer.scan()

    # 垃圾文档列表（需用户确认后删除）
    # 错位文档列表（可自动重新分类+移动）
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from .config import get_config
from .feishu_auth import api_request

logger = logging.getLogger("saber.organizer")


@dataclass
class GarbageDoc:
    """疑似垃圾文档"""
    node_token: str
    title: str
    reason: str
    parent_token: str = ""


@dataclass
class MisplacedDoc:
    """错位文档"""
    node_token: str
    title: str
    current_folder: str
    suggested_folder: str
    doc_type: str = ""


class AutoOrganizer:
    """
    自动整理器。

    安全规则：
    - 垃圾检测结果仅返回列表，不自动删除
    - 删除操作必须通过 confirm_callback 回调确认
    - 移动操作通过移动 API（非删除+重建）
    """

    def __init__(self):
        cfg = get_config()
        self.space_id = cfg.space_id
        self.garbage_rules = cfg.garbage_rules
        self._trash_token = cfg.get_folder_token("99")

    # ── 扫描 ──────────────────────────────────────────────

    def scan(self) -> tuple[list[GarbageDoc], list[MisplacedDoc]]:
        """
        扫描知识库，返回 (垃圾列表, 错位列表)。

        Returns:
            garbage: 疑似垃圾文档列表
            misplaced: 疑似错位文档列表
        """
        garbage: list[GarbageDoc] = []
        misplaced: list[MisplacedDoc] = []

        # 扫描 99-待分类
        if self._trash_token:
            self._scan_folder(self._trash_token, "99-待分类", garbage, misplaced)

        # 可扩展：扫描其他目录

        return garbage, misplaced

    def _scan_folder(
        self,
        parent_token: str,
        folder_name: str,
        garbage: list[GarbageDoc],
        misplaced: list[MisplacedDoc],
    ):
        """递归扫描目录"""
        try:
            nodes = api_request("GET", f"/wiki/v2/spaces/{self.space_id}/nodes",
                                query={"parent_node_token": parent_token, "page_size": 50})
        except RuntimeError:
            return

        for item in nodes.get("items", []):
            title = item.get("title", "")
            node_token = item["node_token"]
            obj_type = item.get("obj_type", "")

            if obj_type == "docx":
                # 获取文档内容进行垃圾检测
                content = self._get_doc_content(node_token)
                rule = self._check_garbage(title, content or "")
                if rule:
                    garbage.append(GarbageDoc(
                        node_token=node_token,
                        title=title,
                        reason=rule["reason"],
                        parent_token=parent_token,
                    ))

                # 99-待分类中的文档：尝试自动分类
                if folder_name == "99-待分类":
                    self._check_misplaced(node_token, title, content or "", misplaced)

    def _get_doc_content(self, doc_token: str) -> str | None:
        """获取文档纯文本内容"""
        try:
            data = api_request("GET", f"/docx/v1/documents/{doc_token}/raw_content")
            return data.get("content", "")
        except RuntimeError:
            return None

    def _check_garbage(self, title: str, content: str) -> dict | None:
        """检测是否为垃圾文档"""
        for rule in self.garbage_rules:
            # 规则：内容过少
            if "min_chars" in rule:
                if len(content) < rule["min_chars"]:
                    return rule

            # 规则：标题模式
            if "title_patterns" in rule:
                for pattern in rule["title_patterns"]:
                    if re.search(pattern, title, re.IGNORECASE):
                        return rule

            # 规则：关键词
            if "keywords" in rule:
                hits = 0
                for kw in rule["keywords"]:
                    if kw.lower() in title.lower() or kw.lower() in content.lower():
                        hits += 1
                if hits >= rule.get("min_hits", 1):
                    return rule

        return None

    def _check_misplaced(
        self, node_token: str, title: str, content: str,
        misplaced: list[MisplacedDoc],
    ):
        """检查 99-待分类中文档是否能归类到正确目录"""
        from .auto_classifier import auto_route
        result = auto_route(title, content)
        if result.folder_key != "99":
            misplaced.append(MisplacedDoc(
                node_token=node_token,
                title=title,
                current_folder="99-待分类",
                suggested_folder=result.folder_key,
                doc_type=result.doc_type,
            ))

    # ── 操作 ──────────────────────────────────────────────

    def delete_document(self, node_token: str, confirm_callback: Callable[[GarbageDoc], bool]) -> bool:
        """
        删除文档（危险操作，需二次确认）。

        Args:
            node_token: 文档 node_token
            confirm_callback: 确认回调，返回 True 执行删除

        Returns:
            是否成功删除
        """
        # 先读取文档信息用于确认
        try:
            doc_info = api_request("GET", f"/wiki/v2/spaces/{self.space_id}/nodes/{node_token}")
        except RuntimeError:
            doc_info = {}

        doc = GarbageDoc(
            node_token=node_token,
            title=doc_info.get("node", {}).get("title", "未知"),
            reason="手动删除",
        )

        if not confirm_callback(doc):
            logger.info("用户取消删除: %s", doc.title)
            return False

        # 执行删除（移入回收站）
        try:
            api_request("POST", f"/wiki/v2/spaces/{self.space_id}/nodes/{node_token}/move",
                        body={"target_parent_token": self._trash_token or ""})
            logger.info("文档已移至回收站: %s", doc.title)
            return True
        except RuntimeError as e:
            logger.error("删除失败: %s", e)
            return False

    def move_document(self, node_token: str, target_parent_token: str) -> bool:
        """
        移动文档到目标目录。

        Args:
            node_token: 文档 token
            target_parent_token: 目标目录 token

        Returns:
            是否成功
        """
        try:
            api_request("POST", f"/wiki/v2/spaces/{self.space_id}/nodes/{node_token}/move",
                        body={"target_parent_token": target_parent_token})
            logger.info("文档已移动: %s → %s", node_token[:16], target_parent_token[:16])
            return True
        except RuntimeError as e:
            logger.error("移动失败: %s", e)
            return False

    def cleanup_99(self) -> list[MisplacedDoc]:
        """
        清理 99-待分类：检测并列出可自动归位的文档。
        不自动移动，仅返回列表供用户审核。
        """
        _, misplaced = self.scan()
        return misplaced
