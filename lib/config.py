"""
统一配置管理
优先级：环境变量 > feishu_config.json > 默认值
"""
import json
import os
import re
from pathlib import Path
from typing import Any


# 默认配置目录（可被 SABER_CONFIG_DIR / FEISHU_CONFIG_DIR 环境变量覆盖）
def _config_dir() -> Path:
    for var in ("SABER_CONFIG_DIR", "FEISHU_CONFIG_DIR"):
        if os.environ.get(var):
            return Path(os.environ[var])
    return Path(__file__).resolve().parent.parent  # saber_soul/


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "feishu_config.json"
CLASSIFICATION_DATA = CONFIG_DIR / "references" / "classification_config.json"


# ── 内置默认值 ────────────────────────────────────────────

DEFAULT_PROHIBITED_WORDS = [
    "可能", "大概", "尝试", "看看", "应该是", "似乎",
]

DEFAULT_PROHIBITED_MAP = {
    "可能": "存在 / 不存在",
    "大概": "确认 / 未确认",
    "尝试": "执行 / 执行失败",
    "看看": "检查 / 检查结果为",
    "应该是": "是 / 不是",
    "似乎": "确认存在该行为 / 未观察到该行为",
}

DEFAULT_GARBAGE_RULES = [
    {
        "name": "内容过少",
        "min_chars": 50,
        "reason": "正文少于50字符，疑似占位文档",
    },
    {
        "name": "标题废弃",
        "title_patterns": ["^副本", "^copy", "^Copy of"],
        "reason": "疑似副本/废弃文档",
    },
    {
        "name": "测试残留",
        "keywords": ["test", "TODO", "测试", "草稿"],
        "min_hits": 2,
        "reason": "疑似测试/草稿残留",
    },
]

DEFAULT_COMMAND_PATTERNS = [
    r"^curl\b",
    r"^nmap\b",
    r"^验证命令:",
]


# ── 配置加载 ──────────────────────────────────────────────

class Config:
    """统一配置，延迟加载，支持运行时更新"""

    def __init__(self):
        self._json: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> dict[str, Any]:
        if self._loaded:
            return self._json
        self._json = {}
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._json = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        self._loaded = True
        return self._json

    def _load_classification_data(self) -> dict[str, Any]:
        if CLASSIFICATION_DATA.exists():
            try:
                with open(CLASSIFICATION_DATA, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    # ── 凭证 ──

    @property
    def app_id(self) -> str:
        return os.environ.get("FEISHU_APP_ID") or self._ensure_loaded().get("FEISHU_APP_ID", "")

    @property
    def app_secret(self) -> str:
        return os.environ.get("FEISHU_APP_SECRET") or self._ensure_loaded().get("FEISHU_APP_SECRET", "")

    @property
    def space_id(self) -> str:
        return os.environ.get("FEISHU_SPACE_ID") or self._ensure_loaded().get("SPACE_ID", "") or self._ensure_loaded().get("space_id", "")

    @property
    def api_base(self) -> str:
        return os.environ.get("FEISHU_API_BASE", "https://open.feishu.cn/open-apis")

    @property
    def log_level(self) -> str:
        return os.environ.get("SABER_LOG_LEVEL") or self._ensure_loaded().get("log_level", "INFO")

    # ── 分类规则 ──

    @property
    def classify_rules(self) -> list[dict]:
        user = self._ensure_loaded().get("classify_rules")
        if user is not None:
            return user
        data = self._load_classification_data()
        return data.get("doc_type_rules", [])

    # ── 厂商/产品映射 ──

    @property
    def vendor_product_map(self) -> dict:
        data = self._load_classification_data()
        default = data.get("vendor_product_map", {})
        user = self._ensure_loaded().get("vendor_product_map")
        if user is not None:
            return _deep_merge(default, user)
        return default

    @property
    def alias_map(self) -> dict:
        data = self._load_classification_data()
        default = data.get("alias_map", {})
        user = self._ensure_loaded().get("alias_map")
        if user is not None:
            return _deep_merge(default, user)
        return default

    @property
    def non_24_routes(self) -> dict:
        data = self._load_classification_data()
        default = data.get("non_24_routes", {})
        user = self._ensure_loaded().get("non_24_routes")
        if user is not None:
            return _deep_merge(default, user)
        return default

    # ── 垃圾规则 ──

    @property
    def garbage_rules(self) -> list[dict]:
        user = self._ensure_loaded().get("garbage_rules")
        if user is not None:
            return user
        return DEFAULT_GARBAGE_RULES

    # ── 禁词 ──

    @property
    def prohibited_words(self) -> list[str]:
        user = self._ensure_loaded().get("prohibited_words")
        if user is not None:
            return user
        return DEFAULT_PROHIBITED_WORDS

    @property
    def prohibited_map(self) -> dict[str, str]:
        default = dict(DEFAULT_PROHIBITED_MAP)
        user = self._ensure_loaded().get("prohibited_map")
        if user is not None:
            default.update(user)
        return default

    @property
    def command_patterns(self) -> list[str]:
        default = list(DEFAULT_COMMAND_PATTERNS)
        user = self._ensure_loaded().get("command_patterns")
        if user is not None:
            seen = set(default)
            for p in user:
                if p not in seen:
                    default.append(p)
                    seen.add(p)
        return default

    # ── token 缓存 ──

    def get_folder_token(self, key: str) -> str:
        tokens = self._ensure_loaded().get("folder_tokens", {})
        return tokens.get(key, "")

    def set_folder_token(self, key: str, token: str):
        self._ensure_loaded()
        self._json.setdefault("folder_tokens", {})[key] = token
        self._save()

    def get_node_tokens(self) -> dict:
        return self._ensure_loaded().get("folder_tokens", {})

    def _save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._json, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# 预编译禁词正则（检查速度更快）
def _compile_prohibited_re(words: list[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(w) for w in words))


# 单例
_config_instance: Config | None = None


def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
