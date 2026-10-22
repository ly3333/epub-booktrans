# -*- coding: utf-8 -*-
"""命令行入口。"""
import argparse
import json
import os
import re
import shutil
import sys
import time

from . import __version__
from . import config as C
from . import epub as E
from . import translate as T
from . import validate as V


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _human(sec):
    """秒数 → 人话。"""
    sec = max(0.0, float(sec))
    if sec < 60:
        return "%.0f 秒" % sec
    m, s = divmod(int(sec), 60)
    if m < 60:
        return "%d 分 %02d 秒" % (m, s)
    h, m = divmod(m, 60)
    return "%d 小时 %02d 分" % (h, m)


def _logger(logdir):
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, "run-%s.log" % time.strftime("%Y%m%d-%H%M%S"))
    fh = open(path, "a", encoding="utf-8")

    def log(msg):
        line = str(msg)
        print(line)
        fh.write(line + "\n")
        fh.flush()

    log.path = path
    return log


def _book_id(path):
    st = os.stat(path)
    seed = "%s|%d|%d" % (os.path.abspath(path), st.st_size, int(st.st_mtime))
    return T.digest(seed)


def _dc_title(opf_text):
    import re
    m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf_text, re.S)
    return E.html.unescape(m.group(1)).strip() if m else ""


def cmd_doctor(args):
    _utf8()
    cfg = C.load_config(args.config)
    print("booktrans   : %s" % __version__)
    print("Python      : %s" % sys.version.split()[0])
    print("工具目录    : %s" % cfg["_root"])
    print("配置文件    : %s %s" % (cfg["_config_path"], "（存在）" if os.path.exists(cfg["_config_path"]) else "（缺失，运行 init 生成）"))
    for mod in ("bs4", "lxml", "requests"):
        try:
            __import__(mod)
            print("依赖        : %-8s OK" % mod)
        except Exception:
            print("依赖        : %-8s 缺失%s" % (mod, "（lxml 可选）" if mod == "lxml" else ""))
    key = (cfg.get("api_key") or "").strip()
    print("API Key     : %s" % ("已配置 ****" + key[-4:] if key and "在这里填" not in key else "未配置"))
    print("模型        : %s @ %s" % (cfg.get("model"), cfg.get("base_url")))
    print("并发 / 分片 : %s / %s 词" % (cfg.get("concurrency"), cfg.get("words_per_chunk")))
    g = C.load_glossary(cfg.get("glossary"))
    print("术语表      : %d 条" % len(g))
    for d in ("out", "cache", "logs"):
        ok = os.access(os.path.join(cfg["_root"], d), os.W_OK)
        print("目录 %-6s : %s" % (d, "可写" if ok else "不可写"))
    return 0


def cmd_init(args):
    _utf8()
    p = C.ensure_default_config()
    g = C.ROOT / "glossary.txt"
    if not g.exists():
        ex = C.ROOT / "glossary.example.txt"
        if ex.exists():
            g.write_text(ex.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            g.write_text(
                "# 术语表：一行一条，格式   English = 中文 | 日本語\n"
                "# 只写中文也行。以 # 开头是注释。\n"
                "difficult conversation = 艰难的对话 | 難しい会話\n"
                "boundaries = 边界 | 境界線\n",
                encoding="utf-8")
    print("已生成：%s" % p)
    print("请填好 api_key 后运行： booktrans doctor")
    return 0


def cmd_make(args):
    _utf8()
    cfg = C.load_config(args.config)
    for k, v in (("concurrency", args.concurrency), ("words_per_chunk", args.words),
                 ("provider", args.provider), ("base_url", args.base_url),
                 ("model", args.model), ("api_key", args.api_key), ("retries", args.retries)):
        if v:
            cfg[k] = v
    if args.replay_dir:
        cfg["provider"] = "replay"
        cfg["replay_dir"] = args.replay_dir
    if getattr(args, "keep_styles", False):
        cfg["keep_inline_styles"] = True
    langs = [x.strip() for x in (args.lang or "zh,ja").split(",") if x.strip()]
    if args.book.lower().endswith(".pdf"):
        print("这个工具只吃 EPUB。PDF 是版面坐标、没有段落和锚点，转出来会丢行内强调和脚注跳转。")
        print("两条路：")
        print("  1) 先用 Calibre 转：ebook-convert 书.pdf 书.epub   然后 booktrans make 书.epub")
        print("  2) 用 pymupdf4llm 之类转 Markdown，再打成 EPUB")
        print("详见 README「为什么只支持 EPUB」。")
        return 2
    if args.furigana == "off":
        cfg["furigana"] = "off"
    elif args.furigana == "fill":
        cfg["furigana"] = "fill"
        from . import furigana as FG
        if not FG.available():
            log0 = print
            log0("！没装 fugashi / unidic-lite，补标不可用。先运行：.venv\\Scripts\\pip install fugashi unidic-lite")
            return 2
    log = _logger(os.path.join(cfg["_root"], "logs"))
    t_all = time.time()
    log("=== booktrans %s ===" % time.strftime("%Y-%m-%d %H:%M:%S"))
    log("输入：%s" % os.path.abspath(args.book))
    log("目标语言：%s   provider=%s   model=%s" % (",".join(langs), cfg.get("provider"), cfg.get("model")))

    book = E.EpubBook(args.book)
    try:
        docs = E.extract_docs(book, keep_styles=cfg.get("keep_inline_styles", True))
        units = []
        for d in docs:
            base = os.path.basename(d["href"])
            for uid, m in d["meta"].items():
                units.append({"file": base, "uid": uid, "en": m["en"]})
        plan = E.collect_toc(book)
        words = sum(E.wc(u["en"]) for u in units)
        log("解析：%d 个文档，%d 个段落单元，%d 英文词" % (len(docs), len(units), words))
        log("导航：%s" % (" + ".join(
            "%s(%d 条)" % (k.upper(), len(plan[k]["labels"]))
            for k in ("nav", "ncx") if plan.get(k)) or "无"))
        if plan["labels"]:
            log("目录待译条目：%d 条（nav / ncx 重复的已去重）" % len(plan["labels"]))
        if not units:
            log("！这本书没有可译文本（可能全是图片），退出。")
            return 2

        if args.dry_run:
            est = {"zh": (words * 2.2, 2.6), "ja": (words * 3.6, 2.6)}
            total_out = 0
            for l in langs:
                out_tok = est.get(l, (words * 3, 3))[0]
                total_out += out_tok
                log("  [%s] 预计输出约 %.0f 万 token" % (l, out_tok / 10000))
            pin = cfg.get("price_in_per_mtok") or 0
            pout = cfg.get("price_out_per_mtok") or 0
            if pin or pout:
                cost = total_out / 1e6 * pout + words * 1.5 * len(langs) / 1e6 * pin
                log("  按当前单价估算：约 %.2f 元/美元（取决于你配置的币种）" % cost)
            log("干跑结束，未调用 API。去掉 --dry-run 开始翻译。")
            return 0

        os.makedirs(args.out, exist_ok=True)
        cache = T.Cache(os.path.join(cfg["_root"], "cache", "cache.sqlite"))
        book_id = _book_id(args.book)
        base_title = _dc_title(book.opf_text)
        gloss = C.load_glossary(cfg.get("glossary"))
        gtext = ""
        if gloss:
            gtext = "统一译名（必须遵守）：\n" + "\n".join(
                "- %s → %s" % (k, v.get("ja") or v.get("zh")) for k, v in list(gloss.items())[:200])
        if cfg.get("style_notes"):
            gtext += "\n\n文风补充：\n" + cfg["style_notes"]

        results = {}
        for lang in langs:
            log("")
            log("--- %s ---" % lang)
            tr = T.translate_units(units, lang, cfg, cache, book_id, log=log, extra=gtext)
            miss = sum(1 for u in units if u["uid"] not in tr.get(u["file"], {}))
            got = sum(len(v) for v in tr.values())
            log("  [%s] 完成 %d/%d 段%s" % (lang, got, len(units),
                                          "，%d 段保留英文" % miss if miss else ""))
            title = getattr(args, "title_" + lang, None) or base_title
            # 正文已经译过的句子，目录里照抄，不再花 token。
            # 目录条目是纯文本，正文单元可能带 <span class> 标记，
            # 所以除了原文，再存一份「去掉标签后」的键用于匹配。
            seen = {}
            for u in units:
                v = tr.get(u["file"], {}).get(u["uid"])
                if not v:
                    continue
                seen.setdefault(u["en"].strip(), v)
                plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", u["en"])).strip()
                if plain:
                    seen.setdefault(plain, v)
            labels = plan["labels"]
            lm = T.translate_labels(labels, lang, cfg, log=log, seen=seen) if labels else {}
            if lang in ("zh", "ja") and not getattr(args, "title_" + lang, None):
                tm = T.translate_labels([title], lang, cfg, seen=seen)
                title = tm.get(title) or title
            results[lang] = (tr, title, lm)

        for lang in langs:
            tr, title, lm = results[lang]
            build = os.path.join(cfg["_root"], "cache", "build_%s_%s" % (book_id[:8], lang))
            if os.path.exists(build):
                shutil.rmtree(build)
            shutil.copytree(book.srcdir, build)
            build_opfdir = os.path.join(build, os.path.relpath(book.opfdir, book.srcdir))
            for d in docs:
                rel = os.path.relpath(d["path"], book.srcdir)
                out = os.path.join(build, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                text = E.render_doc(d, tr.get(os.path.basename(d["href"]), {}), lang, cfg, title,
                                    fill_furigana=(cfg.get("furigana") == "fill"))
                open(out, "w", encoding="utf-8").write(E.set_doc_lang(text, lang))
            opf_out = os.path.join(build, os.path.relpath(book.opf_path, book.srcdir))
            open(opf_out, "w", encoding="utf-8").write(
                E.patch_opf(book.opf_text, lang, title, E.new_uuid("booktrans:" + book_id + ":" + lang)))
            if plan.get("ncx"):
                out = os.path.join(build, os.path.relpath(plan["ncx"]["path"], book.srcdir))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                open(out, "w", encoding="utf-8").write(
                    E.patch_ncx(plan["ncx"]["text"], lang, title, lm))
            if plan.get("nav"):
                out = os.path.join(build, os.path.relpath(plan["nav"]["path"], book.srcdir))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                t = E.patch_nav(plan["nav"]["text"], plan["nav"]["spans"], lm)
                if plan["nav"]["path"].lower().endswith(E.DOC_EXT):
                    t = E.set_doc_lang(t, lang)
                open(out, "w", encoding="utf-8").write(t)
            added = E.ensure_extra_css(build, book.css_hrefs, build_opfdir)
            if added:
                log("  [%s] 已给 %d 个 CSS 追加 bt-* / ruby 规则" % (lang, len(added)))
            stem = os.path.splitext(os.path.basename(args.book))[0]
            out_path = os.path.join(args.out, "%s-%s.epub" % (stem, lang))
            E.package(build, out_path)
            log("")
            log("产出：%s" % out_path)
            rep = V.check_dir(build, lang)
            for line in V.format_report(rep, lang).splitlines():
                log("  " + line)
            if rep["xml_errors"] or rep["dead_links"]:
                log("  ！仍有问题，见 logs 目录")
            shutil.rmtree(build, ignore_errors=True)   # 中间产物不留在磁盘上
        log("")
        log("全部完成。输出目录：%s" % os.path.abspath(args.out))
        log("总耗时：%s（含解析、翻译、回填、校验、打包）" % _human(time.time() - t_all))
        log("日志：%s" % log.path)
        return 0
    finally:
        book.close()


def cmd_validate(args):
    _utf8()
    lang = args.lang or "ja"
    rep = V.check_epub(args.file, lang)
    print(V.format_report(rep, lang))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="booktrans", description="英文书 → 中文 / 日文 EPUB（含假名标注）")
    ap.add_argument("--version", action="version", version="booktrans %s" % __version__)
    sub = ap.add_subparsers(dest="cmd")

    m = sub.add_parser("make", help="翻译一本书")
    m.add_argument("book")
    m.add_argument("--lang", default="zh,ja", help="目标语言，逗号分隔，默认 zh,ja")
    m.add_argument("--out", default=str(C.ROOT / "out"))
    m.add_argument("--concurrency", type=int)
    m.add_argument("--words", type=int, help="每个分片的英文词数")
    m.add_argument("--provider", choices=["openai", "mock", "replay"])
    m.add_argument("--base-url")
    m.add_argument("--model")
    m.add_argument("--api-key")
    m.add_argument("--retries", type=int)
    m.add_argument("--furigana", choices=["llm", "fill", "off"], default="llm",
                   help="llm=译文里标音（默认）；fill=再用 MeCab 补标漏掉的；off=不标")
    m.add_argument("--glossary")
    m.add_argument("--keep-styles", action="store_true",
                   help="连原书的行内配色/字号 class 也保留（默认只保留斜体粗体等语义样式）")
    m.add_argument("--config")
    m.add_argument("--replay-dir", help=argparse.SUPPRESS)
    m.add_argument("--dry-run", action="store_true", help="只统计不翻译")
    m.add_argument("--title-zh")
    m.add_argument("--title-ja")
    m.set_defaults(func=cmd_make)

    v = sub.add_parser("validate", help="校验成品 epub")
    v.add_argument("file")
    v.add_argument("--lang", default="ja")
    v.set_defaults(func=cmd_validate)

    d = sub.add_parser("doctor", help="环境自检")
    d.add_argument("--config")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("init", help="生成配置模板")
    i.set_defaults(func=cmd_init)
    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    return args.func(args) or 0
