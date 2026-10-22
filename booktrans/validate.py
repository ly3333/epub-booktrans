# -*- coding: utf-8 -*-
"""成品校验：XML 合法性、内链可达、图片齐全、假名覆盖。"""
import os
import re
import zipfile

CJK = re.compile(r"[\u4e00-\u9fff]")


def _parser():
    try:
        from lxml import etree
        return etree.XMLParser(recover=False, resolve_entities=False, load_dtd=False, no_network=True), "lxml"
    except Exception:
        return None, "etree"


def check_dir(builddir, lang):
    rep = {"xml_errors": [], "dead_links": [], "missing_images": [], "ruby": 0,
           "kanji_total": 0, "kanji_bare": 0, "files": 0, "chars": 0}
    parser, kind = _parser()
    pages = []
    for root, _d, fs in os.walk(builddir):
        for f in fs:
            if f.lower().endswith((".html", ".xhtml", ".htm")):
                pages.append(os.path.join(root, f))
    ids = {}
    bodies = {}
    for p in pages:
        raw = open(p, encoding="utf-8", errors="replace").read()
        bodies[p] = raw
        for m in re.finditer(r'\bid="([^"]+)"', raw):
            ids.setdefault(m.group(1), p)
        if raw.lstrip().startswith("<?xml"):
            ok = True
            try:
                if kind == "lxml":
                    __import__("lxml.etree", fromlist=["etree"]).fromstring(raw.encode("utf-8"), parser)
                else:
                    import xml.etree.ElementTree as ET
                    ET.fromstring(raw.encode("utf-8"))
            except Exception as e:
                ok = False
                rep["xml_errors"].append("%s: %s" % (os.path.basename(p), str(e)[:100]))
            if ok:
                rep["files"] += 1
        else:
            rep["files"] += 1

    for p, raw in bodies.items():
        base = os.path.dirname(p)
        for m in re.finditer(r'(?:href|src)="([^"]+)"', raw):
            u = m.group(1)
            if u.startswith(("http:", "https:", "mailto:", "data:", "#")):
                if u.startswith("#") and u[1:] and u[1:] not in ids:
                    rep["dead_links"].append((os.path.basename(p), u))
                continue
            path = u.split("#", 1)[0]
            frag = u.split("#", 1)[1] if "#" in u else ""
            target = os.path.normpath(os.path.join(base, path))
            if not os.path.exists(target):
                (rep["missing_images"] if m.group(0).startswith("src=") else rep["dead_links"]).append(
                    (os.path.basename(p), u))
            elif frag and frag not in ids:
                rep["dead_links"].append((os.path.basename(p), u))
        rep["ruby"] += raw.count("<ruby>")
        txt = re.sub(r"<rt>.*?</rt>", "", raw, flags=re.S)
        txt = re.sub(r"<[^>]+>", "", txt)
        rep["chars"] += len(re.sub(r"\s", "", txt))
        if lang == "ja":
            plain = re.sub(r"<ruby>(.*?)<rt>.*?</rt></ruby>", "", raw, flags=re.S)
            plain = re.sub(r"<[^>]+>", "", plain)
            rep["kanji_total"] += len(CJK.findall(txt))
            rep["kanji_bare"] += len(CJK.findall(plain))
    return rep


def check_epub(path, lang):
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="booktrans_chk_")
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(d)
        return check_dir(d, lang)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def format_report(rep, lang):
    lines = []
    lines.append("文件数 %d，正文 %s 字" % (rep["files"], format(rep["chars"], ",")))
    lines.append("XML 错误 %d，断链 %d，缺图 %d" % (len(rep["xml_errors"]), len(rep["dead_links"]), len(rep["missing_images"])))
    if lang == "ja":
        tot, bare = rep["kanji_total"], rep["kanji_bare"]
        cov = 100.0 * (tot - bare) / tot if tot else 0
        lines.append("汉字 %s 个，未标假名 %s 个（覆盖 %.1f%%），ruby 标签 %d 个"
                     % (format(tot, ","), format(bare, ","), cov, rep["ruby"]))
    for x in rep["xml_errors"][:5]:
        lines.append("  XML  " + x)
    for x in rep["dead_links"][:5]:
        lines.append("  断链  %s -> %s" % x)
    for x in rep["missing_images"][:5]:
        lines.append("  缺图  %s -> %s" % x)
    return "\n".join(lines)
