# -*- coding: utf-8 -*-
"""读原书的 CSS，把 span 的 class 翻译成「语义标签」。

为什么需要这一步：Calibre 转出来的书，斜体可能叫 .italic、也可能叫 .ital、.it2、
.calibre7 —— 只看类名一定会漏。唯一的真相在 CSS 声明里：
font-style:italic 就是斜体，不管它叫什么名字。
"""
import os
import re

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
COMMENT = re.compile(r"/\*.*?\*/", re.S)

# 类名启发式：CSS 读不到时的兜底（比如样式写在 <style> 里或内联）
NAME_HINT = [
    ("small-caps", "sc"), ("smallcaps", "sc"), ("small-cap", "sc"), ("caps", "sc"),
    ("linethrough", "s"), ("strike", "s"), ("strikethrough", "s"),
    ("superscript", "sup"), ("superscript-num", "sup"), ("note", "sup"),
    ("subscript", "sub"),
    ("italic", "i"), ("ital", "i"), ("oblique", "i"), ("emph", "i"),
    ("mono", "tt"), ("code", "tt"), ("typewriter", "tt"),
    ("underline", "u"), ("underlined", "u"),
    ("bold", "b"), ("bolder", "b"), ("strong", "b"), ("heavy", "b"),
]

# 重点：同一串关键字按优先级取第一个命中的，因为 "bold-italic" 只有一个坑位
PRIORITY = ["sup", "sub", "sc", "tt", "u", "s", "i", "b"]


def parse(text):
    """返回 {class 名: {属性: 值}}，值已小写。"""
    out = {}
    for m in RULE.finditer(COMMENT.sub(" ", text or "")):
        sel = m.group(1)
        if "@" in sel:
            continue
        decls = {}
        for d in m.group(2).split(";"):
            if ":" not in d:
                continue
            k, v = d.split(":", 1)
            decls[k.strip().lower()] = v.strip().lower()
        if not decls:
            continue
        for part in sel.split(","):
            for cls in re.findall(r"\.([A-Za-z_][\w\-]*)", part):
                out.setdefault(cls, {}).update(decls)
    return out


# 「有实际观感作用」的声明：没有通用语义标签能替代，只能保留原 class
VISUAL_KEYS = ("color", "background-color", "font-family", "font-size",
               "text-transform", "letter-spacing", "font-variant")


def _has_visual(decls):
    return any(k in decls for k in VISUAL_KEYS)


def _em(v):
    """把 font-size 换成相对倍数，用于判定首字下沉。"""
    m = re.match(r"([\d.]+)\s*(em|%|rem|px)", v or "")
    if not m:
        return 0.0
    n = float(m.group(1))
    return {"em": n, "rem": n, "%": n / 100.0, "px": n / 16.0}.get(m.group(2), 0.0)


def _classify(decls):
    hits = []
    fw = decls.get("font-weight", "")
    if fw in ("bold", "bolder", "600", "700", "800", "900") or fw.isdigit() and int(fw) >= 600:
        hits.append("b")
    fs = decls.get("font-style", "")
    if fs in ("italic", "oblique"):
        hits.append("i")
    td = decls.get("text-decoration", "")
    if "line-through" in td:
        hits.append("s")
    if td.startswith("underline") or " underline" in td:
        hits.append("u")
    fv = decls.get("font-variant", "")
    if "small-caps" in fv or "smallcaps" in fv:
        hits.append("sc")
    if decls.get("text-transform", "") == "uppercase" and decls.get("font-size", ""):
        hits.append("sc")
    if "monospace" in decls.get("font-family", "") or "courier" in decls.get("font-family", ""):
        hits.append("tt")
    va = decls.get("vertical-align", "")
    if va in ("super", "top", "text-top"):
        hits.append("sup")
    elif va in ("sub", "bottom", "text-bottom"):
        hits.append("sub")
    for tag in PRIORITY:
        if tag in hits:
            return tag
    return None


class StyleInfo:
    """一本书的样式归类表。"""

    def __init__(self, paths):
        self.map = {}
        for p in paths:
            try:
                raw = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for cls, decls in parse(raw).items():
                self.map.setdefault(cls, decls)
        # 「可能是首字下沉」的 class：字够大，或者带 float。
        # 是否真的算下沉，还要看它是不是段落开头且只包 1 个字符——见 is_dropcap()。
        self.big = {c for c, d in self.map.items()
                    if _em(d.get("font-size", "")) >= 1.5
                    or d.get("float", "") in ("left", "right")}

    def tag_for(self, classes, keep_styles=True):
        """给定一串 class，返回语义标签（i/b/s/u/sc/sup/sub/tt）或 'keep'。

        'keep' = CSS 里带了颜色/字号之类、但没有通用语义标签可替换，
        这种场合保留原 class，让原书的 CSS 继续生效。
        """
        cls = [c for c in (classes or []) if c]
        # 先看 CSS 声明——这是真相
        for c in cls:
            t = _classify(self.map.get(c, {}))
            if t:
                return t
        # 再看类名
        low = " ".join(cls).lower()
        hits = []
        for key, tag in NAME_HINT:
            if key in low:
                hits.append(tag)
        for tag in PRIORITY:
            if tag in hits:
                return tag
        for c in cls:
            if keep_styles and _has_visual(self.map.get(c, {})):
                return "keep"
        return None

    def is_dropcap(self, cls, text=""):
        """首字下沉判定：段首的 span，且它后面还有正文。

        两个条件缺一不可：
        - 后面还有正文 → 排除「整段都是大号字」的标题（那种由 wrap 机制整段包回去）
        - 字够大或有 float → 排除普通行内强调
        """
        low = " ".join(cls or []).lower()
        if any(k in low for k in ("dropcap", "drop-cap", "drop_cap", "initial")):
            return True
        return len(text) <= 2 and any(c in self.big for c in (cls or []))


def collect(srcdir, opfdir, hrefs):
    """把 manifest 里的 text/css 文件收集起来。"""
    paths = []
    for h in hrefs:
        p = os.path.normpath(os.path.join(opfdir, h))
        if os.path.exists(p):
            paths.append(p)
    return StyleInfo(paths)
