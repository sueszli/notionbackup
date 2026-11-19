# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "beautifulsoup4==4.15.0",
#     "httpx==0.28.1",
#     "tqdm==4.70.1",
#     "tyro==1.0.17",
# ]
# ///

import hashlib
import re
import zipfile
from functools import partial
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
import tyro
from bs4 import BeautifulSoup
from bs4.element import Stylesheet
from tqdm.contrib.concurrent import process_map, thread_map

CSS_INJECTION = """
/* notionbackup injection */
p { min-height: 1em !important; }
.code, code { font-size: 100% !important; }
blockquote { font-size: 100% !important; }
.callout div:has(span.icon) { font-size: 100% !important; }
.source:not(.bookmark) { font-size: 100% !important; }
"""
CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""")
IMG_SRC = re.compile(r'<img\b[^>]*?\ssrc="(http[^"]*)"')

parse = lambda page: BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")


def remote_urls(page: Path) -> set[str]:
    html = page.read_text(encoding="utf-8")  # regex instead of a second full parse, this pass only needs urls
    return {unescape(u) for u in IMG_SRC.findall(html)} | {u for u in CSS_URL.findall(html) if u.startswith("http")}


def fetch(client: httpx.Client, cache: Path, url: str) -> str | None:
    try:
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + Path(httpx.URL(url).path).suffix  # hashed names avoid collisions and keep "?" out of local paths
        body = client.get(url).raise_for_status().content
    except httpx.HTTPError, httpx.InvalidURL:
        return None
    if name.endswith(".css"):  # stylesheets like katex load their fonts relative to themselves
        body = CSS_URL.sub(lambda m: f"url({fetch(client, cache, ref := urljoin(url, m[1])) or ref})", body.decode()).encode()
    (cache / name).write_bytes(body)
    return name


def rewrite(page: Path, out: Path, names: dict[str, str]) -> None:
    soup = parse(page)
    local = {u: "../" * (len(page.relative_to(out).parts) - 1) + ".cache/" + n for u, n in names.items()}
    for img in soup.select('img[src^="http"]'):
        img["src"] = local.get(str(img["src"]), str(img["src"]))
    for st in soup.find_all("style"):
        st.string = Stylesheet(CSS_URL.sub(lambda m: f"url('{local[m[1]]}')" if m[1] in local else m[0], st.get_text()))
    for a in soup.select('.source a[href]:not([href^="http"])'):  # show the attachment filename, not its storage key
        a.string = unquote(Path(str(a["href"])).name)
    (soup.head or soup).append(style := soup.new_tag("style"))
    style.string = Stylesheet(CSS_INJECTION)
    # break lines inside tags, never between them, so the rendered page keeps its whitespace. script and style bodies stay untouched
    page.write_text(re.sub(r"(<(script|style)\b.*?</\2)|(?<!--)(?=><)", lambda m: m[1] or "\n", str(soup), flags=re.DOTALL), encoding="utf-8")


def main(path: Path, /) -> None:
    out = path.with_suffix("")
    assert zipfile.is_zipfile(path), f"not a zip file: {path}"
    assert not out.exists(), f"output already exists, delete it first: {out}"
    with zipfile.ZipFile(path) as z:
        nested = all(n.endswith(".zip") for n in z.namelist())  # large exports nest Part-N zips
        for part in [zipfile.ZipFile(z.open(n)) for n in z.namelist()] if nested else [z]:
            part.extractall(out)
    (cache := out / ".cache").mkdir(parents=True)
    pages = list(out.rglob("*.html"))
    urls = list(set().union(*map(remote_urls, pages)))
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        names = {u: n for u, n in zip(urls, thread_map(partial(fetch, client, cache), urls, desc="download")) if n}
    process_map(partial(rewrite, out=out, names=names), pages, desc="write", chunksize=16)


if __name__ == "__main__":
    tyro.cli(main)
