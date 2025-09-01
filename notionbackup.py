# /// script
# dependencies = [
#     "requests==2.32.3",
#     "beautifulsoup4==4.12.3",
# ]
# ///

import argparse
import os
import re
import shutil
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup


args = argparse.ArgumentParser(description="fix notion html exports")
args.add_argument("path", type=Path, help="path to the zipped html export")
args = args.parse_args()
path = args.path
assert path.exists(), f"{path} does not exist"

unzippath = path.with_suffix("")
if unzippath.exists():
    shutil.rmtree(unzippath)
with zipfile.ZipFile(path, "r") as zip_ref:
    zip_ref.extractall(unzippath)

cachepath = unzippath / ".cache"
cachepath.mkdir(exist_ok=True)
cached_img_links = []

css_injectionpath = Path.cwd() / "notionbackup" / "injections" / "injection.css"


htmlpaths = list(unzippath.rglob("*.html"))
for htmlpath in htmlpaths:
    print(f"processing: {htmlpath}")

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
    style_elem.string = css_injectionpath.read_text(encoding="utf-8")
    head = soup.head
    head.append(style_elem)

    # cache images
    imgs = [elem for elem in elems if elem.name == "img"]
    external_imgs = [img for img in imgs if img.has_attr("src") and img["src"].startswith("http")]
    for img in external_imgs:
        url = img["src"]
        if url in cached_img_links:
            continue
        cached_img_links.append(url)
        try:
            response = requests.get(url, stream=True)
            filename = Path(url).name
            cache_img_path = cachepath / filename
            with open(cache_img_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=128):
                    f.write(chunk)
            img["src"] = os.path.relpath(cache_img_path, htmlpath.parent)
        except requests.exceptions.ConnectionError:
            pass
    print(f"\t cached {len(external_imgs)} images")

    # cache katex
    equations = [elem for elem in elems if elem and elem.name == "figure" and "equation" in elem.get("class", [])]
    if equations:
        eqn = equations[0]
        style_elem = eqn.find("style")
        assert style_elem
        katex_url = style_elem.string.split("url(")[1].split(")")[0].replace("'", "")

        katex_cache_path = cachepath / "katex.min.css"
        response = requests.get(katex_url, stream=True)
        with open(katex_cache_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=128):
                f.write(chunk)
        style_elem.decompose()

        head = soup.head
        link_elem = soup.new_tag("link")
        link_elem["rel"] = "stylesheet"
        link_elem["href"] = os.path.relpath(katex_cache_path, htmlpath.parent)
        head.append(link_elem)
    print(f"\t cached {len(equations)} equations")

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
