# 更新记录

## 0.1.2 — 2026-10-22

修两个会让人以为"工具坏了"的问题，并新增一种不依赖 ruby 的注音排版。

**目录条目显示成 `<a href=...>` 源码**
目录"复用正文译文"时复用的是整段 HTML。正文里的目录页每行就是一个链接
`<a href="index_split_003.html#filepos9359">Dedication</a>`，纯文本键 `Dedication`
指向的却是含 `<a>` 和注音标记的整句译文，写进 ncx 的 `<text>` 后被转义成源码。
新增 `plain_label()` 把译文压平（去 `<rt>`/`<rp>`、去 `{表記|よみ}`、去所有标签、反转义），
`seen` 表的值、`translate_labels()` 的返回值、`patch_ncx()`/`patch_nav()` 的写入值三处都过它。

**新增 `--ruby-mode span`**
部分阅读器不认 `<ruby>`，假名会以 `私（わたし）` 的形式跟在汉字后面。
`span` 模式改用 `inline-block` 上下堆叠，完全不依赖 ruby 支持：

```html
<span class="bt-rb"><span class="bt-rt">わたし</span><span class="bt-rb-b">私</span></span>
```

默认仍是 `std`（标准 `<ruby>` + `<rp>` 降级括号）。

**其它**
- 片假名后误带注音标记（`レーベル{れーべる}`）不再退化成 `レーベルれーべる`
- 自测 33 → 37 条
- README 补三问：注音挤成一行、注音变括号、目录显示源码

## 0.1.1 — 2026-10-22

**假名注音排版失效**

注入原书 CSS 的兜底规则里写了 `ruby{...;display:inline}`。
`display:inline` 把 ruby 的注音布局整个关掉，`<rt>` 退化成普通行内文字，
假名直接接在汉字后面（`重要じゅうよう`），看起来像没标假名。

- 去掉 `display:inline`，只保留 `ruby-align`
- 去掉 `ruby>rp{display:none}`（会连带破坏降级显示）
- `to_ruby()` 改为输出带降级括号的 `<ruby>漢<rp>(</rp><rt>よみ</rt><rp>)</rp></ruby>`
- `validate.py` 统计口径同步剔除 `<rp>`
- 自测 33 → 37 条（新增 4 条守 ruby 结构）

## 0.1.0 — 2026-10-22

首个版本。

- 段落级占位符抽取回填，元素与 class 一字节不改
- 读原书 CSS 判断行内样式（`font-style` / `font-weight` / `text-decoration` / `font-variant` / `vertical-align` / `font-family`），不靠类名硬编码
- 保留 `<br>` 换行与 `<pre>` 缩进
- EPUB3 `nav.xhtml` 与 EPUB2 `toc.ncx` 目录一起翻，条目与正文去重
- 日文逐汉字标振假名（`llm` / MeCab 补标 / 关闭 三档）
- 段落级 SQLite 缓存，断点续跑不重复计费
- 成品自带校验：XML、断链、缺图、假名覆盖率
- 每个 XHTML 写 `lang` / `xml:lang`
- Windows 一键安装 `setup.cmd`，插件式安装器会绕开应用商店的占位 python
