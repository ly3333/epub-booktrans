# -*- coding: utf-8 -*-
"""可选：用 MeCab(UniDic) 给漏标的汉字补假名。

模型负责翻译并在译文里标音，覆盖大约 96%；剩下的代词、专有名词、
文档头部的固定文字常常漏标，这里用词典补一遍，稳定且不花 token。
需要额外安装：pip install fugashi unidic-lite
"""
import re

CJK = re.compile(r"[\u4e00-\u9fff]")
_tagger = None
_ok = None


def available():
    global _ok
    if _ok is None:
        try:
            import fugashi  # noqa: F401
            _ok = True
        except Exception:
            _ok = False
    return _ok


def _get_tagger():
    global _tagger
    if _tagger is None:
        import fugashi
        try:
            _tagger = fugashi.Tagger()               # 用默认 unidic
        except Exception:
            _tagger = False
    return _tagger or None


def _kata2hira(s):
    out = []
    for ch in s:
        o = ord(ch)
        if 0x30A1 <= o <= 0x30F6:
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _kana(tok):
    f = tok.feature
    for attr in ("kana", "kana_base", "pron", "pron_base"):
        v = getattr(f, attr, None)
        if v and v != "*":
            return _kata2hira(v)
    return None


def annotate(s):
    """给一句日文补 ruby；按空白切段，避免分词丢空格导致整句放弃。"""
    tg = _get_tagger()
    if not tg or not CJK.search(s):
        return s
    parts = re.split(r"(\s+)", s)
    out = []
    for part in parts:
        if not part or part.isspace() or not CJK.search(part):
            out.append(part)
            continue
        toks = list(tg(part))
        if "".join(t.surface for t in toks) != part:   # 还原不完整，宁可不标
            out.append(part)
            continue
        for tok in toks:
            surf = tok.surface
            if not CJK.search(surf):
                out.append(surf)
                continue
            read = _kana(tok)
            if not read or read == surf:
                out.append(surf)
                continue
            read = read.replace("-", "").replace(" ", "")
            if not re.fullmatch(r"[\u3040-\u309f\u30a0-\u30ffー]+", read):
                out.append(surf)
                continue
            from .epub import to_ruby          # 延迟导入，避免循环依赖
            out.append(to_ruby(surf, read))
    return "".join(out)


def fill_html(html):
    """只处理不在 <ruby> 里的文本节点。"""
    from bs4 import BeautifulSoup
    if not available():
        return html
    soup = BeautifulSoup(html, "html.parser")
    for t in list(soup.find_all(string=True)):
        if t.find_parent("ruby") is not None:
            continue
        s = str(t)
        if not CJK.search(s):
            continue
        new = annotate(s)
        if new != s:
            t.replace_with(BeautifulSoup(new, "html.parser"))
    return str(soup)
