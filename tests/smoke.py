# -*- coding: utf-8 -*-
"""一键自测：造书 → mock 翻译 → 校验 → 结构对比 → 再跑一次验证缓存命中。

跑的是「零成本、零网络」的断言，任何一台装好依赖的机器都能复现：
  [1] 流水线跑通
  [2] EPUB3 nav 目录被翻译，且 <ol>/<li>/<a href> 一个不少
  [3] EPUB2 ncx 目录被翻译
  [4] 原书格式保住：<br> 行数、<pre> 缩进、斜体/小型大写/等宽、脚注锚点、lang 属性
  [5] XML / 断链 / 缺图 全部为 0
  [6] 重跑命中缓存（断点续译）
  [7] PDF 被拦下

用法： .venv\\Scripts\\python.exe tests\\smoke.py
"""
import contextlib
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from booktrans import cli, validate  # noqa: E402
from booktrans import epub as E  # noqa: E402
import make_fixture  # noqa: E402

OUT = os.path.join(ROOT, "out", "_smoke")
FIX = os.path.join(ROOT, "cache", "fixture.epub")
SRC = make_fixture._chapter(True)

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    return ok


def run(argv):
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["booktrans"] + argv
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.main()
    finally:
        sys.argv = old
    return rc or 0, buf.getvalue()


def read_epub(path):
    d = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            d[n] = z.read(n).decode("utf-8", errors="replace")
    return d


def main():
    os.makedirs(OUT, exist_ok=True)
    make_fixture.build(FIX)
    log = []

    rc, out = run(["make", FIX, "--provider", "mock", "--lang", "zh,ja",
                   "--out", OUT, "--concurrency", "4"])
    check("[1] 流水线跑通", rc == 0, "rc=%d" % rc)

    for lang in ("zh", "ja"):
        cands = [f for f in os.listdir(OUT) if f.endswith("-%s.epub" % lang)]
        if not cands:
            check("产出 %s" % lang, False, "没有文件")
            continue
        files = read_epub(os.path.join(OUT, cands[0]))
        rep = validate.check_epub(os.path.join(OUT, cands[0]), lang)
        check("[5-%s] XML/断链/缺图全 0" % lang,
              not (rep["xml_errors"] or rep["dead_links"] or rep["missing_images"]),
              validate.format_report(rep, lang).replace("\n", " | "))

        navsrc = SRC["OEBPS/nav.xhtml"]
        navout = next((v for k, v in files.items() if k.endswith("nav.xhtml")), "")
        if not navout:
            check("[2-%s] nav.xhtml 存在" % lang, False)
        else:
            labels = re.findall(r"<a\b[^>]*>([^<]*)</a>", navsrc)
            hit = 0
            for lab in labels:
                new = re.findall(r"<a\b[^>]*>([^<]*)</a>", navout)
                if any(lab.strip() and lab.strip() in x and x != lab for x in new):
                    hit += 1
            check("[2-%s] EPUB3 nav 目录已翻译" % lang, hit >= 3,
                  "%d/%d 条" % (hit, len(labels)))
            # 结构一个字节都不能少
            struct = {t: navsrc.count(t) for t in ("<ol>", "<li>", "<a ", "</nav>", "<nav ")}
            struct2 = {t: navout.count(t) for t in struct}
            check("[2-%s] nav 结构未变形" % lang, struct == struct2,
                  "源 %s vs 产出 %s" % (struct, struct2))
            hrefs = re.findall(r'href="([^"]+)"', navsrc)
            hrefs2 = re.findall(r'href="([^"]+)"', navout)
            check("[2-%s] nav 链接未改写" % lang, hrefs == hrefs2,
                  "源 %s vs 产出 %s" % (hrefs, hrefs2))

        ncx = next((v for k, v in files.items() if k.lower().endswith(".ncx")), "")
        if ncx:
            labs = re.findall(r"<navLabel>\s*<text>([^<]*)</text>", ncx)
            changed = [x for x in labs if x.startswith("【%s】" % lang)]
            check("[3-%s] EPUB2 ncx 目录已翻译" % lang, len(changed) >= 2,
                  "%d/%d 条：%s" % (len(changed), len(labs), labs[:2]))

        c1 = next((v for k, v in files.items() if k.endswith("ch1.xhtml")), "")
        c2 = next((v for k, v in files.items() if k.endswith("ch2.xhtml")), "")
        src1, src2 = SRC["OEBPS/ch1.xhtml"], SRC["OEBPS/ch2.xhtml"]
        check("[4-%s] 诗歌 <br> 行数保留" % lang,
              c1.count("<br/>") == src1.count("<br/>"),
              "源 %d vs 产出 %d" % (src1.count("<br/>"), c1.count("<br/>")))
        pre = re.search(r"<pre[^>]*>(.*?)</pre>", c2, re.S)
        presrc = re.search(r"<pre[^>]*>(.*?)</pre>", src2, re.S)
        check("[4-%s] 代码块缩进保留" % lang,
              bool(pre) and bool(presrc) and pre.group(1).count("\n") == presrc.group(1).count("\n"),
              "换行数 源 %s vs 产出 %s" % (presrc.group(1).count("\n") if presrc else "?",
                                        pre.group(1).count("\n") if pre else "?"))
        check("[4-%s] 斜体/粗体/等宽仍在" % lang,
              ("bt-i" in c1 or "bt-i" in c2) and ("bt-b" in c2 or "<b>" in c2) and "bt-tt" in c2,
              "i=%s b=%s tt=%s" % ("bt-i" in c1 + c2, "bt-b" in c2, "bt-tt" in c2))
        check("[4-%s] 小型大写保留" % lang, "bt-sc" in c2, "")
        check("[4-%s] 脚注锚点与跳转保留" % lang,
              c1.count('id="fn1"') == src1.count('id="fn1"') and c1.count('href="#fn1"') == src1.count('href="#fn1"'),
              "锚点 %d/%d 跳转 %d/%d" % (c1.count('id="fn1"'), src1.count('id="fn1"'),
                                      c1.count('href="#fn1"'), src1.count('href="#fn1"')))
        check("[4-%s] lang 属性已标注" % lang,
              ('lang="%s"' % lang) in c1 and ("xml:lang=\"%s\"" % lang) in c1, c1[:120])
        css = next((v for k, v in files.items() if k.endswith(".css")), "")
        check("[4-%s] ruby / bt-* 兜底 CSS 已注入" % lang,
              "bt-i" in css and "ruby" in css, "")
        # 2026-10-22 的回归：给 ruby 写 display:inline 会把注音排版整个关掉，
        # <rt> 退化成普通行内文字，假名直接接在汉字后面（重要じゅうよう）。
        flat = css.replace(" ", "").replace("\n", "")
        check("[4-%s] 兜底 CSS 不得破坏 ruby 布局" % lang,
              "ruby{display:inline" not in flat and "ruby{display:inline}" not in flat,
              "命中 display:inline 的 ruby 规则" if "ruby{display:inline" in flat else "OK")

    # [8] 注音单元本身：必须是 ruby + rt，并且带 rp 降级括号
    r = E.to_ruby("重要", "じゅうよう")
    check("[8] to_ruby 产出 ruby/rt/rp",
          "<rt>じゅうよう</rt>" in r and "<rp>" in r and r.startswith("<ruby>"), r)
    r2 = E.to_ruby("引き裂く", "ひきさく")
    check("[8] 送り仮名留在 ruby 外",
          r2.count("<ruby>") == 2 and "く" in r2.split("</ruby>")[-1], r2)
    check("[8] 兜底 CSS 不含 display:inline",
          "display:inline" not in re.sub(r"/\*.*?\*/", "", E.FALLBACK_CSS, flags=re.S).replace(" ", ""),
          "")

    rc, out = run(["make", FIX, "--provider", "mock", "--lang", "zh,ja",
                   "--out", OUT, "--concurrency", "4"])
    hit_lines = [l for l in out.splitlines() if "缓存命中" in l]
    check("[6] 重跑全命中缓存",
          bool(hit_lines) and not any("命中 0" in h for h in hit_lines),
          " / ".join(hit_lines))

    rc, out = run(["make", FIX.replace(".epub", ".pdf")])
    check("[7] PDF 拦截", rc == 2, "rc=%d" % rc)

    ok = all(c[1] for c in CHECKS)
    lines = ["测试结果：%s" % ("全部通过" if ok else "有失败项")]
    for name, good, detail in CHECKS:
        lines.append("  %s %s%s" % ("OK  " if good else "FAIL", name,
                                    ("  → " + detail) if (detail and (not good or True)) else ""))
    lines.append("")
    lines.append("（完整运行日志见 logs/smoke.txt）")
    text = "\n".join(lines)
    open(os.path.join(ROOT, "logs", "smoke.txt"), "w", encoding="utf-8").write(text)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
