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
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
import tyro
from bs4 import BeautifulSoup
from bs4.element import Stylesheet
from tqdm import tqdm
from tqdm.contrib.concurrent import thread_map

CSS_INJECTION = """
/* notionbackup injection */
p { min-height: 1em !important; }
.code, code { font-size: 100% !important; }
blockquote { font-size: 100% !important; }
.callout div:has(span.icon) { font-size: 100% !important; }
.source:not(.bookmark) { font-size: 100% !important; }
"""

CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""")


def fetch(client: httpx.Client, cache: Path, url: str) -> str | None:
    try:
        # hashed names avoid collisions and keep "?" out of local paths
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + Path(httpx.URL(url).path).suffix
        body = client.get(url).raise_for_status().content
    except (httpx.HTTPError, httpx.InvalidURL):
        return None
    if name.endswith(".css"):  # stylesheets like katex load fonts relative to themselves

        def localize(m: re.Match[str]) -> str:
            ref = urljoin(url, m[1])
            return f"url({fetch(client, cache, ref) or ref})"

        body = CSS_URL.sub(localize, body.decode()).encode()
    (cache / name).write_bytes(body)
    return name


def rewrite(soup: BeautifulSoup, local: dict[str, str]) -> str:
    for img in soup.select('img[src^="http"]'):
        img["src"] = local.get(str(img["src"]), str(img["src"]))
    for st in soup.find_all("style"):
        st.string = Stylesheet(CSS_URL.sub(lambda m: f"url('{local[m[1]]}')" if m[1] in local else m[0], st.get_text()))
    for a in soup.select('.source a[href]:not([href^="http"])'):  # show attachment filename, not storage key
        a.string = unquote(Path(str(a["href"])).name)
    style = soup.new_tag("style")
    style.string = Stylesheet(CSS_INJECTION)
    (soup.head or soup).append(style)
    # break lines inside tags, never between them, so no visible whitespace is added
    return re.sub(r"(?<!--)><", "\n><", str(soup))


def main(path: Path, /) -> None:
    """Make a Notion HTML export zip editable, offline-ready and closer to Notion's look."""
    out = path.with_suffix("")
    if not zipfile.is_zipfile(path):
        raise SystemExit(f"{path} is not a zip file")
    if out.exists():
        raise SystemExit(f"{out} already exists, delete it first")
    with zipfile.ZipFile(path) as z:
        if all(n.endswith(".zip") for n in z.namelist()):  # large exports nest Part-N zips
            for n in z.namelist():
                with zipfile.ZipFile(z.open(n)) as part:
                    part.extractall(out)
        else:
            z.extractall(out)
    cache = out / ".cache"
    cache.mkdir(parents=True)

    soups = {p: BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser") for p in tqdm(list(out.rglob("*.html")), desc="parse")}
    urls = list({str(img["src"]) for s in soups.values() for img in s.select('img[src^="http"]')} | {u for s in soups.values() for st in s.find_all("style") for u in CSS_URL.findall(st.get_text()) if u.startswith("http")})
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        names = {u: n for u, n in zip(urls, thread_map(lambda u: fetch(client, cache, u), urls, desc="download")) if n}

    for page, soup in tqdm(soups.items(), desc="write"):
        up = "../" * (len(page.relative_to(out).parts) - 1)
        page.write_text(rewrite(soup, {u: f"{up}.cache/{n}" for u, n in names.items()}), encoding="utf-8")


if __name__ == "__main__":
    tyro.cli(main)
