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
from .feishu_auth import api_request, get_tenant_access_token

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
        return {
            "block_type": level,
            level: {
                "elements": self._parse_inline(text),
                "style": {},
            },
        }

    def _make_text_block(self, text: str, block_type: int = BLOCK_TEXT) -> dict:
        return {
            "block_type": block_type,
            "text": {
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
                # 更新现有文档
                api_request("PATCH", f"/docx/v1/documents/{doc_token}/blocks/batch_update",
                            body={"blocks": blocks})
                doc_url = f"https://bytedance.feishu.cn/docx/{doc_token}"
            else:
                # 创建新文档
                resp = api_request("POST", f"/wiki/v2/spaces/{self.space_id}/nodes", body={
                    "parent_node_token": folder_token,
                    "obj_type": "docx",
                    "node_type": "origin",
                    "title": title,
                })
                doc_token = resp["node"]["node_token"]
                doc_url = f"https://bytedance.feishu.cn/docx/{doc_token}"

                # 创建后写入内容
                api_request("PATCH", f"/docx/v1/documents/{doc_token}/blocks/batch_update",
                            body={"blocks": blocks})

            # 内置验证
            verify = self.verify_document(doc_token)

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
            image_key = self._upload_image(final_path)
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
        """Mermaid 文本 → PNG 文件"""
        tmp_mmd = tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False)
        tmp_png = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_mmd.write(mermaid_text)
        tmp_mmd.close()
        tmp_png.close()

        try:
            result = subprocess.run(
                ["mmdc", "-i", tmp_mmd.name, "-o", tmp_png.name, "-b", "white"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error("mmdc 渲染失败: %s", result.stderr)
                return None
            return tmp_png.name
        except FileNotFoundError:
            logger.error("mmdc 命令未安装，请运行: npm install -g @mermaid-js/mermaid-cli")
            return None
        except subprocess.TimeoutExpired:
            logger.error("mmdc 渲染超时")
            return None
        finally:
            os.unlink(tmp_mmd.name)

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

    def _upload_image(self, image_path: str) -> str:
        """上传图片到飞书，返回 image_key"""
        import requests
        cfg = get_config()
        token = get_tenant_access_token()

        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{cfg.api_base}/im/v1/images",
                headers={"Authorization": f"Bearer {token}"},
                files={"image": f},
                data={"image_type": "message"},
                timeout=30,
            )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"图片上传失败: {data}")
        return data["data"]["image_key"]

    def _insert_image_block(self, doc_token: str, image_key: str):
        """向文档插入图片 block"""
        api_request("PATCH", f"/docx/v1/documents/{doc_token}/blocks/batch_update",
                    body={
                        "blocks": [{
                            "block_type": 27,
                            "image": {
                                "token": image_key,
                                "width": 800,
                            },
                        }]
                    })

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
            search_type: 搜索范围（wiki / space）

        Returns:
            匹配的文档列表
        """
        from urllib.parse import quote
        import requests
        cfg = get_config()
        token = get_tenant_access_token()

        # 飞书搜索 API
        resp = requests.get(
            f"{cfg.api_base}/search/v2/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"query": keyword, "search_type": search_type, "page_size": 10},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return []
        return data.get("data", {}).get("items", [])

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
