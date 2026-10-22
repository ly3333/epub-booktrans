# -*- coding: utf-8 -*-
"""翻译调度：分片、并发、断点缓存、失败重试。"""
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request

LOCK = threading.Lock()

SYSTEM = {
    "zh": (
        "你是资深图书译者，正在翻译一本英文书。\n"
        "要求：忠实、通顺、有节奏；保留作者的语气与具体细节，不要译成四平八稳的书面语；"
        "不要合并或拆分段落，不加译者注、编号或解释。\n"
        "保留原文里的内联标签：<i></i> <b></b> <s></s> <a href=\"...\">...</a>，href 一个字都不能改。\n"
        "中文用全角引号“ ”‘ ’，不要用半角双引号。\n"
        "只输出 JSON 对象，不要任何解释或代码块标记。"
    ),
    "ja": (
        "あなたはプロの書籍翻訳者です。英語の本を日本語に翻訳します。\n"
        "要件：忠実で自然な日本語。です・ます調を基調に、叙述部分はより口語的に。"
        "段落を分割・統合しない。訳注や番号を付けない。\n"
        "原文のインラインタグ <i></i> <b></b> <s></s> <a href=\"...\">...</a> はそのまま残す（href は変更禁止）。\n"
        "日本語の引用は「 」『 』を使う。\n"
        "**すべての漢字を含む語に読みを付ける**：{表記|よみ} の形式。送り仮名は花かっこ内に含める"
        "（例：{会話|かいわ}、{難しい|むずかしい}、{引き裂く|ひきさく}）。"
        "数字・英字・仮名だけの語には付けない。人名地名はラテン文字のまま。入れ子の花かっこは禁止。\n"
        "JSON オブジェクトだけを出力し、説明もコードフェンスも付けない。"
    ),
}


class Cache:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS seg(
            book TEXT, lang TEXT, file TEXT, uid TEXT, hash TEXT, text TEXT, ts REAL,
            PRIMARY KEY(book, lang, file, uid))""")
        self.db.commit()

    def get_map(self, book, lang):
        cur = self.db.execute("SELECT file, uid, hash, text FROM seg WHERE book=? AND lang=?", (book, lang))
        return {(f, u): (h, t) for f, u, h, t in cur.fetchall()}

    def put_many(self, book, lang, rows):
        with LOCK:
            self.db.executemany(
                "INSERT INTO seg(book,lang,file,uid,hash,text,ts) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(book,lang,file,uid) DO UPDATE SET hash=excluded.hash,text=excluded.text,ts=excluded.ts",
                [(book, lang, f, u, h, t, time.time()) for f, u, h, t in rows])
            self.db.commit()

    def stats(self, book, lang):
        return self.db.execute("SELECT COUNT(*) FROM seg WHERE book=? AND lang=?", (book, lang)).fetchone()[0]


def digest(s):
    import hashlib
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:16]


class Provider:
    def translate(self, items, lang, cfg, extra=""):
        raise NotImplementedError


class MockProvider(Provider):
    """自测用：不联网，返回带标记的伪译文，验证整条流水线。"""

    def translate(self, items, lang, cfg, extra=""):
        return {it["uid"]: ("【%s】%s" % (lang, it["en"])) for it in items}


def _norm_uid(u):
    """U001 与 U0001 归一：只保留数字部分。"""
    m = re.match(r"^U0*(\d+)$", str(u or ""))
    return "U%d" % int(m.group(1)) if m else str(u)


class ReplayProvider(Provider):
    """从已有译文目录回放，用于回归测试。"""

    def __init__(self, root):
        self.data = {}
        for lang in ("zh", "ja"):
            self.data[lang] = {}
            cands = [os.path.join(root, lang), os.path.join(root, "tr_" + lang)]
            d = next((c for c in cands if os.path.isdir(c)), None)
            if not d:
                continue
            for fn in os.listdir(d):
                if not fn.endswith(".json"):
                    continue
                base = fn.split(".part")[0].replace(".json", "")
                try:
                    obj = json.load(open(os.path.join(d, fn), encoding="utf-8"))
                except Exception:
                    continue
                self.data[lang].setdefault(base, {}).update(
                    {_norm_uid(k): v for k, v in obj.items()})

    def translate(self, items, lang, cfg, extra=""):
        out = {}
        for it in items:
            base = os.path.basename(it["file"]).rsplit(".", 1)[0]
            v = self.data.get(lang, {}).get(base, {}).get(_norm_uid(it["uid"]))
            if v:
                out[it["uid"]] = v
        return out


class OpenAIProvider(Provider):
    def __init__(self, cfg):
        self.cfg = cfg
        key = (cfg.get("api_key") or "").strip()
        if not key or "在这里填" in key:
            raise SystemExit("还没配置 API Key。请打开 %s 填写 api_key。" % cfg.get("_config_path"))

    def _post(self, payload):
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.cfg["api_key"]})
        with urllib.request.urlopen(req, timeout=self.cfg.get("timeout", 180)) as r:
            return json.loads(r.read().decode("utf-8"))

    def translate(self, items, lang, cfg, extra=""):
        sys_prompt = SYSTEM.get(lang, SYSTEM["zh"])
        if extra:
            sys_prompt += "\n\n" + extra
        user = ("翻译下面 JSON 数组里每一项的 en 字段。返回一个 JSON 对象，键就是 uid，值是译文。\n"
                "条数必须与输入完全一致，不能漏、不能合并段落。\n\n"
                + json.dumps([{"uid": it["uid"], "en": it["en"]} for it in items], ensure_ascii=False))
        payload = {
            "model": cfg["model"],
            "temperature": cfg.get("temperature", 0.6),
            "max_tokens": cfg.get("max_tokens", 8192),
            "messages": [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": user}],
        }
        data = self._post(payload)
        text = data["choices"][0]["message"]["content"]
        return _parse_obj(text)


def _parse_obj(s):
    if not s:
        return {}
    s = s.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        for cand in (s[i:j + 1], re.sub(r",\s*([}\]])", r"\1", s[i:j + 1])):
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict):
                    return {str(k): v for k, v in obj.items()}
                if isinstance(obj, list):
                    return {str(x.get("uid")): x.get("text") or x.get("translation") or ""
                            for x in obj if isinstance(x, dict) and x.get("uid")}
            except Exception:
                pass
    return {}


def make_provider(cfg):
    kind = (cfg.get("provider") or "openai").lower()
    if kind == "mock":
        return MockProvider()
    if kind == "replay":
        return ReplayProvider(cfg.get("replay_dir") or ".")
    return OpenAIProvider(cfg)


def chunk_units(units, words_per_chunk):
    """同文件内连续切块，保住上下文。"""
    chunks, cur, cw, curfile = [], [], 0, None
    for u in units:
        if curfile is not None and (u["file"] != curfile or cw >= words_per_chunk):
            chunks.append(cur)
            cur, cw = [], 0
        curfile = u["file"]
        cur.append(u)
        cw += len(re.findall(r"[A-Za-z][A-Za-z'\-]*", u["en"]))
    if cur:
        chunks.append(cur)
    return chunks


def translate_units(units, lang, cfg, cache, book_id, log=print, extra=""):
    """返回 {文件名: {uid: 译文}}。键必须带文件名——不同文件的段号会重复。"""
    prov = make_provider(cfg)
    cached = cache.get_map(book_id, lang)
    todo, reused = [], 0
    for u in units:
        h = digest(u["en"])
        hit = cached.get((u["file"], u["uid"]))
        if hit and hit[0] == h and hit[1] and hit[1].strip():
            reused += 1
            continue
        todo.append(u)
    log("  [%s] 共 %d 段，缓存命中 %d，待译 %d" % (lang, len(units), reused, len(todo)))

    def grouped(pairs):
        out = {}
        for (f, u), t in pairs.items():
            out.setdefault(f, {})[u] = t
        return out

    if not todo:
        log("  [%s] 全部命中缓存，未发请求（省下这次全部费用）" % lang)
        return grouped({k: v[1] for k, v in cached.items()})

    chunks = chunk_units(todo, cfg.get("words_per_chunk", 1200))
    log("  [%s] 切成 %d 个分片，并发 %d" % (lang, len(chunks), cfg.get("concurrency", 6)))

    results, failures = {}, []
    done = [0]
    step = max(20, len(todo) // 10)
    lock = threading.Lock()
    # 计时：给「快多少」留硬数据，不靠估
    lat = []
    t_start = time.time()

    def work(ch):
        for attempt in range(1, cfg.get("retries", 3) + 1):
            t0 = time.time()
            try:
                got = prov.translate(ch, lang, cfg, extra=extra)
                got = {k: v for k, v in got.items() if isinstance(v, str) and v.strip()}
                miss = [x for x in ch if x["uid"] not in got]
                if miss and attempt < cfg.get("retries", 3):
                    raise ValueError("缺 %d 条" % len(miss))
                rows = [(x["file"], x["uid"], digest(x["en"]), got[x["uid"]])
                        for x in ch if x["uid"] in got]
                cache.put_many(book_id, lang, rows)
                dt = time.time() - t0
                with lock:
                    lat.append((dt, len(ch)))
                    for x in ch:
                        if x["uid"] in got:
                            results[(x["file"], x["uid"])] = got[x["uid"]]
                    done[0] += len(ch)
                    if done[0] % step < len(ch) or done[0] >= len(todo):
                        log("    %d/%d 段完成（%.0f%%）" % (done[0], len(todo), 100.0 * done[0] / len(todo)))
                return
            except Exception as e:
                if attempt >= cfg.get("retries", 3):
                    with lock:
                        failures.append((ch, str(e)))
                        log("    ! 分片失败（%d 段）：%s" % (len(ch), str(e)[:120]))
                else:
                    time.sleep(1.5 * attempt)

    from concurrent.futures import ThreadPoolExecutor
    workers = max(1, int(cfg.get("concurrency", 6)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, chunks))
    wall = time.time() - t_start
    if lat:
        dts = [d for d, _n in lat]
        serial = sum(dts)
        log("  [%s] 请求 %d 次（并发 %d）：平均 %.1fs，最快 %.1fs，最慢 %.1fs"
            % (lang, len(lat), workers, serial / len(dts), min(dts), max(dts)))
        log("  [%s] 翻译墙钟 %.1f 分；串行要 %.1f 分，并发 %.1f×"
            % (lang, wall / 60, serial / 60, serial / wall if wall else 1))
    else:
        log("  [%s] 全部命中缓存，未发请求（%.1f 秒）" % (lang, wall))

    # 补齐：缓存里已有的 + 本轮新译的
    cached2 = cache.get_map(book_id, lang)
    pairs = {}
    for u in units:
        k = (u["file"], u["uid"])
        if k in results:
            pairs[k] = results[k]
            continue
        hit = cached2.get(k)
        if hit and hit[0] == digest(u["en"]):
            pairs[k] = hit[1]
    if failures:
        log("  [%s] 有 %d 个分片失败，这些段落将保留英文原文" % (lang, len(failures)))
    return grouped(pairs)


def translate_labels(labels, lang, cfg, log=print, seen=None):
    """目录 / 章节标题 → {原文: 译文}。

    seen 是正文已经译过的「原文 → 译文」表：很多 nav 条目跟正文里的章节标题一字不差，
    直接复用，既省钱又保证目录和正文口径一致。
    """
    seen = seen or {}
    out = {}
    todo = []
    for s in labels:
        hit = seen.get(s) or seen.get(s.strip())
        if hit:
            out[s] = hit
        else:
            todo.append(s)
    reused = len(out)
    if todo:
        prov = make_provider(cfg)
        items = [{"uid": "T%03d" % i, "en": s, "file": "toc"} for i, s in enumerate(todo)]
        try:
            got = prov.translate(items, lang, cfg)
            for it in items:
                out[it["en"]] = (got.get(it["uid"]) or "").strip() or it["en"]
        except Exception as e:
            log("  ! 目录标题翻译失败，保留原文：%s" % str(e)[:80])
            for s in todo:
                out.setdefault(s, s)
    if labels:
        log("  [%s] 目录 %d 条：复用正文 %d，实译 %d" % (lang, len(labels), reused, len(todo)))
    return out
