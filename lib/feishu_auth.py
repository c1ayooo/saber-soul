"""
飞书认证模块 — tenant_access_token 获取与缓存
所有脚本的唯一认证入口，禁止手写认证逻辑。
V2: 添加 api_request_with_retry 自动重试+指数退避
"""
import time
from urllib import request, error
import json
import logging
import random

from .config import get_config

logger = logging.getLogger("saber.feishu_auth")

# 模块级缓存
_cached_token: str = ""
_cached_expire: float = 0.0
_token_lock = False  # 防止并发刷新


def get_tenant_access_token() -> str:
    """获取 tenant_access_token，自动缓存，过期前 5 分钟刷新。"""
    global _cached_token, _cached_expire
    now = time.time()
    if _cached_token and now < _cached_expire - 300:
        return _cached_token
    return _refresh_token()


def _refresh_token() -> str:
    global _cached_token, _cached_expire, _token_lock
    if _token_lock:
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
        body = json.dumps({"app_id": cfg.app_id, "app_secret": cfg.app_secret}).encode("utf-8")
        req = request.Request(url, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
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
    method: str, path: str, body: dict | None = None,
    query: dict | None = None, timeout: int = 30,
) -> dict:
    """统一的飞书 API 请求封装。自动注入 Authorization header。"""
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


# ── 带重试的 API 请求 ────────────────────────────────────

_MAX_RETRIES = 3
_BASE_DELAY = 1.5


def api_request_with_retry(
    method: str, path: str, body: dict | None = None,
    query: dict | None = None, timeout: int = 30,
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """
    带自动重试 + 指数退避的 API 请求。
    SSL 错误/408/429/5xx 自动重试，最多 max_retries 次。
    401 时自动刷新 token 后重试。
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return api_request(method, path, body, query, timeout)
        except RuntimeError as e:
            msg = str(e)
            # 401 → token 过期，刷新后重试
            if "HTTP 401" in msg and attempt < max_retries:
                invalidate_token()
                delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.warning("token 过期，刷新后重试 (attempt %d/%d)", attempt, max_retries)
                time.sleep(delay)
                last_error = e
                continue
            # SSL / 网络错误 → 重试
            if any(kw in msg for kw in ("网络错误", "SSL", "timeout", "EOF", "408", "429", "50")):
                if attempt < max_retries:
                    delay = _BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning("API 请求失败，%s 秒后重试 (attempt %d/%d): %s",
                                   round(delay, 1), attempt, max_retries, msg[:60])
                    time.sleep(delay)
                    last_error = e
                    continue
            raise e
        except Exception as e:
            raise e
    raise RuntimeError(f"API 请求重试 {max_retries} 次均失败: {last_error}")


def invalidate_token():
    """主动使 token 缓存失效，用于 401 重试场景"""
    global _cached_token, _cached_expire
    _cached_token = ""
    _cached_expire = 0.0
