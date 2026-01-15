# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "beautifulsoup4==4.12.3",
#     "click==8.1.7",
#     "tqdm==4.66.4",
# ]
# ///

import os
import re
import shutil
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List

import urllib.error
import urllib.request
import click
from bs4 import BeautifulSoup
from tqdm import tqdm

CSS_INJECTION = """
/* notionbackup injection */
body { white-space: normal !important; }
p { min-height: 1em !important; }
.code, code { font-size: 100% !important; }
blockquote { font-size: 100% !important; }
.callout { white-space: normal !important; }
.callout div:has(span.icon) { font-size: 100% !important; }
.source:not(.bookmark) { font-size: 100% !important; }
"""


def process_html_file(htmlpath: Path, cachepath: Path, css_injection: str, cached_img_links: List[str], cached_img_lock: Lock) -> Dict[str, Any]:
    content = htmlpath.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")
    elems = soup.find_all()

    # drop ids
    for elem in elems:
        if elem.has_attr("id"):
            del elem["id"]

    # drop empty class attributes
    for elem in elems:
        if elem.has_attr("class") and elem["class"] == []:
            del elem["class"]

    # replace asset content with filename instead of aws-bucket name
    anchor_wrappers = [elem for elem in elems if elem.has_attr("class") and "source" in elem["class"]]
    anchors = [wrapper.find("a") for wrapper in anchor_wrappers]
    is_asset = lambda anchor: anchor and anchor.has_attr("href") and anchor["href"] and not anchor["href"].startswith("http")
    for anchor in anchors:
        if is_asset(anchor):
            href = anchor["href"]
            filename = Path(href).name
            anchor.string = filename

    # inject custom css
    style_elem = soup.new_tag("style")
    style_elem.string = css_injection
    head = soup.head
    head.append(style_elem)

    # cache images
    imgs = [elem for elem in elems if elem.name == "img"]
    external_imgs = [img for img in imgs if img.has_attr("src") and img["src"].startswith("http")]
    for img in external_imgs:
        url = img["src"]
        with cached_img_lock:
            if url in cached_img_links:
                continue
            cached_img_links.append(url)

        try:
            with urllib.request.urlopen(url) as response:
                filename = Path(url).name
                cache_img_path = cachepath / filename
                with open(cache_img_path, "wb") as f:
                    while True:
                        chunk = response.read(128)
                        if not chunk:
                            break
                        f.write(chunk)
                img["src"] = os.path.relpath(cache_img_path, htmlpath.parent)
        except urllib.error.URLError:
            pass

    # cache katex
    equations = [elem for elem in elems if elem and elem.name == "figure" and "equation" in elem.get("class", [])]
    if equations:
        eqn = equations[0]
        style_elem = eqn.find("style")
        assert style_elem
        katex_url = style_elem.string.split("url(")[1].split(")")[0].replace("'", "")

        katex_cache_path = cachepath / "katex.min.css"
        katex_cache_path = cachepath / "katex.min.css"
        with urllib.request.urlopen(katex_url) as response:
            with open(katex_cache_path, "wb") as f:
                while True:
                    chunk = response.read(128)
                    if not chunk:
                        break
                    f.write(chunk)
        style_elem.decompose()

        head = soup.head
        link_elem = soup.new_tag("link")
        link_elem["rel"] = "stylesheet"
        link_elem["href"] = os.path.relpath(katex_cache_path, htmlpath.parent)
        head.append(link_elem)

    # format html, keep equations as they are
    equations = [elem for elem in soup.find_all("figure", class_="equation")]
    equation_placeholders = {}
    for i, eq in enumerate(equations):
        placeholder = f"EQUATION_PLACEHOLDER_{i}"
        equation_placeholders[placeholder] = str(eq)
        eq.replace_with(placeholder)
    formatted_html = soup.prettify()
    for placeholder, equation in equation_placeholders.items():
        formatted_html = formatted_html.replace(placeholder, equation)
    formatted_html = re.sub(r'\n\s*(<figure class="equation".*?</figure>)\s*\n', r"\1", formatted_html, flags=re.DOTALL)

    # write back
    htmlpath.write_text(formatted_html, encoding="utf-8")

    return {
        "filename": htmlpath.name,
        "images": len(external_imgs),
        "equations": len(equations),
    }


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.help_option("--help", "-h")
def main(path: Path) -> None:
    # figure out input and output
    start_time = time.time()
    unzippath = path.with_suffix("")
    if unzippath.exists():
        shutil.rmtree(unzippath)
    with zipfile.ZipFile(path, "r") as zip_ref:
        zip_ref.extractall(unzippath)
    htmlpaths = list(unzippath.rglob("*.html"))

    # share common stuff between pages
    cachepath = unzippath / ".cache"
    cachepath.mkdir(exist_ok=True)
    cached_img_links = []
    cached_img_lock = Lock()

    executor = ThreadPoolExecutor(max_workers=os.cpu_count())
    futures = [executor.submit(process_html_file, htmlpath, cachepath, CSS_INJECTION, cached_img_links, cached_img_lock) for htmlpath in htmlpaths]
    pbar = tqdm(total=len(htmlpaths), desc="Processing", unit="file")
    for future in as_completed(futures):
        result = future.result()
        pbar.set_description(f"Completed: {result['filename']}")
        pbar.set_postfix(images=result["images"], equations=result["equations"])
        pbar.update(1)
    pbar.close()
    executor.shutdown(wait=True)
    end_time = time.time()
    print(f"Time elapsed: {end_time - start_time:.2f}s")


if __name__ == "__main__":
    main()
