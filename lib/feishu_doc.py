"""
飞书文档核心模块 — 读/写/修/验/删/移/图/排序
所有文档操作的唯一入口，禁止手写 API 调用。
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config, _compile_prohibited_re
from .feishu_auth import api_request, api_request_with_retry, get_tenant_access_token

logger = logging.getLogger("saber.feishu_doc")


# ── Block 类型常量 ────────────────────────────────────────

BLOCK_TEXT = 2          # 文本
BLOCK_H1 = 3            # 一级标题
BLOCK_H2 = 4            # 二级标题
BLOCK_H3 = 5            # 三级标题
BLOCK_H4 = 6            # 四级标题
BLOCK_H5 = 7            # 五级标题
BLOCK_CODE = 14         # 代码块
BLOCK_QUOTE = 15        # 引用
BLOCK_DIVIDER = 22      # 分割线
BLOCK_BULLET = 12       # 无序列表
BLOCK_ORDERED = 13      # 有序列表


# ── 结果类型 ──────────────────────────────────────────────

@dataclass
class WriteResult:
    """写入结果"""
    success: bool
    doc_token: str = ""
    doc_url: str = ""
    title: str = ""
    verify: "VerifyResult | None" = None
    error: str = ""


@dataclass
class VerifyResult:
    """验证结果"""
    passed: bool
    score: int = 100          # 0-100
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    body_char_count: int = 0  # 纯正文（去代码块）字符数


@dataclass
class FixResult:
    """修复结果"""
    fixed: bool
    issues_fixed: list[str] = field(default_factory=list)
    issues_remaining: list[str] = field(default_factory=list)


# ── Markdown → 飞书 Block 转换器 ──────────────────────────

class ContentParser:
    """
    将类 Markdown 内容解析为飞书 block 数组。

    支持：
    - # ~ ###### 标题
    - **bold** 加粗
    - `code` 行内代码
    - ```lang 代码块（block_type=14）
    - --- 分割线（block_type=22）
    - - / * 无序列表
    - 1. / 2. 有序列表
    - |表格| → 自动转换为子弹列表
    - > 引用
    """

    def parse(self, markdown_text: str) -> list[dict]:
        """主解析入口"""
        blocks: list[dict] = []
        lines = markdown_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # 分割线
            if line.strip() == "---":
                blocks.append(self._make_divider())
                i += 1
                continue

            # 代码块
            if line.strip().startswith("```"):
                code_lines, lang, i = self._parse_code_block(lines, i)
                blocks.append(self._make_code_block(code_lines, lang))
                continue

            # 标题
            heading = self._parse_heading(line)
            if heading:
                blocks.append(heading)
                i += 1
                continue

            # 无序列表
            bullet = self._parse_bullet(line)
            if bullet:
                blocks.append(bullet)
                i += 1
                continue

            # 有序列表
            ordered = self._parse_ordered(line)
            if ordered:
                blocks.append(ordered)
                i += 1
                continue

            # 管道符表格 → 转换为文本块
            if line.strip().startswith("|") and "|" in line.strip()[1:]:
                blocks.append(self._make_text_block(line))
                i += 1
                continue

            # 引用
            if line.strip().startswith(">"):
                blocks.append(self._make_quote_block(line.strip()[1:].strip()))
                i += 1
                continue

            # 空行跳过
            if line.strip() == "":
                i += 1
                continue

            # 正文段落
            text_lines = []
            while i < len(lines) and lines[i].strip() != "" \
                    and not lines[i].strip().startswith("```") \
                    and not lines[i].strip().startswith("|") \
                    and not self._parse_heading(lines[i]) \
                    and not self._parse_bullet(lines[i]) \
                    and not self._parse_ordered(lines[i]) \
                    and lines[i].strip() != "---" \
                    and not lines[i].strip().startswith(">"):
                text_lines.append(lines[i])
                i += 1
            blocks.append(self._make_text_block("\n".join(text_lines)))

        return blocks

    def _parse_code_block(self, lines: list[str], start: int) -> tuple[str, str, int]:
        """解析代码块，返回 (代码内容, 语言, 下一行索引)"""
        lang = lines[start].strip()[3:].strip()
        code_lines = []
        i = start + 1
        while i < len(lines):
            if lines[i].strip() == "```":
                i += 1
                break
            code_lines.append(lines[i])
            i += 1
        return "\n".join(code_lines), lang, i

    def _parse_heading(self, line: str) -> dict | None:
        """解析标题行"""
        line = line.strip()
        if line.startswith("###### "):
            return self._make_heading(line[7:], BLOCK_H5)
        if line.startswith("##### "):
            return self._make_heading(line[6:], BLOCK_H5)
        if line.startswith("#### "):
            return self._make_heading(line[5:], BLOCK_H4)
        if line.startswith("### "):
            return self._make_heading(line[4:], BLOCK_H3)
        if line.startswith("## "):
            return self._make_heading(line[3:], BLOCK_H2)
        if line.startswith("# "):
            return self._make_heading(line[2:], BLOCK_H1)
        return None

    def _parse_bullet(self, line: str) -> dict | None:
        """解析无序列表"""
        stripped = line.strip()
        for prefix in ("- ", "* ", "+ "):
            if stripped.startswith(prefix):
                return self._make_text_block(stripped[len(prefix):], block_type=BLOCK_BULLET)
        return None

    def _parse_ordered(self, line: str) -> dict | None:
        """解析有序列表"""
        match = re.match(r"^(\d+)[.)]\s+(.+)", line.strip())
        if match:
            return self._make_text_block(match.group(2), block_type=BLOCK_ORDERED)
        return None

    # ── Block 构造 ──

    def _make_heading(self, text: str, level: int) -> dict:
        heading_key = {3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4", 7: "heading5", 8: "heading6"}.get(level, "text")
        return {
            "block_type": level,
            heading_key: {
                "elements": self._parse_inline(text),
                "style": {},
            },
        }

    def _make_text_block(self, text: str, block_type: int = BLOCK_TEXT) -> dict:
        content_key = {12: "bullet", 13: "ordered", 2: "text"}.get(block_type, "text")
        return {
            "block_type": block_type,
            content_key: {
                "elements": self._parse_inline(text),
                "style": {},
            },
        }

    def _make_code_block(self, code: str, lang: str) -> dict:
        return {
            "block_type": BLOCK_CODE,
            "code": {
                "elements": [
                    {
                        "text_run": {
                            "content": code,
                            "text_element_style": {"language": self._map_lang(lang)},
                        }
                    }
                ],
                "style": {},
            },
        }

    def _make_divider(self) -> dict:
        return {"block_type": BLOCK_DIVIDER, "divider": {}}

    def _make_quote_block(self, text: str) -> dict:
        return {
            "block_type": BLOCK_QUOTE,
            "quote": {
                "elements": self._parse_inline(text),
            },
        }

    # ── 内联解析 ──

    def _parse_inline(self, text: str) -> list[dict]:
        """
        解析内联格式：
        - **text** → bold
        - `text` → inline_code
        - 其余 → text_run
        """
        elements: list[dict] = []
        pos = 0
        while pos < len(text):
            # bold
            bold_match = re.match(r"\*\*(.+?)\*\*", text[pos:])
            if bold_match:
                content = bold_match.group(1)
                elements.append({
                    "text_run": {
                        "content": content,
                        "text_element_style": {
                            "bold": True,
                        },
                    }
                })
                pos += len(bold_match.group(0))
                continue

            # inline_code
            code_match = re.match(r"`([^`]+)`", text[pos:])
            if code_match:
                content = code_match.group(1)
                elements.append({
                    "text_run": {
                        "content": content,
                        "text_element_style": {
                            "inline_code": True,
                        },
                    }
                })
                pos += len(code_match.group(0))
                continue

            # plain text
            next_special = len(text)
            for ch in ("**", "`"):
                idx = text.find(ch, pos)
                if idx != -1 and idx < next_special:
                    next_special = idx

            plain = text[pos:next_special]
            if plain:
                elements.append({
                    "text_run": {
                        "content": plain,
                        "text_element_style": {},
                    }
                })
            pos = next_special

        return elements

    def _map_lang(self, lang: str) -> int:
        """语言名称 → 飞书语言编码"""
        lang_map = {
            "bash": 2, "shell": 2,
            "python": 4, "py": 4,
            "javascript": 5, "js": 5,
            "typescript": 6, "ts": 6,
            "java": 8,
            "go": 12,
            "c": 14,
            "cpp": 15, "c++": 15,
            "json": 18,
            "yaml": 19, "yml": 19,
            "sql": 22,
            "html": 24,
            "css": 25,
            "http": 28,
            "plaintext": 1, "text": 1, "": 1,
            "powershell": 31, "ps1": 31,
            "dockerfile": 33, "docker": 33,
            "makefile": 34,
            "nginx": 35,
            "xml": 37,
            "rust": 43,
        }
        return lang_map.get(lang.lower(), 1)


# ── 文档操作类 ────────────────────────────────────────────

class FeishuDoc:
    """飞书文档操作核心类"""

    def __init__(self):
        cfg = get_config()
        self.space_id = cfg.space_id
        self.parser = ContentParser()

    # ═══ 写入 ════════════════════════════════════════════

    def write(
        self,
        title: str,
        content: str,
        folder_token: str,
        doc_token: str | None = None,
    ) -> WriteResult:
        """
        创建或更新飞书文档。

        Args:
            title: 文档标题
            content: 类 Markdown 内容
            folder_token: 父目录 token
            doc_token: 若提供则为更新模式，否则创建新文档

        Returns:
            WriteResult（含内置验证结果）
        """
        blocks = self.parser.parse(content)

        try:
            if doc_token:
                # 更新现有文档（分批写入）
                batch_size = 20
                for i in range(0, len(blocks), batch_size):
                    chunk = blocks[i:i + batch_size]
                    api_request(
                        "POST",
                        f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                        body={"children": chunk},
                    )
                doc_url = f"https://bytedance.feishu.cn/docx/{doc_token}"
            else:
                # 创建新文档
                resp = api_request("POST", f"/wiki/v2/spaces/{self.space_id}/nodes", body={
                    "parent_node_token": folder_token,
                    "obj_type": "docx",
                    "node_type": "origin",
                    "title": title,
                })
                node_token = resp["node"]["node_token"]
                doc_token = resp["node"].get("obj_token", node_token)
                doc_url = f"https://bytedance.feishu.cn/docx/{doc_token}"

                # 创建后写入内容（分批写入）
                batch_size = 20
                for i in range(0, len(blocks), batch_size):
                    chunk = blocks[i:i + batch_size]
                    api_request(
                        "POST",
                        f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                        body={"children": chunk},
                    )

            # 内置验证（基于本地 blocks，不走网络）
            verify = self._inline_verify(blocks, content)

            return WriteResult(
                success=True,
                doc_token=doc_token,
                doc_url=doc_url,
                title=title,
                verify=verify,
            )

        except RuntimeError as e:
            logger.error("写入失败: %s", e)
            return WriteResult(success=False, error=str(e))

    # ═══ 读取 ════════════════════════════════════════════

    def read(self, doc_token: str) -> dict[str, Any]:
        """
        读取文档内容和 block 结构。

        Returns:
            {"title": ..., "blocks": [...], "raw_text": "..."}
        """
        # 获取文档信息
        info = api_request("GET", f"/wiki/v2/spaces/{self.space_id}/nodes/{doc_token}")
        title = info.get("node", {}).get("title", "")

        # 获取 block 列表
        blocks_data = api_request("GET", f"/docx/v1/documents/{doc_token}/blocks",
                                  query={"page_size": 500})

        blocks = blocks_data.get("items", [])
        return {
            "title": title,
            "blocks": blocks,
            "raw_text": self._blocks_to_text(blocks),
        }

    def read_raw(self, doc_token: str) -> str:
        """读取文档纯文本"""
        try:
            data = api_request("GET", f"/docx/v1/documents/{doc_token}/raw_content")
            return data.get("content", "")
        except RuntimeError:
            return ""

    def _blocks_to_text(self, blocks: list[dict]) -> str:
        """Block 列表 → 纯文本"""
        texts = []
        for block in blocks:
            bt = block.get("block_type", 0)
            if bt == BLOCK_TEXT:
                texts.append(self._extract_text(block.get("text", {})))
            elif bt in (BLOCK_H1, BLOCK_H2, BLOCK_H3, BLOCK_H4, BLOCK_H5):
                texts.append(self._extract_text(block.get(bt, {})))
            elif bt == BLOCK_CODE:
                code = block.get("code", {})
                for e in code.get("elements", []):
                    texts.append(e.get("text_run", {}).get("content", ""))
            elif bt in (BLOCK_BULLET, BLOCK_ORDERED):
                texts.append(self._extract_text(block.get("text", {})))
        return "\n".join(texts)

    @staticmethod
    def _extract_text(block_data: dict) -> str:
        return "".join(
            e.get("text_run", {}).get("content", "")
            for e in block_data.get("elements", [])
        )

    # ═══ 验证 ════════════════════════════════════════════

    def _inline_verify(self, blocks: list[dict], raw_content: str) -> VerifyResult:
        """
        基于本地 blocks 做基础验证，不走网络。
        用于 write() 内部的即时检查。
        """
        issues: list[str] = []
        warnings: list[str] = []
        score = 100

        # 提取非代码块文本
        non_code_text = self._get_non_code_text(blocks)
        body_chars = len(non_code_text.strip())

        # 1. 正文字数
        if body_chars < 200:
            issues.append(f"正文不足 200 字符（当前 {body_chars}）")
            score -= 30

        # 2. 禁词检测
        cfg = get_config()
        prohibited = cfg.prohibited_words
        if prohibited:
            re_prohibited = _compile_prohibited_re(prohibited)
            found = re_prohibited.findall(non_code_text)
            if found:
                issues.append(f"发现禁词: {', '.join(set(found))}")
                score -= 20

        # 3. ASCII 句号检测（正文中）
        if re.search(r'(?<!\d)\.(?!\d)', non_code_text):
            warnings.append("正文中存在 ASCII 句号，应使用全角 。")

        # 4. 代码块引导语检查
        code_blocks = sum(1 for b in blocks if b.get("block_type") == BLOCK_CODE)
        if code_blocks and body_chars < 300:
            warnings.append("代码块较多但正文较少，检查是否有引导语")

        return VerifyResult(
            passed=len(issues) == 0,
            score=max(0, score),
            issues=issues,
            warnings=warnings,
            body_char_count=body_chars,
        )

    def verify_document(self, doc_token: str) -> VerifyResult:
        """
        验证文档质量。

        检查项：
        1. 纯正文 ≥ 200 字符
        2. 无禁词
        3. 代码块有引导语
        4. 无 ASCII 句号（正文中）
        """
        doc = self.read(doc_token)
        blocks = doc.get("blocks", [])
        raw = doc.get("raw_text", "")
        issues: list[str] = []
        warnings: list[str] = []
        score = 100

        # 获取非代码块的纯文本
        non_code_text = self._get_non_code_text(blocks)

        # 1. 正文字数
        body_chars = len(non_code_text.strip())
        if body_chars < 200:
            issues.append(f"正文不足 200 字符（当前 {body_chars}）")
            score -= 30

        # 2. 禁词检测
        cfg = get_config()
        prohibited = cfg.prohibited_words
        if prohibited:
            re_prohibited = _compile_prohibited_re(prohibited)
            found = re_prohibited.findall(non_code_text)
            if found:
                issues.append(f"发现禁词: {', '.join(set(found))}")
                score -= 20

        # 3. ASCII 句号检测（正文中）
        if re.search(r'(?<!\d)\.(?!\d)', non_code_text):
            warnings.append("正文中存在 ASCII 句号，应使用全角 。")

        # 4. 代码块数量 vs 引导语
        code_blocks = [b for b in blocks if b.get("block_type") == BLOCK_CODE]
        if code_blocks and body_chars < 300:
            warnings.append("代码块较多但正文较少，检查是否有引导语")

        return VerifyResult(
            passed=len(issues) == 0,
            score=score,
            issues=issues,
            warnings=warnings,
            body_char_count=body_chars,
        )

    @staticmethod
    def _get_non_code_text(blocks: list[dict]) -> str:
        """提取非代码块文本"""
        texts = []
        for block in blocks:
            bt = block.get("block_type", 0)
            if bt == BLOCK_CODE:
                continue
            if bt in (BLOCK_TEXT, BLOCK_H1, BLOCK_H2, BLOCK_H3, BLOCK_H4, BLOCK_H5,
                      BLOCK_BULLET, BLOCK_ORDERED, BLOCK_QUOTE):
                block_data = block.get(bt, block.get("text", {}))
                texts.append(FeishuDoc._extract_text(block_data))
        return "\n".join(texts)

    # ═══ 修复 ════════════════════════════════════════════

    def fix_document(self, doc_token: str) -> FixResult:
        """
        自动修复文档问题。

        修复项：
        - 清理禁词 → 替换为合规措辞
        - ASCII 句号 → 全角句号
        """
        doc = self.read(doc_token)
        blocks = doc.get("blocks", [])
        fixed_count = 0
        remaining: list[str] = []
        cfg = get_config()
        pmap = cfg.prohibited_map

        modified = False
        new_blocks = []
        for block in blocks:
            bt = block.get("block_type", 0)
            if bt == BLOCK_CODE:
                new_blocks.append(block)
                continue

            if bt in (BLOCK_TEXT, BLOCK_H1, BLOCK_H2, BLOCK_H3, BLOCK_H4, BLOCK_H5,
                      BLOCK_BULLET, BLOCK_ORDERED, BLOCK_QUOTE):
                block_data = block.get(bt, block.get("text", {}))
                if "elements" not in block_data:
                    new_blocks.append(block)
                    continue

                block_modified = False
                for elem in block_data["elements"]:
                    tr = elem.get("text_run", {})
                    content = tr.get("content", "")

                    # 替换禁词
                    new_content = content
                    for word, replacement in pmap.items():
                        if word in new_content:
                            new_content = new_content.replace(word, replacement)
                            block_modified = True

                    # ASCII 句号 → 全角（非数字上下文）
                    if re.search(r'(?<!\d)\.(?!\d)', new_content):
                        new_content = re.sub(r'(?<!\d)\.(?!\d)', '。', new_content)
                        block_modified = True

                    tr["content"] = new_content

                if block_modified:
                    modified = True
                    fixed_count += 1

            new_blocks.append(block)

        if modified:
            try:
                api_request("PATCH", f"/docx/v1/documents/{doc_token}/blocks/batch_update",
                            body={"blocks": new_blocks})
            except RuntimeError:
                remaining = ["block 更新 API 调用失败"]

        return FixResult(
            fixed=fixed_count > 0,
            issues_fixed=[f"修复了 {fixed_count} 个 block"] if fixed_count > 0 else [],
            issues_remaining=remaining,
        )

    # ═══ 删除 ════════════════════════════════════════════

    def delete_document(self, doc_token: str, confirm: bool = False) -> bool:
        """
        删除文档（危险操作）。

        Args:
            doc_token: 文档 token
            confirm: 必须显式传 True 才执行

        Returns:
            是否成功
        """
        if not confirm:
            logger.warning("删除操作未确认，已跳过")
            return False

        try:
            api_request("DELETE", f"/wiki/v2/spaces/{self.space_id}/nodes/{doc_token}")
            logger.info("文档已删除: %s", doc_token[:16])
            return True
        except RuntimeError as e:
            logger.error("删除失败: %s", e)
            return False

    # ═══ 移动 ════════════════════════════════════════════

    def move(self, doc_token: str, target_parent_token: str) -> bool:
        """
        移动文档到目标目录。

        Args:
            doc_token: 文档 token
            target_parent_token: 目标父目录 token

        Returns:
            是否成功
        """
        try:
            api_request("POST", f"/wiki/v2/spaces/{self.space_id}/nodes/{doc_token}/move",
                        body={"target_parent_token": target_parent_token})
            logger.info("文档已移动: %s → %s", doc_token[:16], target_parent_token[:16])
            return True
        except RuntimeError as e:
            logger.error("移动失败: %s", e)
            return False

    # ═══ 图表渲染 ════════════════════════════════════════

    def render_chart(self, mermaid_text: str, doc_token: str) -> bool:
        """
        将 Mermaid 语法渲染为 PNG 并插入飞书文档。

        流程：Mermaid → PNG（mmdc CLI）→ 裁剪（PIL）→ 上传飞书图片 → 插入文档

        Args:
            mermaid_text: Mermaid 语法文本
            doc_token: 目标文档 token

        Returns:
            是否成功
        """
        # Step 1: 渲染 PNG
        png_path = self._mermaid_to_png(mermaid_text)
        if not png_path:
            return False

        # Step 2: 裁剪白边
        cropped = self._crop_png(png_path)
        final_path = cropped or png_path

        # Step 3: 上传飞书图片并插入文档
        try:
            image_key = self._upload_image(final_path, parent_node=doc_token)
            self._insert_image_block(doc_token, image_key)
            logger.info("图表已插入文档: %s", doc_token[:16])
            return True
        except RuntimeError as e:
            logger.error("图表插入失败: %s", e)
            return False
        finally:
            # 清理临时文件
            for f in (png_path, cropped):
                if f and os.path.exists(f):
                    os.unlink(f)

    def _mermaid_to_png(self, mermaid_text: str) -> str | None:
        """Mermaid 文本 → PNG 文件（通过 mermaid.ink API）"""
        import base64
        import urllib.request

        try:
            # mermaid.ink 使用 base64 编码
            encoded = base64.urlsafe_b64encode(mermaid_text.encode("utf-8")).decode()
            url = f"https://mermaid.ink/img/{encoded}"

            tmp_png = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_png.close()

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SaberSoul/1.0)",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(tmp_png.name, "wb") as f:
                    f.write(resp.read())
            return tmp_png.name
        except Exception as e:
            logger.error("mermaid.ink 渲染失败: %s", e)
            return None

    def _crop_png(self, png_path: str) -> str | None:
        """裁剪 PNG 白边"""
        try:
            from PIL import Image
            img = Image.open(png_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # 获取边界
            bbox = img.getbbox()
            if bbox is None:
                return None

            cropped = img.crop(bbox)
            output = png_path.replace(".png", "_crop.png")
            cropped.save(output, "PNG")
            return output
        except ImportError:
            logger.warning("Pillow 未安装，跳过裁剪")
            return None

    def _upload_image(self, image_path: str, parent_node: str = "") -> str:
        """上传图片到飞书 Drive，返回可用于 docx 的 file_token"""
        import requests
        cfg = get_config()
        token = get_tenant_access_token()

        file_name = Path(image_path).name
        file_size = Path(image_path).stat().st_size

        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{cfg.api_base}/drive/v1/medias/upload_all",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (file_name, f, "image/png")},
                data={
                    "file_name": file_name,
                    "parent_type": "docx_image",
                    "parent_node": parent_node,
                    "size": str(file_size),
                },
                timeout=30,
            )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"图片上传失败: {data}")
        return data["data"]["file_token"]

    def _insert_image_block(self, doc_token: str, image_key: str):
        """向文档插入图片 block"""
        api_request("POST", f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
                    body={"children": [{
                        "block_type": 27,
                        "image": {
                            "file_token": image_key,
                            "width": 800,
                        },
                        }]
                    })

    # ═══ 图片插入（三步法封装）════════════════════════════════

    def insert_image(self, doc_token: str, image_path: str, index: int = 0) -> str:
        """
        向飞书文档插入图片（建块 → 上传 → 填内容）。
        返回图片块的 block_id。
        上传失败不会残留空块（使用 api_request_with_retry）。
        """
        # 1. 上传图片到 Drive
        file_token = self._upload_image(image_path, parent_node=doc_token)

        # 2. 建图片块并填入 file_token
        api_request_with_retry("POST",
            f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
            body={
                "children": [{"block_type": 27, "image": {"file_token": file_token, "width": 800}}],
                "index": index,
            },
            timeout=30,
        )
        logger.info("图片已插入 doc=%s index=%d file_token=%s", doc_token[:12], index, file_token[:12])

        # 3. 清理可能残留的空块
        self.cleanup_empty_images(doc_token)

        return file_token

    # ═══ Excalidraw 渲染 ════════════════════════════════════

    @staticmethod
    def render_excalidraw(input_path: str, output_path: str | None = None, scale: int = 2) -> str:
        """
        将 Excalidraw .excalidraw 文件渲染为 PNG。
        依赖：cairosvg（hermes-agent venv）+ ~/.fonts/msyh.ttc

        Args:
            input_path: .excalidraw 文件路径
            output_path: 输出 PNG 路径，默认替换后缀为 .png
            scale: 缩放倍率（2=高清）

        Returns:
            输出 PNG 路径
        """
        if output_path is None:
            output_path = input_path.replace(".excalidraw", ".png")

        import json, math

        venv_python = "/home/c1ay/.hermes/hermes-agent/venv/bin/python3"
        if not os.path.exists(venv_python):
            # 降级到系统 python3
            venv_python = "python3"

        # 渲染逻辑：将 excalidraw JSON 转为 SVG → cairosvg 转 PNG
        # 使用子进程调用 venv 中的 cairosvg
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        elements = data.get("elements", [])

        # 分离容器绑定文本、其他元素
        texts_c, others, containers = [], [], {}
        for el in elements:
            t = el.get("type")
            if t == "text" and el.get("containerId"):
                texts_c.append(el)
                if el["containerId"] not in containers:
                    containers[el["containerId"]] = None
            else:
                others.append(el)
                if el.get("id"):
                    containers[el["id"]] = el

        # 计算画布边界
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for el in elements:
            if el.get("type") == "text" and el.get("containerId"):
                c = containers.get(el["containerId"])
                if c:
                    min_x = min(min_x, c["x"]); max_x = max(max_x, c["x"] + c["width"])
                    min_y = min(min_y, c["y"]); max_y = max(max_y, c["y"] + c["height"])
                    continue
            ex, ey = el.get("x", 0), el.get("y", 0)
            ew = el.get("width", 100) if el.get("type") != "arrow" else 0
            eh = el.get("height", 100) if el.get("type") != "arrow" else 0
            min_x, max_x = min(min_x, ex), max(max_x, ex + ew)
            min_y, max_y = min(min_y, ey), max(max_y, ey + eh)

        pad = 40
        w = int(max_x - min_x + pad * 2)
        h = int(max_y - min_y + pad * 2)
        ox, oy = min_x - pad, min_y - pad

        def px(x): return f"{x - ox:.0f}"
        def py(y): return f"{y - oy:.0f}"

        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="white"/>',
        ]

        for el in others:
            t, ex, ey = el.get("type"), el.get("x", 0), el.get("y", 0)
            ew, eh = el.get("width", 100), el.get("height", 100)
            bg, sc, sw = el.get("backgroundColor", "transparent"), el.get("strokeColor", "#1e1e1e"), el.get("strokeWidth", 2)
            if t == "rectangle":
                rx = 8 if el.get("roundness", {}).get("type") == 3 else 0
                svg_parts.append(f'<rect x="{px(ex)}" y="{py(ey)}" width="{ew:.0f}" height="{eh:.0f}" rx="{rx}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
            elif t == "ellipse":
                svg_parts.append(f'<ellipse cx="{px(ex+ew/2)}" cy="{py(ey+eh/2)}" rx="{ew/2:.0f}" ry="{eh/2:.0f}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
            elif t == "diamond":
                pts = f"{px(ex+ew/2)},{py(ey)} {px(ex+ew)},{py(ey+eh/2)} {px(ex+ew/2)},{py(ey+eh)} {px(ex)},{py(ey+eh/2)}"
                svg_parts.append(f'<polygon points="{pts}" fill="{bg}" stroke="{sc}" stroke-width="{sw}"/>')
            elif t == "arrow":
                pts = el.get("points", [[0, 0], [100, 0]])
                sx, sy = ex + pts[0][0], ey + pts[0][1]
                ex2, ey2 = ex + pts[-1][0], ey + pts[-1][1]
                dash = "5,5" if el.get("strokeStyle") == "dashed" else "none"
                svg_parts.append(f'<line x1="{px(sx)}" y1="{py(sy)}" x2="{px(ex2)}" y2="{py(ey2)}" stroke="{sc}" stroke-width="{sw}" stroke-dasharray="{dash}"/>')
                if el.get("endArrowhead") == "arrow":
                    ang = math.atan2(ey2 - sy, ex2 - sx)
                    svg_parts.append(f'<polygon points="{px(ex2)},{py(ey2)} {px(ex2-10*math.cos(ang-0.4))},{py(ey2-10*math.sin(ang-0.4))} {px(ex2-10*math.cos(ang+0.4))},{py(ey2-10*math.sin(ang+0.4))}" fill="{sc}"/>')
            elif t == "text" and not el.get("containerId"):
                txt = el.get("text", ""); fs = el.get("fontSize", 16)
                if not txt.strip(): continue
                for li, l in enumerate(txt.replace("\\n", "\n").split("\n")):
                    svg_parts.append(f'<text x="{px(ex+5)}" y="{py(ey+(li+1)*fs)}" font-size="{fs}" fill="{sc}" font-family="Microsoft YaHei, sans-serif">{l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</text>')

        # 容器内文字
        for tel in texts_c:
            txt = tel.get("text", ""); fs = tel.get("fontSize", 16)
            cont = containers.get(tel.get("containerId", ""))
            if not txt.strip() or not cont: continue
            lines = txt.replace("\\n", "\n").split("\n")
            lh = fs + 4
            mw = max(len(l) for l in lines) if lines else 1
            tx = cont["x"] + (cont["width"] - mw * fs * 0.55) / 2
            ty = cont["y"] + (cont["height"] - len(lines) * lh) / 2 + fs
            for li, l in enumerate(lines):
                svg_parts.append(f'<text x="{px(tx)}" y="{py(ty+li*lh)}" font-size="{fs}" fill="{tel.get("strokeColor","#1e1e1e")}" font-family="Microsoft YaHei, sans-serif">{l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</text>')

        svg_parts.append("</svg>")
        svg = "".join(svg_parts)

        # 用 cairosvg 渲染 PNG
        import subprocess
        svg_path = output_path + ".svg.tmp"
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)

        try:
            subprocess.run(
                [venv_python, "-c", f"""
import cairosvg
cairosvg.svg2png(url=r'{svg_path}', write_to=r'{output_path}', scale={scale})
print('OK')
"""],
                capture_output=True, text=True, timeout=30, check=True,
            )
            logger.info("Excalidraw 已渲染: %s", output_path)
        except Exception as e:
            raise RuntimeError(f"Excalidraw 渲染失败: {e}") from e
        finally:
            if os.path.exists(svg_path):
                os.remove(svg_path)

        return output_path

    # ═══ 空图片块清理 ════════════════════════════════════

    def cleanup_empty_images(self, doc_token: str) -> int:
        """
        扫描文档，删除 token 为空的图片块（上传失败残留）。
        返回删除的块数。
        """
        url = f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children?page_size=100"
        try:
            data = api_request("GET", url)
        except RuntimeError:
            return 0
        items = data.get("items", [])
        to_delete = []
        for i, block in enumerate(items):
            if block.get("block_type") == 27:  # image
                img = block.get("image", {}) or {}
                if not img.get("token", ""):
                    to_delete.append(i)
        if not to_delete:
            return 0
        # 从后往前删，避免索引偏移
        deleted = 0
        for idx in reversed(to_delete):
            try:
                url = f"/docx/v1/documents/{doc_token}/blocks/{doc_token}/children/batch_delete"
                api_request("DELETE", url, body={"start_index": idx, "end_index": idx + 1})
                deleted += 1
            except RuntimeError:
                pass
        if deleted:
            logger.info("清理了 %d 个空图片块", deleted)
        return deleted

    # ═══ 节点排序 ════════════════════════════════════════

    def reorder(self, parent_token: str, child_tokens: list[str]) -> bool:
        """
        对兄弟节点重新排序。

        Args:
            parent_token: 父节点 token
            child_tokens: 按期望顺序排列的子节点 token 列表

        Returns:
            是否成功
        """
        try:
            api_request("PATCH", f"/wiki/v2/spaces/{self.space_id}/nodes/reorder",
                        body={
                            "parent_node_token": parent_token,
                            "node_tokens": child_tokens,
                        })
            logger.info("节点已排序: %s 下 %d 个子节点", parent_token[:16], len(child_tokens))
            return True
        except RuntimeError as e:
            logger.error("排序失败: %s", e)
            return False

    # ═══ 文档搜索 ════════════════════════════════════════

    def search(self, keyword: str, search_type: str = "wiki") -> list[dict]:
        """
        搜索文档（用于查重）。

        Args:
            keyword: 搜索关键词（如 CVE 编号）
            search_type: 未使用，保留兼容

        Returns:
            匹配的文档列表
        """
        import requests
        cfg = get_config()
        token = get_tenant_access_token()

        # 遍历根节点根据标题模糊匹配
        try:
            # 先获取根节点
            resp = requests.get(
                f"{cfg.api_base}/wiki/v2/spaces/{cfg.space_id}/nodes",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 100},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                return []
            
            results = []
            for item in data.get("data", {}).get("items", []):
                title = item.get("title", "")
                if keyword.lower() in title.lower():
                    results.append({
                        "title": title,
                        "node_token": item.get("node_token", ""),
                        "id": item.get("node_token", ""),
                    })
            
            # 递归搜索子节点（最多两级）
            self._search_children(cfg.space_id, data.get("data", {}).get("items", []), 
                                  keyword, token, cfg.api_base, results, depth=0)
            
            return results
        except Exception as e:
            logger.warning("搜索失败: %s，跳过查重", e)
            return []

    def _search_children(self, space_id: str, nodes: list, keyword: str, 
                         token: str, api_base: str, results: list, depth: int = 0):
        """递归搜索子节点中的标题匹配"""
        if depth > 2 or not nodes:
            return
        import requests
        for node in nodes:
            nt = node.get("node_token", "")
            if not nt:
                continue
            try:
                resp = requests.get(
                    f"{api_base}/wiki/v2/spaces/{space_id}/nodes",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"parent_node_token": nt, "page_size": 50},
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") != 0:
                    continue
                children = data.get("data", {}).get("items", [])
                for child in children:
                    title = child.get("title", "")
                    if keyword.lower() in title.lower():
                        results.append({
                            "title": title,
                            "node_token": child.get("node_token", ""),
                            "id": child.get("node_token", ""),
                        })
                self._search_children(space_id, children, keyword, token, api_base, results, depth + 1)
            except Exception:
                continue

    # ═══ 内容检查（Pre-Check） ═══════════════════════════

    def pre_check(self, content: str, doc_type: str = "") -> VerifyResult:
        """
        写入前预检：检查内容是否满足基本要求。

        Args:
            content: 待写入的 Markdown 内容
            doc_type: 文档类型（用于模板验证）

        Returns:
            VerifyResult
        """
        issues: list[str] = []
        warnings: list[str] = []

        # 去除代码块后的纯文本
        clean = re.sub(r"```[\s\S]*?```", "", content)
        clean = clean.strip()
        body_chars = len(clean)

        # 基础字数
        if body_chars < 200:
            issues.append(f"正文不足 200 字符（当前 {body_chars}）")

        # 禁词
        cfg = get_config()
        prohibited = cfg.prohibited_words
        if prohibited:
            re_prohibited = _compile_prohibited_re(prohibited)
            found = re_prohibited.findall(clean)
            if found:
                issues.append(f"发现禁词: {', '.join(set(found))}")

        # ASCII 句号
        if re.search(r'(?<!\d)\.(?!\d)', clean):
            warnings.append("正文中存在 ASCII 句号，应使用全角 。")

        # 长破折号
        if "—" in content:
            warnings.append("发现 U+2014 em dash，请替换为 --")

        # CVE 模板 9 段检查
        if doc_type in ("cve", "CVE情报"):
            required_sections = [
                "基本信息", "影响组件", "漏洞原理", "利用条件",
                "测绘", "PoC", "修复建议", "关联漏洞", "参考链接",
            ]
            missing = [s for s in required_sections if s not in content]
            if missing:
                warnings.append(f"CVE 模板缺少段落: {', '.join(missing)}")

        # 命令裸写检测
        for pattern in cfg.command_patterns:
            if re.search(pattern, clean):
                warnings.append(f"疑似命令裸写在正文中（匹配: {pattern}），应放入代码块")

        score = max(0, 100 - len(issues) * 15 - len(warnings) * 5)
        return VerifyResult(
            passed=len(issues) == 0,
            score=score,
            issues=issues,
            warnings=warnings,
            body_char_count=body_chars,
        )


# ── 单例 ─────────────────────────────────────────────────

_doc_instance: FeishuDoc | None = None


def get_doc() -> FeishuDoc:
    global _doc_instance
    if _doc_instance is None:
        _doc_instance = FeishuDoc()
    return _doc_instance


# ── 便捷函数 ─────────────────────────────────────────────

def write_doc(title: str, content: str, folder_token: str, doc_token: str | None = None) -> WriteResult:
    """便捷写入函数"""
    return get_doc().write(title, content, folder_token, doc_token)


def read_doc(doc_token: str) -> dict:
    """便捷读取函数"""
    return get_doc().read(doc_token)


def verify_doc(doc_token: str) -> VerifyResult:
    """便捷验证函数"""
    return get_doc().verify_document(doc_token)


def fix_doc(doc_token: str) -> FixResult:
    """便捷修复函数"""
    return get_doc().fix_document(doc_token)
