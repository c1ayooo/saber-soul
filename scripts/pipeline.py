#!/usr/bin/env python3
"""
飞书知识库编排器 — 唯一写入入口

所有写文档请求必须通过本脚本执行。禁止直接调用 feishu_doc 模块。

调度流程：
  1. Pre-Check   → 字数/禁词/格式检查
  2. Dedup       → 搜索已有文档，避免重复
  3. Route       → 自动分类（关键词优先 0 token，不命中 LLM fallback）
  4. Auto-Classify → 【2.4 专用】自动建文件夹 → 返回产品层 token
  5. Write       → 写入飞书文档
  6. Verify      → 内置验证
  7. Fix Loop    → 失败时自动修复（最多 3 次）
  8. Deliver     → 输出飞书链接

CVE 文档 POC 检查：
  如果文档类型是 CVE 且未包含 PoC 段（或 PoC 段为空），则暂停并询问用户是否继续。

用法：
  python3 pipeline.py write \
    --title "文档标题" \
    --content-file /path/to/content.md \
    [--cve-id "CVE-2026-20253"] \
    [--product "Splunk Enterprise"] \
    [--component "PostgreSQL Sidecar"] \
    [--skip-poc-check] \
    [--llm-fallback-cmd "python3 path/to/llm_classify.py"]

  python3 pipeline.py organize    # 垃圾扫描+清理
  python3 pipeline.py cleanup-99  # 清理 99-待分类
  python3 pipeline.py delete --doc-token xxx --confirm  # 删除文档
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

# 确保 saber_soul 在 Python path
HERE = Path(__file__).resolve().parent.parent  # saber_soul/
sys.path.insert(0, str(HERE))

from lib.config import get_config
from lib.auto_classifier import ClassifyResult, AutoClassifier, auto_route
from lib.auto_organizer import AutoOrganizer, GarbageDoc, MisplacedDoc
from lib.feishu_doc import (
    FeishuDoc, WriteResult, VerifyResult, FixResult,
    write_doc, read_doc, verify_doc, fix_doc,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("saber.pipeline")


# ── 内部信号 ──────────────────────────────────────────────

class NeedDecision(Exception):
    """需要用户决策的信号"""
    def __init__(self, reason: str, context: dict):
        self.reason = reason
        self.context = context


# ═══════════════════════════════════════════════════════════
#  主编排流程
# ═══════════════════════════════════════════════════════════

def pipeline_write(
    title: str,
    content: str,
    *,
    cve_id: str = "",
    product: str = "",
    component: str = "",
    skip_poc_check: bool = False,
    skip_dedup: bool = False,
    llm_fallback_cmd: str | None = None,
    user_decision: str | None = None,  # "proceed" / "abort"
) -> dict:
    """
    写入编排主流程。

    Args:
        title: 文档标题
        content: Markdown 文档内容
        cve_id: CVE 编号（可选，用于查重和分类）
        product: 受影响产品
        component: 受影响组件
        skip_poc_check: 跳过 POC 检查
        skip_dedup: 跳过查重（默认 False，命中直接返回已有文档链接）
        llm_fallback_cmd: LLM 分类脚本命令（关键词不命中时调用）
        user_decision: 用户对 POC 缺失的决策（"proceed"/"abort"）

    Returns:
        {
            "status": "ok" / "need_decision" / "error",
            "doc_url": "...",
            "doc_token": "...",
            "verify": {...},
            "decision_reason": "...",  # 仅 need_decision
        }
    """
    doc = FeishuDoc()
    cfg = get_config()

    # ── Step 0: 凭证检查 ──
    if not cfg.app_id or not cfg.app_secret or not cfg.space_id:
        return {"status": "error", "error": "FEISHU_APP_ID / FEISHU_APP_SECRET / SPACE_ID 未配置"}

    # ── Step 0.5: POC 检查（CVE 文档） ──
    poc_decision = _check_poc(title, content, skip_poc_check, user_decision)
    if poc_decision:
        return poc_decision

    # ── Step 1: Pre-Check ──
    logger.info("[1/6] Pre-Check")
    pre = doc.pre_check(content)
    if pre.issues:
        logger.warning("Pre-Check 发现问题: %s", pre.issues)
        # 非阻断性问题继续，阻断性问题终止
        blocking = [i for i in pre.issues if "不足" in i]
        if blocking:
            return {"status": "error", "error": f"Pre-Check 失败: {blocking}", "verify": _vr(pre)}

    # ── Step 2: Dedup（查重，命中直接返回链接） ──
    existing_token = None
    if not skip_dedup:
        logger.info("[[2/6] Dedup]")
        search_key = cve_id or title
        existing = doc.search(search_key)
        if existing:
            for item in existing:
                match_title = item.get("title", "")
                if match_title == title or (cve_id and cve_id in match_title):
                    node_token = item.get("id") or item.get("node_token", "") or item.get("url", "")
                    # 提取纯 token 部分
                    if "/" in node_token:
                        node_token = node_token.rsplit("/", 1)[-1]
                    doc_url = f"https://bytedance.feishu.cn/docx/{node_token}"
                    logger.info("文档已存在: %s → %s", match_title, doc_url)
                    return {
                        "status": "already_exists",
                        "doc_url": doc_url,
                        "doc_token": node_token,
                        "title": match_title,
                    }

    # ── Step 3: Route（分类） ──
    logger.info("[[3/6] Route]")
    llm_cb = None
    if llm_fallback_cmd:
        def _llm_callback(prompt: str) -> str:
            import subprocess
            try:
                result = subprocess.run(
                    llm_fallback_cmd.split() + [prompt],
                    capture_output=True, text=True, timeout=30,
                )
                return result.stdout.strip()
            except Exception:
                return '{"folder_key":"99","doc_type":"待分类"}'
        llm_cb = _llm_callback

    route_result = auto_route(title, content, llm_cb)
    logger.info("分类结果: folder=%s type=%s", route_result.folder_key, route_result.doc_type)

    # 99 检查
    if route_result.folder_key == "99":
        return {
            "status": "need_decision",
            "decision_reason": f"无法自动分类文档「{title}」。请手动指定目录或建议新建文件夹。",
            "route": {"folder_key": "99", "doc_type": route_result.doc_type},
        }

    # ── Step 4: Auto-Classify（2.4 专用） ──
    logger.info("[[4/6] Auto-Classify]")
    folder_token = ""
    folder_path = route_result.folder_key

    if route_result.folder_key == "2.4" and (product or cve_id):
        cls = AutoClassifier()
        product_name = product or title
        folder_token, folder_path = cls.resolve_folder(
            cve_id=cve_id,
            product_name=product_name,
            component=component,
        )
        logger.info("2.4 分层结果: %s", folder_path)
    else:
        # 非 2.4：直接查 config 中的 token
        folder_token = cfg.get_folder_token(route_result.folder_key)
        if not folder_token:
            return {
                "status": "error",
                "error": f"目录 {route_result.folder_key} 的 token 未配置，请先运行 init_config.py",
            }

    # ── Step 5: Write ──
    logger.info("[[5/6] Write]")
    result = doc.write(
        title=title,
        content=content,
        folder_token=folder_token,
        doc_token=existing_token,
    )
    if not result.success:
        return {"status": "error", "error": result.error}

    # ── Step 6: Verify（使用 write 内置的本地验证结果，不走网络） ──
    verify = result.verify
    if verify and verify.passed:
        return _ok(result, verify, folder_path)

    # ── Step 7: Fix Loop ──
    logger.info("[[6/6] Verify]")
    for attempt in range(1, 4):
        logger.info("修复尝试 %d/3 ...", attempt)
        fix_r = doc.fix_document(result.doc_token)
        if not fix_r.fixed:
            break

        verify = doc.verify_document(result.doc_token)
        if verify.passed:
            logger.info("修复成功 (第 %d 次)", attempt)
            return _ok(result, verify, folder_path)

    # 3 次后仍失败
    return {
        "status": "partial",
        "doc_url": result.doc_url,
        "doc_token": result.doc_token,
        "title": title,
        "folder": folder_path,
        "verify": _vr(verify),
        "warning": "文档已写入但验证未通过，请人工复核",
    }


def _check_poc(
    title: str, content: str,
    skip: bool, user_decision: str | None,
) -> dict | None:
    """
    CVE 文档 POC 检查。
    如果文档是 CVE 类型且 PoC 段为空/缺少，返回 need_decision。
    """
    if skip:
        return None

    # 检测是否为 CVE 文档
    is_cve = any(kw in title or kw in content[:200]
                 for kw in ("CVE-", "CVSS", "漏洞编号", "CNVD-", "CNNVD-"))

    if not is_cve:
        return None

    # 检查 PoC 段是否存在且非空
    poc_patterns = [
        r"#{1,4}\s*(?:六|陆|6)[、.）\s]*PoC",
        r"#{1,4}\s*PoC",
        r"#{1,4}\s*复现",
        r"#{1,4}\s*漏洞验证",
    ]
    has_poc_section = any(re.search(p, content) for p in poc_patterns)

    if not has_poc_section:
        if user_decision is None:
            return {
                "status": "need_decision",
                "decision_reason": (
                    f"文档「{title}」为 CVE 漏洞情报，但未包含 PoC 段。"
                    "是否继续写入？（请回复 proceed 或 abort）"
                ),
                "decision_required": "poc_missing",
            }
        elif user_decision == "abort":
            return {"status": "aborted", "reason": "用户要求中止：缺少 PoC"}
        # "proceed" → 继续

    return None


def _ok(result: WriteResult, verify: VerifyResult, folder_path: str) -> dict:
    return {
        "status": "ok",
        "doc_url": result.doc_url,
        "doc_token": result.doc_token,
        "title": result.title,
        "folder": folder_path,
        "verify": _vr(verify),
    }


def _vr(v: VerifyResult) -> dict:
    return {
        "passed": v.passed,
        "score": v.score,
        "issues": v.issues,
        "warnings": v.warnings,
        "body_chars": v.body_char_count,
    }


# ═══════════════════════════════════════════════════════════
#  辅助命令
# ═══════════════════════════════════════════════════════════

def cmd_organize() -> dict:
    """扫描知识库，返回垃圾和错位文档列表"""
    org = AutoOrganizer()
    garbage, misplaced = org.scan()

    return {
        "status": "ok",
        "garbage": [
            {"title": g.title, "reason": g.reason, "node_token": g.node_token}
            for g in garbage
        ],
        "misplaced": [
            {
                "title": m.title,
                "current": m.current_folder,
                "suggested": m.suggested_folder,
                "doc_type": m.doc_type,
                "node_token": m.node_token,
            }
            for m in misplaced
        ],
    }


def cmd_cleanup_99() -> dict:
    """清理 99-待分类"""
    org = AutoOrganizer()
    misplaced = org.cleanup_99()
    return {
        "status": "ok",
        "count": len(misplaced),
        "items": [
            {"title": m.title, "suggested_folder": m.suggested_folder, "node_token": m.node_token}
            for m in misplaced
        ],
    }


def cmd_delete(doc_token: str, confirm: bool = False) -> dict:
    """删除文档"""
    if not confirm:
        return {"status": "aborted", "reason": "删除操作需要 --confirm 确认"}
    doc = FeishuDoc()
    ok = doc.delete_document(doc_token, confirm=True)
    return {"status": "ok" if ok else "error"}


def cmd_move(doc_token: str, target_token: str) -> dict:
    """移动文档"""
    doc = FeishuDoc()
    ok = doc.move(doc_token, target_token)
    return {"status": "ok" if ok else "error"}


def cmd_classify(title: str, content_file: str, llm_fallback_cmd: str | None = None) -> dict:
    """仅分类，不写入"""
    content = Path(content_file).read_text(encoding="utf-8")
    llm_cb = None
    if llm_fallback_cmd:
        import subprocess
        def _cb(prompt: str) -> str:
            r = subprocess.run(llm_fallback_cmd.split() + [prompt],
                               capture_output=True, text=True, timeout=30)
            return r.stdout.strip()
        llm_cb = _cb

    result = auto_route(title, content, llm_cb)
    return {
        "folder_key": result.folder_key,
        "doc_type": result.doc_type,
        "vendor": result.vendor,
        "product": result.product,
        "subdir": result.subdir_name,
    }


# ═══════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Saber 飞书知识库编排器")
    sub = parser.add_subparsers(dest="command", required=True)

    # write
    pw = sub.add_parser("write", help="写入新文档（唯一写入入口）")
    pw.add_argument("--title", required=True)
    pw.add_argument("--content-file", required=True, help="Markdown 内容文件路径")
    pw.add_argument("--cve-id", default="")
    pw.add_argument("--product", default="")
    pw.add_argument("--component", default="")
    pw.add_argument("--skip-poc-check", action="store_true")
    pw.add_argument("--skip-dedup", action="store_true", help="跳过查重（默认启用，命中直接返回链接）")
    pw.add_argument("--llm-fallback-cmd")
    pw.add_argument("--user-decision", choices=["proceed", "abort"])
    pw.add_argument("--verbose", action="store_true", help="输出详细进度")
    pw.add_argument("--env-file", default="", help="从文件加载环境变量（eg: /path/to/.env）")

    # organize
    sub.add_parser("organize", help="扫描垃圾和错位文档")

    # cleanup-99
    sub.add_parser("cleanup-99", help="清理 99-待分类")

    # delete
    pd = sub.add_parser("delete", help="删除文档")
    pd.add_argument("--doc-token", required=True)
    pd.add_argument("--confirm", action="store_true")

    # move
    pm = sub.add_parser("move", help="移动文档")
    pm.add_argument("--doc-token", required=True)
    pm.add_argument("--target-token", required=True)

    # classify
    pc = sub.add_parser("classify", help="仅分类不写入")
    pc.add_argument("--title", required=True)
    pc.add_argument("--content-file", required=True)
    pc.add_argument("--llm-fallback-cmd")

    # image
    pi = sub.add_parser("image", help="向文档插入图片")
    pi.add_argument("--doc-token", required=True)
    pi.add_argument("--image", required=True, help="PNG 图片路径")
    pi.add_argument("--index", type=int, default=0, help="插入位置（默认文档开头）")

    # render
    pr = sub.add_parser("render", help="Excalidraw 渲染为 PNG")
    pr.add_argument("--input", required=True, help=".excalidraw 文件路径")
    pr.add_argument("--output", default="", help="输出 PNG 路径（默认替换后缀）")
    pr.add_argument("--scale", type=int, default=2, help="缩放倍率（默认2）")

    args = parser.parse_args()

    # ── 从文件加载环境变量 ──
    env_file = getattr(args, 'env_file', '') or ''
    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip().strip("\"'")

    # ── 日志级别 ──
    verbose = getattr(args, 'verbose', False)
    if verbose:
        logging.getLogger('saber').setLevel(logging.DEBUG)

    def log_step(step: str, msg: str = ""):
        if verbose:
            logger.info("▶ [%s] %s", step, msg)

    if args.command == "write":
        content = Path(args.content_file).read_text(encoding="utf-8")
        log_step("1/7", "Pre-Check")
        result = pipeline_write(
            title=args.title,
            content=content,
            cve_id=args.cve_id,
            product=args.product,
            component=args.component,
            skip_poc_check=args.skip_poc_check,
            skip_dedup=args.skip_dedup,
            llm_fallback_cmd=args.llm_fallback_cmd,
            user_decision=args.user_decision,
        )

        # 写入成功后清理空图片块
        if result.get("status") in ("ok", "partial") and result.get("doc_token"):
            log_step("7/7", "清理空图片块")
            doc = FeishuDoc()
            try:
                cleaned = doc.cleanup_empty_images(result["doc_token"])
                if cleaned:
                    logger.info("post-write: 清理了 %d 个空图片块", cleaned)
            except Exception:
                pass

    elif args.command == "organize":
        result = cmd_organize()
    elif args.command == "cleanup-99":
        result = cmd_cleanup_99()
    elif args.command == "delete":
        result = cmd_delete(args.doc_token, args.confirm)
    elif args.command == "move":
        result = cmd_move(args.doc_token, args.target_token)
    elif args.command == "classify":
        result = cmd_classify(args.title, args.content_file, args.llm_fallback_cmd)
    elif args.command == "image":
        doc = FeishuDoc()
        try:
            doc.insert_image(args.doc_token, args.image, args.index)
            result = {"status": "ok", "doc_token": args.doc_token, "image": args.image, "index": args.index}
        except Exception as e:
            result = {"status": "error", "error": str(e)}
    elif args.command == "render":
        try:
            out = FeishuDoc.render_excalidraw(args.input, args.output or None, args.scale)
            result = {"status": "ok", "output": out}
        except Exception as e:
            result = {"status": "error", "error": str(e)}
    else:
        result = {"status": "error", "error": f"未知命令: {args.command}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
