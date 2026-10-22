# -*- coding: utf-8 -*-
"""生成一本用于自测的迷你 EPUB3（两章 + EPUB3 nav 目录 + EPUB2 ncx 双导航）。

内含：图片、脚注锚点、首字下沉、CSS 定义的斜体/小型大写/等宽、
诗歌换行 <br>、代码块 <pre>、原生 <em>/<strong>/<code>/<sup>。
不依赖任何受版权保护的书，可以随仓库分发。
用法： .venv\\Scripts\\python.exe tests\\make_fixture.py [输出路径]
"""
import base64
import os
import sys
import tempfile
import zipfile

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M/wHwAEAAH/7S0Z9AAAAABJRU5ErkJggg==")


def _chapter(style):
    files = {}

    files["mimetype"] = "application/epub+zip"
    files["META-INF/container.xml"] = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

    files["OEBPS/content.opf"] = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>Slower Conversations</dc:title><dc:language>en</dc:language>
<dc:creator>Jane Sample</dc:creator>
<dc:identifier id="uid">urn:uuid:test-fixture-0001</dc:identifier>
<meta property="dcterms:modified">2020-01-01T00:00:00Z</meta>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
<item id="im1" href="img/dot.png" media-type="image/png"/>
</manifest>
<spine>
<itemref idref="c1"/><itemref idref="c2"/>
</spine>
</package>"""

    files["OEBPS/toc.ncx"] = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="eng">
<head><meta name="dtb:uid" content="test-fixture-0001"/></head>
<docTitle><text>Slower Conversations</text></docTitle>
<navMap>
<navPoint id="n1" playOrder="1"><navLabel><text>Chapter One: The Pause</text></navLabel><content src="ch1.xhtml"/></navPoint>
<navPoint id="n2" playOrder="2"><navLabel><text>Chapter Two: The Question</text></navLabel><content src="ch2.xhtml"/></navPoint>
</navMap></ncx>"""

    # EPUB3 目录：故意用两层嵌套 + 一个与正文标题完全相同的条目（用来验证「复用正文译文」）
    files["OEBPS/nav.xhtml"] = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<h1>Table of Contents</h1>
<nav epub:type="toc" id="toc">
  <ol>
    <li><a href="ch1.xhtml">Chapter One: The Pause</a>
      <ol><li><a href="ch1.xhtml#poem">A Short Poem</a></li></ol>
    </li>
    <li><a href="ch2.xhtml">Chapter Two: The Question</a></li>
  </ol>
</nav>
<nav epub:type="landmarks"><ol><li><a href="ch1.xhtml">Start of Content</a></li></ol></nav>
<p>Cover image follows.</p>
</body></html>"""

    files["OEBPS/style.css"] = """body{font-family:serif;line-height:1.6}
p{margin:0 0 .8em;text-indent:1em}
h1{font-size:1.4em}
.ital{font-style:italic}
.sc{font-variant:small-caps}
.drop{float:left;font-size:2.4em;line-height:.9;padding-right:.05em}
.mono-block{font-family:monospace;white-space:pre}
.note{font-size:.75em;vertical-align:super}
"""

    files["OEBPS/ch1.xhtml"] = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Slower Conversations</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head><body>
<h1 id="c1">Chapter One: The Pause</h1>
<p class="first"><span class="drop">T</span>he first rule is not to answer at once. Silence is not a weapon; it is a door.<a id="fn1"></a></p>
<p>When my father asked me a hard question, he waited. He waited so long that I heard the clock in the hall.</p>
<p><span class="ital">Wait three seconds.</span> That is all. Then say the true thing.</p>
<div id="poem">
<p>Do not fill the room.<br/>Let it breathe.<br/>Then answer.</p>
</div>
<blockquote><p>&ldquo;I need a moment to think about that.&rdquo;<sup class="note"><a href="#fn1">1</a></sup></p></blockquote>
<p><img src="img/dot.png" alt="dot"/></p>
<p>Most people fill the silence with an apology. Don&rsquo;t.</p>
</body></html>"""

    files["OEBPS/ch2.xhtml"] = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Slower Conversations</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head><body>
<h1 id="c2">Chapter Two: The Question</h1>
<p>The second rule is to ask before you argue. <strong>Ask, then listen.</strong></p>
<p>My sister once said, <em>&ldquo;You are not listening, you are reloading.&rdquo;</em> She was right.</p>
<p><span class="sc">Chapter preview</span> — the rest is silence.</p>
<pre class="mono-block">def wait(seconds=3):
    if seconds &lt; 1:
        raise ValueError
    return seconds
</pre>
<p>Then, and only then, answer. Use <code>wait(3)</code> before you speak.</p>
</body></html>"""

    if style:
        files["OEBPS/img/dot.png"] = PNG_1X1
    return files


def build(out):
    files = _chapter(True)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", files.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
        for k, v in files.items():
            z.writestr(k, v, compress_type=zipfile.ZIP_DEFLATED)
    return out


def source_map(out):
    """把 fixture 展开到临时目录，方便自测做「结构对比」。"""
    d = tempfile.mkdtemp(prefix="booktrans_fix_")
    build(out)
    with zipfile.ZipFile(out) as z:
        z.extractall(d)
    return d


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "fixture.epub"
    print(build(target))
