#!/usr/bin/env python3
"""Copia o HTML público da Dra. Júlia Adde para public/, sem baixar nem executar PHP."""

import html as html_lib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ORIGIN = "https://drajuliaadde.com.br"
HOST = "drajuliaadde.com.br"
SKIP_PARTS = ("/wp-admin/", "/wp-json", "/xmlrpc.php", "/feed", "/comments/")
ASSET_EXT = (
    ".css", ".js", ".mjs", ".json", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".ico", ".avif", ".mp4", ".webm",
)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TRUSTINDEX_CSS = (
    '<link rel="stylesheet" id="trustindex-widget-css" '
    'href="/wp-content/uploads/trustindex-google-widget.css" media="all" />'
)
SUSPICIOUS = re.compile(
    r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k|"
    r"base64_decode|gzinflate|str_rot13|coinhive|cryptonight|"
    r"document\.write\s*\(\s*unescape",
    re.I,
)
OLD_SERVER = re.compile(
    r"background-image\s*:\s*url\(\s*[\"']?https?://srv\d+\.wemarketingdigital\.com\.br[^)\"']*[\"']?\s*\)\s*;?",
    re.I,
)
CTX = ssl.create_default_context()


def fetch(url: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": BROWSER_UA},
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as response:
            data = response.read()
            final = response.geturl()
            ctype = response.headers.get("Content-Type", "")
        return data, final if final else url, ctype
    except urllib.error.HTTPError as error:
        data = error.read()
        ctype = error.headers.get("Content-Type", "") or ""
        if error.code == 403 and b"<html" in data[:800].lower():
            return data, url, ctype
        raise


def load_pages() -> list[str]:
    data, _, _ = fetch(ORIGIN + "/sitemap_index.xml")
    index = data.decode("utf-8", "replace")
    pages = []
    for loc in re.findall(r"<loc>(.*?)</loc>", index):
        child, _, _ = fetch(loc)
        pages.extend(re.findall(r"<loc>(.*?)</loc>", child.decode("utf-8", "replace")))
    # home first, then the rest, unique
    ordered = []
    seen = set()
    for page in [ORIGIN + "/"] + pages:
        clean = page if page.endswith("/") else page + "/"
        if clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def same_origin(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc == HOST


def strip_query(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def should_skip(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith(".php") or any(part in path for part in SKIP_PARTS):
        return True
    return False


def local_path(url: str) -> Path:
    path = urllib.parse.urlparse(strip_query(url)).path
    if path.endswith("/"):
        path += "index.html"
    return PUBLIC / path.lstrip("/")


def extract_urls(text: str, base: str) -> set[str]:
    found = set()
    patterns = [
        r"""(?:href|src|poster|data-src|data-lazy-src)=["']([^"']+)["']""",
        r"""srcset=["']([^"']+)["']""",
        r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""",
        r"""https:\\/\\/drajuliaadde\.com\.br\\/[^"\\\s]+""",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            chunk = match.replace("\\/", "/")
            if pattern.startswith("srcset"):
                pieces = [part.strip().split(" ")[0] for part in chunk.split(",")]
            else:
                pieces = [chunk]
            for piece in pieces:
                if not piece or piece.startswith(("data:", "mailto:", "tel:", "javascript:", "#")):
                    continue
                absolute = urllib.parse.urljoin(base, piece)
                found.add(absolute.split("#")[0])
    for match in re.findall(r"[\w./-]+\.bundle\.min\.js", text):
        found.add(urllib.parse.urljoin(base, match))
    for match in re.findall(
        r"/wp-content/uploads/[^\"'\\s>]+\.(?:json|css|js|mjs|png|jpe?g|gif|webp|svg|woff2?|avif|mp4)",
        text,
        flags=re.I,
    ):
        found.add(urllib.parse.urljoin(base, match))
    for match in re.findall(
        r"\\/wp-content\\/uploads\\/(?:[A-Za-z0-9_.-]+\\/)*[A-Za-z0-9_.-]+\.json",
        text,
    ):
        found.add(urllib.parse.urljoin(base, match.replace("\\/", "/")))
    return found


def fix_star_alts(html: str) -> str:
    number = 0

    def repl(match: re.Match) -> str:
        nonlocal number
        tag = match.group(0)
        alt = re.search(r'alt="([^"]*)"', tag)
        if not alt or alt.group(1) != "Google":
            return tag
        number += 1
        label = f"Google star {((number - 1) % 5) + 1}"
        return tag.replace('alt="Google"', f'alt="{label}"', 1)

    return re.sub(r'<img\b[^>]*\bclass="ti-star"[^>]*>', repl, html)


def strip_origin(text: str) -> str:
    for scheme in ("https", "http"):
        escaped = scheme + ":\\/\\/" + HOST
        plain = scheme + "://" + HOST
        text = text.replace(escaped + "\\/", "\\/")
        text = text.replace(escaped, "\\/")
        text = text.replace(plain + "/", "/")
        text = text.replace(plain, "/")
    return text


def page_title_from_html(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    title = re.sub(r"\s+", " ", title).strip()
    for suffix in (
        " - Dra. Júlia Blumke Adde",
        " – Dra. Júlia Blumke Adde",
        " | Dra. Júlia Blumke Adde",
        " - Dra. Julia Blumke Adde",
    ):
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def replace_page_title(html: str) -> str:
    if "[page_title]" not in html and "&#91;page_title&#93;" not in html:
        return html
    title = page_title_from_html(html)
    if not title:
        return html
    safe = html_lib.escape(title, quote=False)
    return html.replace("[page_title]", safe).replace("&#91;page_title&#93;", safe)


def rewrite_html(html: str) -> str:
    html = replace_page_title(html)
    html = strip_origin(html)
    html = re.sub(r"<link[^>]+(?:xmlrpc\.php|/wp-json/|/feed/)[^>]*>", "", html, flags=re.I)
    html = re.sub(
        r'(<link rel="canonical" href=")/',
        r"\1https://drajuliaadde.com.br/",
        html,
        flags=re.I,
    )
    html = OLD_SERVER.sub("", html)
    html = re.sub(
        r'<script\b[^>]*\bsrc="https://cdn\.trustindex\.io/loader\.js[^"]*"[^>]*>\s*</script>',
        "",
        html,
    )
    html = re.sub(
        r'<div\b[^>]*\bdata-src="https://cdn\.trustindex\.io/loader\.js\?wp-widget"[^>]*>\s*</div>',
        "",
        html,
    )
    html = re.sub(
        r'<pre class="ti-widget">([\s\S]*?)</pre>\s*<pre class="ti-hidden-markup"[^>]*>[\s\S]*?</pre>',
        r'<div class="ti-widget-slot">\1</div>',
        html,
        count=1,
    )
    html = re.sub(
        r'\sstyle="opacity:\s*0;\s*height:\s*0\s*!important;\s*overflow:\s*hidden\s*!important"',
        "",
        html,
    )
    html = re.sub(
        r'<script id="wp-emoji-settings"[\s\S]*?</script>\s*'
        r'<script type="module">[\s\S]*?wp-emoji-loader\.min\.js\s*</script>',
        "",
        html,
        count=1,
    )
    html = fix_star_alts(html)
    if "ti-widget" in html and not re.search(r"<link\b[^>]*trustindex-google-widget\.css", html):
        html = html.replace("</head>", TRUSTINDEX_CSS + "\n</head>", 1)
    return html


def pagination_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in ("", HOST):
        return None
    if not re.search(r"/page/\d+/?$", parsed.path):
        return None
    path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
    return ORIGIN + path


def queue_found_urls(html: str, final: str, queue: list[str], extra_pages: list[str], seen_pages: set[str]) -> None:
    for url in extract_urls(html, final):
        if same_origin(url) and not should_skip(url):
            queue.append(url)
        nxt = pagination_url(url)
        if nxt and nxt not in seen_pages and nxt not in extra_pages:
            extra_pages.append(nxt)


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    print(f"pages_to_copy {len(pages)}", flush=True)
    queue = []
    seen = set()
    saved_pages = []
    flags = []
    seen_pages = set(pages)
    extra_pages = []

    for index, page in enumerate(pages, start=1):
        try:
            data, final, ctype = fetch(page)
        except Exception as error:
            flags.append(f"falha pagina {page}: {error}")
            print(f"fail page {page}", flush=True)
            continue
        if "text/html" not in ctype:
            flags.append(f"pagina sem html: {page} ({ctype})")
            continue
        html = data.decode("utf-8", "replace")
        if SUSPICIOUS.search(html):
            flags.append(f"html suspeito: {final}")
        if urllib.parse.urlparse(final).path in ("", "/"):
            target = PUBLIC / "index.html"
        else:
            target = local_path(final if final.endswith("/") else final + "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite_html(html), encoding="utf-8")
        saved_pages.append(
            "/"
            if target.name == "index.html" and target.parent == PUBLIC
            else "/" + str(target.relative_to(PUBLIC)).removesuffix("index.html")
        )
        queue_found_urls(html, final, queue, extra_pages, seen_pages)
        if index % 20 == 0:
            print(f"pages {index}/{len(pages)}", flush=True)

    while extra_pages:
        page = extra_pages.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        try:
            data, final, ctype = fetch(page)
        except Exception as error:
            flags.append(f"falha pagina {page}: {error}")
            print(f"fail page {page}", flush=True)
            continue
        if "text/html" not in ctype:
            flags.append(f"pagina sem html: {page} ({ctype})")
            continue
        html = data.decode("utf-8", "replace")
        if SUSPICIOUS.search(html):
            flags.append(f"html suspeito: {final}")
        target = local_path(final if final.endswith("/") else final + "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite_html(html), encoding="utf-8")
        saved_pages.append("/" + str(target.relative_to(PUBLIC)).removesuffix("index.html"))
        if re.search(r'name="robots"[^>]*content="[^"]*noindex', html, flags=re.I):
            flags.append(f"paginacao noindex, fora do sitemap: {page}")
        else:
            pages.append(page)
        queue_found_urls(html, final, queue, extra_pages, seen_pages)
        print(f"page extra {page}", flush=True)

    assets = 0
    while queue:
        url = queue.pop(0)
        clean = strip_query(url)
        if clean in seen or not same_origin(clean) or should_skip(clean):
            continue
        path = urllib.parse.urlparse(clean).path.lower()
        if not any(path.endswith(ext) for ext in ASSET_EXT):
            continue
        seen.add(clean)
        try:
            data, _final, ctype = fetch(clean)
        except Exception as error:
            flags.append(f"falha {clean}: {error}")
            continue
        if "text/html" in ctype or path.endswith(".php"):
            flags.append(f"ignorado (nao e asset estatico): {clean}")
            continue
        if path.endswith((".css", ".js", ".mjs", ".svg", ".json")) or "javascript" in ctype or "text/css" in ctype:
            text = data.decode("utf-8", "replace")
            if SUSPICIOUS.search(text):
                flags.append(f"asset suspeito: {clean}")
            cleaned = strip_origin(OLD_SERVER.sub("", text))
            if cleaned != text:
                flags.append(f"removida marcacao de servidor antigo: {clean}")
                data = cleaned.encode("utf-8")
                text = cleaned
            for extra in extract_urls(text, clean):
                if same_origin(extra) and not should_skip(extra):
                    queue.append(extra)
        dest = local_path(clean)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        assets += 1
        if assets % 50 == 0:
            print(f"assets {assets}", flush=True)

    locs = []
    for page in pages:
        path = urllib.parse.urlparse(page).path or "/"
        if not path.endswith("/"):
            path += "/"
        locs.append(f"  <url><loc>{ORIGIN}{path}</loc></url>")
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(locs)
        + "\n</urlset>\n"
    )
    (PUBLIC / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\nSitemap: https://drajuliaadde.com.br/sitemap.xml\n",
        encoding="utf-8",
    )
    report = {"pages": len(saved_pages), "assets": assets, "flags": flags}
    (ROOT / "mirror-report.json").write_text(json.dumps({"pages": saved_pages, "assets": assets, "flags": flags}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
