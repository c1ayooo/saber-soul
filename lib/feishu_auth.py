"""
飞书认证模块 — tenant_access_token 获取与缓存
所有脚本的唯一认证入口，禁止手写认证逻辑。
"""
import time
from urllib import request, error
import json
import logging

from .config import get_config

logger = logging.getLogger("saber.feishu_auth")

# 模块级缓存
_cached_token: str = ""
_cached_expire: float = 0.0
_token_lock = False  # 防止并发刷新


def get_tenant_access_token() -> str:
    """
    获取 tenant_access_token，自动缓存，过期前 5 分钟刷新。
    所有飞书 API 调用必须通过此函数获取 token。
    """
    global _cached_token, _cached_expire

    now = time.time()
    if _cached_token and now < _cached_expire - 300:
        return _cached_token

    return _refresh_token()


def _refresh_token() -> str:
    global _cached_token, _cached_expire, _token_lock

    if _token_lock:
        # 等待另一个刷新完成（最多 5 秒）
        for _ in range(50):
            time.sleep(0.1)
            if not _token_lock:
                return _cached_token
    _token_lock = True

    try:
        cfg = get_config()
        if not cfg.app_id or not cfg.app_secret:
            raise RuntimeError(
                "FEISHU_APP_ID / FEISHU_APP_SECRET 未设置。"
                "请设置环境变量或配置 feishu_config.json"
            )

        url = f"{cfg.api_base}/auth/v3/tenant_access_token/internal"
        body = json.dumps({
            "app_id": cfg.app_id,
            "app_secret": cfg.app_secret,
        }).encode("utf-8")

        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")

        _cached_token = data["tenant_access_token"]
        _cached_expire = time.time() + data.get("expire", 7200)
        logger.info("token 已刷新，有效期至 %s", time.ctime(_cached_expire))
        return _cached_token

    except error.HTTPError as e:
        raise RuntimeError(f"认证请求失败 HTTP {e.code}") from e
    except error.URLError as e:
        raise RuntimeError(f"认证请求网络错误: {e.reason}") from e
    finally:
        _token_lock = False


def api_request(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    timeout: int = 30,
) -> dict:
    """
    统一的飞书 API 请求封装。
    自动注入 Authorization header 和 Content-Type。

    Args:
        method: HTTP 方法（GET/POST/PATCH/DELETE）
        path: API 路径（如 /wiki/v2/spaces/{space_id}/nodes）
        body: 请求体（仅 POST/PATCH）
        query: URL 查询参数
        timeout: 超时秒数

    Returns:
        API 响应 JSON dict（已解析 code 字段，非 0 抛异常）
    """
    cfg = get_config()
    token = get_tenant_access_token()
    url = f"{cfg.api_base}{path}"

    if query:
        from urllib.parse import urlencode
        url += "?" + urlencode(query)

    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    req = request.Request(url, data=data_bytes, headers=headers, method=method)

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"API 请求失败 HTTP {e.code}: {err_body[:500]}") from e
    except error.URLError as e:
        raise RuntimeError(f"API 请求网络错误: {e.reason}") from e

    if result.get("code") != 0:
        raise RuntimeError(f"API 返回错误: code={result.get('code')} msg={result.get('msg')}")

    return result.get("data", result)


def invalidate_token():
    """主动使 token 缓存失效，用于 401 重试场景"""
    global _cached_token, _cached_expire
    _cached_token = ""
    _cached_expire = 0.0
