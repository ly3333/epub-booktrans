# -*- coding: utf-8 -*-
"""EPUB 解析 / 单元抽取 / 译文回填 / 打包。

设计前提：**原书的排版信息是资产，不是噪音。**
抽取时尽量保留内联标签、换行、代码块空白；只在「标签无法与译文对应」时才降级去掉。
"""
import html
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from bs4 import BeautifulSoup

from . import cssmap

BLOCK = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd",
         "blockquote", "div", "td", "th", "figcaption", "pre"}
DOC_EXT = (".html", ".xhtml", ".htm")

# 原生标签统一化的目标，便于记忆，也便于模型复现
NATIVE_ALIAS = {"em": "i", "cite": "i", "dfn": "i", "var": "i",
                "strong": "b", "del": "s", "strike": "s",
                "ins": "u", "code": "code", "tt": "code", "kbd": "code", "samp": "code"}
# cssmap 归类结果 → 实际写进抽取文本的标签
TARGET_TAG = {"i": "i", "b": "b", "s": "s", "u": "u",
              "sc": "sc", "tt": "code", "sup": "sup", "sub": "sub"}

# render 时允许通过的内联标签（模型可能吐出任何一种）
ALLOWED = re.compile(
    r"</?(?:i|b|s|u|em|strong|del|strike|ins|code|tt|kbd|samp|var|cite|dfn"
    r"|sup|sub|small|br|a|span|ruby|rt|rb|rp)\b[^>]*>", re.I)
KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# 一个注音单元。rp 是给不支持 ruby 的阅读器看的降级括号。
RUBY = "<ruby>%s<rp>(</rp><rt>%s</rt><rp>)</rp></ruby>"
# 兼容模式：完全不依赖 <ruby> 支持，用 inline-block 上下堆叠模拟注音。
# 布局不支持 ruby 的阅读器（不少国产阅读器就是）只能靠这个。
RUBY_SPAN = ('<span class="bt-rb"><span class="bt-rt">%s</span>'
             '<span class="bt-rb-b">%s</span></span>')
RUBY_MODE = "std"          # std | span，由 cli 按 --ruby-mode 或 config 设置


def set_ruby_mode(mode):
    global RUBY_MODE
    RUBY_MODE = "span" if str(mode).lower() in ("span", "compat", "fallback") else "std"
    return RUBY_MODE

FALLBACK_CSS = """
/* booktrans: 行内样式与振假名的兜底规则（原书缺哪条补哪条） */
.bt-i{font-style:italic}
.bt-b{font-weight:bold}
.bt-s{text-decoration:line-through}
.bt-u{text-decoration:underline}
.bt-sc{font-variant:small-caps}
.bt-tt{font-family:monospace}
/* 注意：这里绝对不能给 ruby 写 display:inline。
   那会把注音排版关掉，<rt> 变成普通行内文字，
   假名直接接在汉字后面（"重要じゅうよう"）。2026-10-22 踩过。 */
ruby{ruby-align:center;-webkit-ruby-align:center}
rt{font-size:.5em;line-height:1.1;font-weight:normal;font-style:normal;
   letter-spacing:0;-webkit-ruby-position:over;ruby-position:over}
/* <rp> 是给不支持 ruby 的阅读器看的括号，交给浏览器自己的 UA 样式去隐藏，
   这里不要写 display:none，否则降级阅读器会退化成"重要じゅうよう"。 */
/* 兼容模式（--ruby-mode span）：不依赖 ruby 支持，注音叠在汉字正上方 */
.bt-rb{display:inline-block;text-align:center;vertical-align:baseline;line-height:1.15;
   margin:0 .02em}
.bt-rt{display:block;font-size:.5em;line-height:1.2;white-space:nowrap}
.bt-rb-b{display:block;line-height:1.15}
"""


def wc(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return len(re.findall(r"[A-Za-z][A-Za-z'\-]*", s))


def _is_leaf_block(el):
    return not any(getattr(d, "name", None) in BLOCK for d in el.descendants)


class EpubBook:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.srcdir = tempfile.mkdtemp(prefix="booktrans_src_")
        with zipfile.ZipFile(self.path) as z:
            z.extractall(self.srcdir)
        self.opf_path = self._find_opf()
        self.opfdir = os.path.dirname(self.opf_path)
        self.opf_text = open(self.opf_path, encoding="utf-8", errors="replace").read()
        self.docs, self.nav_doc, self.css_hrefs = self._read_manifest()
        self.style = cssmap.collect(self.srcdir, self.opfdir, self.css_hrefs)

    def _find_opf(self):
        container = os.path.join(self.srcdir, "META-INF", "container.xml")
        if os.path.exists(container):
            soup = BeautifulSoup(open(container, encoding="utf-8", errors="replace").read(), "xml")
            rf = soup.find("rootfile")
            if rf and rf.get("full-path"):
                return os.path.join(self.srcdir, rf["full-path"])
        for p in os.listdir(self.srcdir):
            if p.endswith(".opf"):
                return os.path.join(self.srcdir, p)
        raise SystemExit("这个 EPUB 里找不到 .opf，可能不是标准 EPUB")

    def _read_manifest(self):
        soup = BeautifulSoup(self.opf_text, "xml")
        items = soup.find_all("item")
        by_id, css, nav = {}, [], None
        for it in items:
            i, h = it.get("id"), it.get("href")
            if not i or not h:
                continue
            by_id[i] = h
            mt = (it.get("media-type") or "").lower()
            if mt == "text/css" or h.lower().endswith(".css"):
                css.append(h)
            if "nav" in (it.get("properties") or ""):
                nav = h
        spine = []
        for ref in soup.find_all("itemref"):
            idr = ref.get("idref")
            if idr in by_id:
                spine.append(by_id[idr])
        docs = [h for h in spine if h.lower().endswith(DOC_EXT)]
        return docs, nav, css

    def doc_path(self, href):
        return os.path.normpath(os.path.join(self.opfdir, href))

    def close(self):
        shutil.rmtree(self.srcdir, ignore_errors=True)


def extract_docs(book, keep_styles=True):
    """把每个文档拆成「带占位符的模板」+「待译单元」。

    nav.xhtml 不在这里处理——它的目录结构靠 <a href> 撑着，
    整段抽取有被模型改写 href 的风险，改由 collect_toc / patch_nav 只替换文字。
    """
    out = []
    navkey = os.path.basename(book.nav_doc).lower() if book.nav_doc else None
    for href in book.docs:
        if navkey and os.path.basename(href).lower() == navkey:
            continue
        p = book.doc_path(href)
        if not os.path.exists(p):
            continue
        raw = open(p, encoding="utf-8", errors="replace").read()
        m = re.search(r"<body[^>]*>", raw, re.I)
        if not m:
            continue
        head_end = m.end()
        tail_start = raw.lower().rfind("</body>")
        if tail_start < 0:
            tail_start = len(raw)
        head, body, tail = raw[:head_end], raw[head_end:tail_start], raw[tail_start:]
        soup = BeautifulSoup(body, "html.parser")
        meta, n = {}, 0
        for el in soup.find_all(list(BLOCK)):
            if not _is_leaf_block(el):
                continue
            # 先判空：纯锚点段落原样留在模板里，一个标签都不动
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            for a in el.find_all("a"):
                if not a.get_text(strip=True) and not a.find("img"):
                    if a.get("id"):
                        a.extract()
                        el.insert(0, a)      # 跳转锚点上提到段首，不能丢
                    elif not a.get("href"):
                        a.decompose()
            n += 1
            uid = "U%04d" % n
            inner = "".join(str(c) for c in el.contents)
            clean, wrap, dropcap, anchors = _prep(
                inner, book.style, keep_ws=(el.name == "pre"),
                keep_styles=keep_styles)
            if not clean:
                n -= 1
                continue
            meta[uid] = {"wrap": wrap, "dropcap": dropcap, "anchors": anchors,
                         "en": clean, "tag": el.name}
            el.clear()
            el.append("@@%s@@" % uid)
        tpl = head + str(soup) + tail
        out.append({"href": href, "path": p, "tpl": tpl, "meta": meta,
                    "title": _doc_title(raw)})
    return out


def _doc_title(raw):
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _prep(inner, style=None, keep_ws=False, keep_styles=True):
    """归一化内联标签，摘出首字下沉与整段包裹的 span。

    keep_ws=True 时不压空白（代码块、pre）。
    <br> 保留成 <br/>——诗歌、歌词、地址、签名块的换行是内容的一部分。
    """
    soup = BeautifulSoup(inner, "html.parser")
    anchors = []
    for a in soup.find_all("a"):
        if a.get("id") and not a.get("href") and not a.get_text(strip=True):
            anchors.append(a["id"])
            a.decompose()

    style = style or cssmap.StyleInfo([])

    # 首字下沉：包着第一个字符（通常就 1~2 个字符）的 span
    dropcap = None
    for sp in soup.find_all("span", recursive=False):
        cls = sp.get("class", []) or []
        if style.is_dropcap(cls, sp.get_text()):
            dropcap = " ".join(cls)
            sp.unwrap()
            break

    # 整段被一个 span 包住 → 记下 class，回填时整段包回去（模型不用碰标签）
    wrap = None
    while True:
        kids = [c for c in soup.contents if getattr(c, "name", None) or str(c).strip()]
        if len(kids) != 1 or getattr(kids[0], "name", None) != "span":
            break
        t = style.tag_for(kids[0].get("class") or [], keep_styles)
        if t and t != "keep":
            break                                    # 语义行内样式，留给模型原样带回
        cls = " ".join(kids[0].get("class", []) or [])
        wrap = (cls + " " + (wrap or "")).strip()
        kids[0].unwrap()

    for el in soup.find_all(list(NATIVE_ALIAS)):
        if el.name != NATIVE_ALIAS[el.name]:
            el.name = NATIVE_ALIAS[el.name]
            el.attrs = {}

    for sp in soup.find_all("span"):
        target = style.tag_for(sp.get("class") or [], keep_styles)
        if not target:
            sp.unwrap()                              # 认不出来＝承载不了样式，去掉不影响观感
            continue
        if target == "keep":
            sp.attrs = {"class": " ".join(sp.get("class") or [])}
        elif target == "sc":
            sp.name = "span"
            sp.attrs = {"class": "bt-sc"}
        else:
            sp.name = TARGET_TAG[target]
            sp.attrs = {}

    txt = str(soup)                    # bs4 会把 <br> 输出成 <br/>，原样保留
    if not keep_ws:
        txt = re.sub(r"[ \t\r\n]+", " ", txt).strip()
    # pre / 代码块：缩进与空行都是内容，一个字符都不动
    return txt, wrap, dropcap, anchors


def to_ruby(form, read):
    """{表記|よみ} → 逐汉字 run 的 ruby，送り仮名留在 ruby 外。

    输出带 <rp> 括号：支持 ruby 的阅读器会自动隐藏 rp，显示汉字上方的注音；
    不支持的阅读器会显示成「重要（じゅうよう）」——比「重要じゅうよう」可读得多。
    """
    read = re.sub(r"[^\u3040-\u309f\u30a0-\u30ffー]", "", read)
    out, i, j = [], 0, 0
    while i < len(form):
        if KANA.match(form[i]):
            k = i
            while k < len(form) and KANA.match(form[k]):
                k += 1
            run = form[i:k]
            m = read.find(run, j)
            if m != -1:
                j = m + len(run)
            out.append(run)
            i = k
            continue
        k = i
        while k < len(form) and not KANA.match(form[k]):
            k += 1
        kanji = form[i:k]
        if k < len(form):
            m = read.find(form[k], j)
            rd, j = (read[j:m], m) if m != -1 else (read[j:], len(read))
        else:
            rd, j = read[j:], len(read)
        out.append((RUBY_SPAN % (rd, kanji) if RUBY_MODE == "span" else RUBY % (kanji, rd))
                   if rd else kanji)
        i = k
    out.append(form[i:])
    out.append(read[j:])
    return "".join(out)


# render 时把模型吐出的标签映射回「一定有效」的 span class
OPEN_TO_CSSKEY = {
    "i": "italic", "em": "italic", "cite": "italic", "dfn": "italic", "var": "italic",
    "b": "bold", "strong": "bold",
    "s": "strike", "del": "strike", "strike": "strike",
    "u": "underline", "ins": "underline",
    "code": "mono", "tt": "mono", "kbd": "mono", "samp": "mono",
}
PASSTHROUGH = {"sup", "sub", "small", "ruby", "rt", "rb", "rp", "a", "span"}


def render_text(s, lang, cfg):
    css = cfg.get("css") or {}
    prot = []

    def keep(x):
        prot.append(x)
        return "\x00%d\x00" % (len(prot) - 1)

    def keep_tag(m):
        t = m.group(0)
        name = re.match(r"</?([a-zA-Z]+)", t).group(1).lower()
        if t.startswith("</"):
            if name in OPEN_TO_CSSKEY or name == "span":
                return keep("</span>")
            if name == "br":
                return keep("<br/>")
            return keep("</%s>" % name) if name in PASSTHROUGH else keep(t)
        if name == "br":
            return keep("<br/>")
        if name in OPEN_TO_CSSKEY:
            return keep('<span class="%s">' % css.get(OPEN_TO_CSSKEY[name], "bt-x"))
        return keep(t)

    if lang == "ja":
        s = re.sub(r"\{([^{}|]+)\|([^{}|]+)\}", lambda m: keep(to_ruby(m.group(1), m.group(2))), s)
        s = re.sub(r"([\u4e00-\u9fff]+)\{([\u3040-\u309f\u30a0-\u30ff]+)\}",
                   lambda m: keep(to_ruby(m.group(1), m.group(2))), s)
        # 片假名后面跟注音的情况（レーベル{れーべる}）：片假名本来不需要注音，
        # 留着标记只会退化成"レーベルれーべる"，直接丢掉标记。
        s = re.sub(r"\{[\u3040-\u309f\u30a0-\u30ffー]+\}", "", s)
        s = s.replace("{", "").replace("}", "")
    s = ALLOWED.sub(keep_tag, s)
    # 原书里的实体（&nbsp; &amp; &lt; &#8212;）必须原样带走，不能被二次转义成 &amp;nbsp;
    s = re.sub(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);", lambda m: keep(m.group(0)), s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\x00(\d+)\x00", lambda m: prot[int(m.group(1))], s)


def render_doc(doc, tr, lang, cfg, book_title="", fill_furigana=False):
    tpl = doc["tpl"]
    if book_title:
        tpl = re.sub(r"<title>[^<]*</title>", "<title>%s</title>" % html.escape(book_title), tpl, count=1)
    for uid, m in doc["meta"].items():
        text = tr.get(uid)
        if text is None or not str(text).strip():
            body = m["en"]                     # 没译到就保留原文，绝不出现空白段
        else:
            body = render_text(str(text), lang, cfg)
        if m["dropcap"]:
            mm = re.match(r"^(\s*)(<[^>]+>)?(.)", body, re.S)
            if mm:
                pre = mm.group(1) + (mm.group(2) or "")
                rest = body[len(pre):]
                body = pre + '<span class="%s">%s</span>%s' % (m["dropcap"], rest[0], rest[1:])
        if m["wrap"]:
            cls = m["wrap"].split()
            body = "".join('<span class="%s">' % c for c in cls[::-1]) + body + "</span>" * len(cls)
        if m["anchors"]:
            body = "".join('<a id="%s"></a>' % a for a in m["anchors"]) + body
        if fill_furigana and lang == "ja":
            from . import furigana
            body = furigana.fill_html(body)
        tpl = tpl.replace("@@%s@@" % uid, body, 1)
    tpl = re.sub(r"@@U\d{4}@@", "", tpl)
    return tpl


def set_doc_lang(text, lang):
    """给 <html> 写 lang/xml:lang：决定字形（日 vs 中汉字）与断行规则。"""

    def sub(m):
        tag = re.sub(r'\s(?:xml:)?lang\s*=\s*"[^"]*"', "", m.group(0))
        return tag.rstrip()[:-1] + ' lang="%s" xml:lang="%s">' % (lang, lang)

    return re.sub(r"<html\b[^>]*>", sub, text, count=1, flags=re.I)


def ensure_extra_css(buildroot, css_hrefs, opfdir):
    """给书籍原有 CSS 追加兜底规则；一本 CSS 都没有就新建 bt.css 并在每个 XHTML 里 link。"""
    added = []
    for h in css_hrefs:
        p = os.path.normpath(os.path.join(opfdir, h))
        if not os.path.exists(p):
            continue
        raw = open(p, encoding="utf-8", errors="replace").read()
        if "bt-i{" in raw.replace(" ", "") and "ruby" in raw:
            continue
        open(p, "w", encoding="utf-8").write(raw.rstrip() + "\n" + FALLBACK_CSS)
        added.append(h)
    return added


def patch_opf(text, lang, title, newid):
    text = re.sub(r"(<dc:language[^>]*>)[^<]*(</dc:language>)", r"\g<1>%s\g<2>" % lang, text, count=1)
    text = re.sub(r"(<dc:title[^>]*>)[^<]*(</dc:title>)", r"\g<1>%s\g<2>" % html.escape(title), text, count=1)
    text = re.sub(r'(<dc:identifier[^>]*id="[^"]*"[^>]*>)[^<]*(</dc:identifier>)',
                  r"\g<1>%s\g<2>" % newid, text, count=1)
    return text


NCX_LABEL = re.compile(r"(<navLabel>\s*<text>)([^<]*)(</text>)")


def patch_ncx(text, lang, title, tmap):
    """tmap: {原文标签: 译文}，不动结构只换字。"""
    text = re.sub(r'(<ncx[^>]*xml:lang=")eng(")', r"\g<1>%s\g<2>" % lang, text, count=1)
    text = re.sub(r"(<docTitle>\s*<text>)[^<]*(</text>)",
                  r"\g<1>%s\g<2>" % html.escape(title), text, count=1)

    def sub(m):
        src = html.unescape(m.group(2)).strip()
        val = plain_label(tmap.get(src, src)) or src     # 兜底：目录里绝不出现标签
        return m.group(1) + html.escape(val) + m.group(3)

    return NCX_LABEL.sub(sub, text)


A_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
BLOCK_TEXT_RE = re.compile(
    r"<(h[1-6]|p|dt|dd|li|figcaption|blockquote|summary)\b[^>]*>([^<]*)</\1\s*>", re.I | re.S)
NAV_OPEN_RE = re.compile(r"<nav\b[^>]*>", re.I)
NAV_ANY_RE = re.compile(r"<nav\b[^>]*>|</nav\s*>", re.I)


def _toc_nav_span(raw):
    """定位 toc nav 元素的内容区间（起，止）；找不到返回 None。"""
    pick = None
    for m in NAV_OPEN_RE.finditer(raw):
        if re.search(r'(?:epub:)?type\s*=\s*["\']?toc\b', m.group(0), re.I):
            pick = m
            break
        if pick is None:
            pick = m
    if pick is None:
        return None
    depth, pos = 1, pick.end()
    while True:
        m = NAV_ANY_RE.search(raw, pos)
        if not m:
            return (pick.end(), len(raw))
        if m.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        pos = m.end()
        if depth == 0:
            return (pick.end(), m.start())


def _nav_spans(raw, navspan):
    """目录里所有可替换的文字位置。

    两类：toc nav 内每个 <a> 的文字，以及 nav 之外孤立的标题/段落（如 "Contents"）。
    """
    out = []

    def add(start, end, raw_text):
        out.append({"start": start, "end": end,
                    "text": html.unescape(raw_text).strip() if "<" not in raw_text else None})

    if navspan:
        for m in A_RE.finditer(raw, navspan[0], navspan[1]):
            add(m.start(1), m.end(1), m.group(1))
    for m in BLOCK_TEXT_RE.finditer(raw):
        if navspan and navspan[0] <= m.start(2) <= navspan[1]:
            continue
        add(m.start(2), m.end(2), m.group(2))
    return out


def plain_label(s):
    """把译文压成纯文本，专给目录标签用。

    目录标签（ncx 的 <text>、nav 里 <a> 的文字）只能是纯文本。
    但"复用正文译文"拿到的可能是一整段 HTML（正文里的目录页就是
    `<a href="...">Dedication</a>` 这种），直接写进去会被转义成源码，
    读者面板里显示成 &lt;a href=...&gt;。2026-10-22 踩过。

    这里依次去掉：注音标记 {表記|よみ}、<rt>/<rp>、其余标签，再反转义。
    """
    if not s:
        return ""
    s = re.sub(r"<rt\b[^>]*>.*?</rt\s*>", "", s, flags=re.S | re.I)
    s = re.sub(r"<rp\b[^>]*>.*?</rp\s*>", "", s, flags=re.S | re.I)
    s = re.sub(r"\{([^{}|]*)\|[^{}|]*\}", r"\1", s)      # {献辞|けんじ} → 献辞
    s = re.sub(r"\{[\u3040-\u309f\u30a0-\u30ffー]+\}", "", s)   # 会話{かいわ} → 会話
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def collect_toc(book):
    """读出书里所有导航文件的目录条目，去重后返回待译清单。"""
    plan = {"ncx": None, "nav": None, "labels": []}
    ncx_path = None
    for root, _d, fs in os.walk(book.srcdir):
        for f in fs:
            if f.lower().endswith(".ncx"):
                ncx_path = os.path.join(root, f)
                break
        if ncx_path:
            break
    if ncx_path:
        text = open(ncx_path, encoding="utf-8", errors="replace").read()
        labels = [html.unescape(x).strip() for x in
                  re.findall(r"<navLabel>\s*<text>([^<]*)</text>", text)]
        plan["ncx"] = {"path": ncx_path, "text": text, "labels": labels}

    if book.nav_doc:
        p = book.doc_path(book.nav_doc)
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="replace").read()
            spans = _nav_spans(text, _toc_nav_span(text))
            plan["nav"] = {"path": p, "text": text, "spans": spans,
                           "labels": [s["text"] for s in spans if s["text"]]}

    seen, labels = set(), []
    for src in ("nav", "ncx"):
        node = plan.get(src)
        if not node:
            continue
        for s in node["labels"]:
            if s and s not in seen:
                seen.add(s)
                labels.append(s)
    plan["labels"] = labels
    return plan


def patch_nav(raw, spans, tmap):
    """按位置替换文字，一个字节的标签都不动。"""
    out, last = [], 0
    for sp in sorted(spans, key=lambda x: x["start"]):
        if sp["start"] < last or not sp["text"]:
            continue
        new = plain_label(tmap.get(sp["text"], sp["text"])) or sp["text"]
        out.append(raw[last:sp["start"]])
        out.append(html.escape(new))
        last = sp["end"]
    out.append(raw[last:])
    return "".join(out)


def package(builddir, outpath):
    if os.path.exists(outpath):
        os.remove(outpath)
    files = []
    for root, _dirs, fs in os.walk(builddir):
        for f in fs:
            files.append(os.path.relpath(os.path.join(root, f), builddir).replace("\\", "/"))
    files.sort(key=lambda x: (x != "mimetype",))
    os.makedirs(os.path.dirname(os.path.abspath(outpath)) or ".", exist_ok=True)
    with zipfile.ZipFile(outpath, "w") as z:
        if "mimetype" in files:
            z.write(os.path.join(builddir, "mimetype"), "mimetype", compress_type=zipfile.ZIP_STORED)
        for f in files:
            if f == "mimetype":
                continue
            z.write(os.path.join(builddir, f), f, compress_type=zipfile.ZIP_DEFLATED)
    return outpath


def new_uuid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
