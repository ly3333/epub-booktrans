# -*- coding: utf-8 -*-
"""配置加载：默认值 + config.json + 命令行覆盖。"""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEFAULTS = {
    "provider": "openai",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "temperature": 0.6,
    "max_tokens": 8192,
    "timeout": 180,
    "retries": 3,
    "concurrency": 6,
    "words_per_chunk": 1200,
    "glossary": "glossary.txt",
    "style_notes": "",
    "price_in_per_mtok": 0.0,
    "price_out_per_mtok": 0.0,
    # 换行 kinds：翻译出来的内联标签统一映射到这几个 class，
    # 由 ensure_extra_css() 把规则写进原书 CSS，保证任何书都能正确显示。
    "css": {
        "italic": "bt-i",
        "bold": "bt-b",
        "strike": "bt-s",
        "underline": "bt-u",
        "smallcaps": "bt-sc",
        "mono": "bt-tt",
        "dropcap": "bt-drop",
    },
    # 原书给行内文字上色 / 改字号（.calibre4{color:#4c7aa9} 之类）时，
    # 没有通用语义标签可替代 —— 要么保留原 class（省事但送进模型的文本变长，
    # 少数模型会把嵌套标签搞乱），要么丢掉（丢这部分观感）。
    # 默认丢：与已验证过的产出保持一致。想尽量还原原书观感就设 true。
    "keep_inline_styles": False,
    # 注音排版方式：
    #   std  = 标准 <ruby>，假名排在汉字上方（Calibre / Apple Books / Thorium / 多看 都支持）
    #   span = 兼容模式，不依赖 ruby 支持，用 inline-block 上下堆叠
    #          给不支持 <ruby> 的阅读器用（不然假名会作为普通文字接在汉字后面）
    "ruby_mode": "std",
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def ensure_default_config():
    """首次运行时生成带注释的配置模板。"""
    p = ROOT / "config.json"
    if p.exists():
        return p
    tpl = {
        "_说明": "provider 支持 openai（任何 OpenAI 兼容接口，含 DeepSeek）与 mock（自测用）",
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "在这里填你的 API Key",
        "model": "deepseek-chat",
        "temperature": 0.6,
        "max_tokens": 8192,
        "concurrency": 6,
        "words_per_chunk": 1200,
        "glossary": "glossary.txt",
        "style_notes": "",
    }
    p.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_config(path=None):
    cfg = dict(DEFAULTS)
    p = pathlib.Path(path) if path else ROOT / "config.json"
    if p.exists():
        try:
            cfg = _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            raise SystemExit("配置文件 %s 解析失败：%s" % (p, e))
    cfg["_root"] = str(ROOT)
    cfg["_config_path"] = str(p)
    return cfg


def load_glossary(path) -> dict:
    """术语表格式（UTF-8 文本）：
       术语 = 中文 | 日本語      # 双语都指定
       术语 = 中文               # 只指定中文
       以 # 开头为注释
    """
    if not path:
        return {}
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        parts = [x.strip() for x in v.split("|")]
        out[k.strip()] = {"zh": parts[0] if parts else "", "ja": parts[1] if len(parts) > 1 else ""}
    return out
