# booktrans

Translate an English EPUB into **Chinese** and **Japanese (with full furigana)** while keeping the
original layout, images, footnote links and table of contents intact.

Windows-first, double-click friendly. The goal is not "machine translation you can skim" —
it is **a translated book you can actually read and print**.

> 中文说明见 [README.md](README.md)。

---

## Why another EPUB translator?

Plenty of tools already translate EPUBs (`bilingual_book_maker`, Calibre plugins, `epub_furigana`…).
This one exists for a single reason: **treat layout fidelity as a first-class requirement**, not a
side effect of translation.

Where that shows up in practice:

| | Typical behaviour | This tool |
|---|---|---|
| Footnote / index links | Whole block replaced, `<a href>` silently lost, links dead at the end of the book | Anchors and links migrated one by one; the build validates every link |
| Inline styling | Matches a fixed class name like `.italic`; a different publisher means zero italics | **Parses the book's CSS**: `font-style:italic` means italic, whatever the class is called |
| Poetry / code | `<br>` collapsed into a space, `<pre>` indentation flattened | Line breaks and indentation preserved **byte for byte** |
| Japanese furigana | None, or whole-word blobs like `古い(ふるい)` | Per-kanji ruby, okurigana kept outside: `古(ふる)い`, `擦(す)り切(き)れた` |
| Table of contents | Only EPUB2 `toc.ncx`; EPUB3 books keep an English TOC | Both `nav.xhtml` and `toc.ncx`, worded consistently with the body |

---

## Features

- **Paragraph-aligned translation** — one source paragraph in, one translated paragraph out
- **Layout untouched by default** — classes, drop caps, page breaks, image positions preserved;
  no bilingual side-by-side, no translator's notes
- **TOC translated** — EPUB3 `nav.xhtml` + EPUB2 `toc.ncx`, deduplicated and translated once
- **Resumable** — per-paragraph SQLite cache; a crash never re-bills finished work
- **Self-validating** — XML well-formedness, dead links, missing images, furigana coverage
- **Three furigana modes** — `llm` (≈96.5%), `fill` (MeCab, 99.9%), `off`
- **Vendor-neutral** — any OpenAI-compatible endpoint (DeepSeek, Moonshot, Ollama, vLLM…)
- **Almost dependency-free** — HTTP via stdlib `urllib`; only parsing needs `beautifulsoup4`

---

## Quick start (Windows)

**Requirements:** Python 3.10+ ([download](https://www.python.org/downloads/) — tick
*Add python.exe to PATH*).

1. Download the repo (`Code` → `Download ZIP`) and unzip it to a path **without spaces or
   non-ASCII characters**.
2. Double-click **`setup.cmd`**. It creates `.venv`, installs dependencies and generates
   `config.json` + `glossary.txt`.
3. Open `config.json` and fill in `api_key`:

   ```json
   {
     "base_url": "https://api.deepseek.com/v1",
     "api_key": "sk-your-key",
     "model": "deepseek-chat"
   }
   ```

   For a **free local model**, point `base_url` at `http://127.0.0.1:11434/v1` (Ollama),
   set `model` to e.g. `qwen2.5:32b` and put any placeholder string in `api_key`.

4. `booktrans.cmd doctor` — checks interpreter, dependencies, key, glossary, write permissions.
5. Translate:

   ```
   booktrans.cmd make "D:\books\some book.epub"
   ```

   Output lands in `out\`: `some book-zh.epub`, `some book-ja.epub`.
   Or just drag the epub onto `拖书到这里.cmd` (`drop-book-here`).

Estimate cost and volume first — no API call, no money spent:

```
booktrans.cmd make "D:\books\some book.epub" --dry-run
```

---

## Commands

| Command | Purpose |
|---|---|
| `booktrans.cmd init` | Generate `config.json` and `glossary.txt` templates |
| `booktrans.cmd doctor` | Environment self-check |
| `booktrans.cmd make book.epub` | Translate (Chinese + Japanese by default) |
| `booktrans.cmd make book.epub --dry-run` | Stats only: paragraphs, words, estimated tokens |
| `booktrans.cmd make book.epub --lang ja` | Japanese only (halves cost and time) |
| `booktrans.cmd make book.epub --concurrency 8` | Raise concurrency (default 6) |
| `booktrans.cmd make book.epub --glossary my.txt` | Use a custom glossary |
| `booktrans.cmd make book.epub --title-zh "Title"` | Set the book title manually |
| `booktrans.cmd make book.epub --furigana fill` | Top up missing furigana with MeCab |
| `booktrans.cmd make book.epub --keep-styles` | Keep inline colours/font-sizes too |
| `booktrans.cmd validate out.epub --lang ja` | Validate any EPUB |
| `booktrans.cmd --version` | Version |

**Resume:** translations are cached per paragraph, keyed by
`book + language + file + paragraph + hash of the source text`. Re-run the same command after a
crash, an error or Ctrl+C — finished paragraphs are never re-translated or re-billed.
Delete `cache\cache.sqlite` to start over.

---

## How it works

Five decisions, each one aimed at a specific way layout gets destroyed.

**1. Extraction by paragraph, with placeholders.**
Every leaf block element in the spine (`p`, `h1`–`h6`, `li`, `blockquote`, `pre`, `td`…) has its
inner HTML replaced by a token like `@@U0007@@`; the original template stays in memory.
Filling in a translation only replaces tokens — **the element and its classes are never touched**.
`nav.xhtml` is the one exception (see 3).

**2. Styling is read from CSS, not guessed from class names.**
`cssmap.py` parses every `text/css` item into `{class: {declarations}}` and classifies by
declaration: `font-style:italic` → italic, `font-weight:bold`/≥600 → bold,
`text-decoration:line-through` → strike, `font-variant:small-caps` → small caps, and so on.
Recognised spans become canonical tags (`<i>`, `<b>`, `<s>`, `<code>`…), which are rendered back as
`bt-i` / `bt-b` / … **and the CSS rules are injected into the book's own stylesheet**, so the styling
works even when the book has no `.italic` class at all.

Unrecognised spans are dropped (text kept). Use `--keep-styles` to preserve colour/font-size wrappers.

**3. Two navigation files, translated once.**
Entries from `nav.xhtml` and `toc.ncx` are merged and deduplicated, translated in a single request,
then written back by mapping *source text → translation*. For `nav.xhtml` the bytes of the document
are edited **in place**: only the text inside `<a>` changes; `<ol>`, `<li>`, `href`s and nesting are
untouched.

TOC entries that are identical to a body heading reuse the body translation (matched on
tag-stripped text), so the TOC usually costs nothing extra.

**4. Furigana in three tiers.**
`llm` asks the model to emit `{表記|よみ}` pairs, converted to `<ruby>` on write-back (≈96.5%
coverage). `fill` then tops up unannotated kanji with MeCab + UniDic — deterministic, no tokens
(99.9%). `to_ruby()` splits `{引き裂く|ひきさく}` into `引(ひ)き裂(さ)く`, keeping okurigana outside
the ruby, which is how Japanese typesetting normally does it.

**5. Validation instead of "I checked it".**
Every run reports XML validity, dead links, missing images and furigana coverage into the log.
`tests/smoke.py` adds 33 assertions over a generated mini EPUB3 (nav TOC, poetry `<br>`, `<pre>`
indentation, italics, footnote anchors, cache hits, PDF rejection).

---

## Measured on a real book

59,085 English words / 2,383 paragraphs / 54 XHTML files (the book is copyrighted and not in this
repo; the method is reproducible):

| Check | Result |
|---|---|
| Byte-identical to a human-reviewed build (ignoring `<head><title>`) | **52 / 54 files** |
| Remaining 2 differences | entity fix: `&amp;` no longer double-escaped to `&amp;amp;` |
| `<a href>` links | 786 → **786** |
| `id=` anchors | 360 → **360** |
| `<img>` | 48 → **48** |
| `<li>` | 885 → **885** |
| XML valid / dead links / missing images | **0 / 0 / 0** |
| Fixed overhead (parse + fill + validate + package, two languages) | **15 s** |
| Furigana coverage | 96.5% default, 99.9% with `--furigana fill` |

`wall clock ≈ (chunks ÷ concurrency) × request latency + 15 s`. The log prints the real numbers:

```
[zh] 请求 83 次（并发 8）：平均 47.3s，最快 21.0s，最慢 96.4s
[zh] 翻译墙钟 9.8 分；串行要 65.5 分，并发 6.7×
总耗时：19 分 42 秒（含解析、翻译、回填、校验、打包）
```

---

## Known limitations

| Limitation | Notes |
|---|---|
| **EPUB only** | PDF is page coordinates, not structure — converting it loses inline emphasis, footnote jumps and image order |
| **No bilingual edition** | Side-by-side doubles the book and breaks the layout. Use `bilingual_book_maker` for that |
| **Inline colours dropped by default** | Semantic styles only; `--keep-styles` keeps colour/font-size wrappers (+5% prompt size) |
| **Big-font span mixed with other content** | If the source is `<span class="big">first half</span><br/>second half`, that styling may be lost (6 of 35 occurrences on the test book). Cosmetic only |
| **`landmarks` nav untouched** | Only `epub:type="toc"` is translated |
| **Scanned PDFs** | Out of scope — that's OCR plus reflow |
| **Windows scripts only** | The Python code is cross-platform (`python -m booktrans`); only the `.cmd` wrappers are Windows-specific |

## FAQ

| Symptom | Fix |
|---|---|
| `还没配置 API Key` | Fill `api_key` in `config.json` |
| `429` / rate limit | Lower `concurrency` to 3 |
| A few paragraphs left in English | Those requests failed — re-run the same command |
| Terminology drifts | Add the term to `glossary.txt`, delete `cache\cache.sqlite`, re-run (re-billed) |
| Furigana renders on two lines | Reader lacks ruby support; Calibre / Apple Books / recent Kindle are fine |
| Layout looks off | Try `--keep-styles`; if it persists, map the class names in the `css` config block |

Logs: `logs\run-*.log`.

---

## Self-test

No book needed, no network:

```
.venv\Scripts\python.exe tests\smoke.py
```

It generates a two-chapter mini EPUB3 (nav TOC, poetry `<br>`, `<pre>` block, CSS-defined italics and
small caps, footnote anchor, image), runs a mock translation, validates the output, re-runs to prove
cache hits, and confirms PDFs are rejected. 33 assertions, report in `logs\smoke.txt`.

---

## Legal

- Use this only with works **you own the rights to** or that are **in the public domain**.
- Translation is an exclusive right of the copyright holder. Private use is generally fair use;
  **publishing the translation is infringement** (Berne Convention and national laws).
- This repo contains **no book text, no translations, no API keys**. `config.json`, `glossary.txt`,
  `cache/`, `out/` are gitignored.
- The tool collects nothing. Your key stays in your local `config.json` and is only sent to the
  `base_url` you configure.

## License

[MIT](LICENSE)
