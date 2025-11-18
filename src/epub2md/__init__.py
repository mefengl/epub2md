#!/usr/bin/env python3
import sys, re, subprocess, tempfile, shutil
from collections import defaultdict
import xml.etree.ElementTree as ET
from pathlib import Path

LUA = """
function Div(el) return el.content end
function Span(el) return el.content end
function Para(el)
  if el.content and #el.content==1 and el.content[1].t=='Str' and el.content[1].text=='\\\\' then return {} end
  return el
end
function Plain(el)
  if el.content and #el.content==1 and el.content[1].t=='Str' and el.content[1].text=='\\\\' then return {} end
  return el
end
function Image(el) el.classes={} el.attributes={} return el end
"""


def _local_name(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_opf(root):
    container = root / "META-INF" / "container.xml"
    if not container.exists():
        return None
    try:
        tree = ET.parse(container)
    except ET.ParseError:
        return None
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    rootfile = tree.find(".//c:rootfile", ns)
    if rootfile is None:
        return None
    full_path = rootfile.attrib.get("full-path")
    if not full_path:
        return None
    opf = root / full_path
    return opf if opf.exists() else None


def _parse_ncx(ncx_path):
    try:
        tree = ET.parse(ncx_path)
    except ET.ParseError:
        return ncx_path.parent, []
    ns = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
    items = []
    for nav in tree.findall(".//n:navPoint", ns):
        te = nav.find(".//n:text", ns)
        ce = nav.find(".//n:content", ns)
        if te is None or ce is None:
            continue
        title = te.text or "untitled"
        href = ce.get("src", "")
        if not href:
            continue
        file_part, _, fragment = href.partition("#")
        if not file_part:
            continue
        items.append((title, file_part, fragment or None))
    return ncx_path.parent, items


def _parse_nav(nav_path):
    try:
        tree = ET.parse(nav_path)
    except ET.ParseError:
        return nav_path.parent, []
    root = tree.getroot()
    navs = [el for el in root.iter() if _local_name(el.tag) == "nav"]
    nav_el = None
    for candidate in navs:
        for attr_name, attr_val in candidate.attrib.items():
            if _local_name(attr_name) == "type" and "toc" in attr_val:
                nav_el = candidate
                break
        if nav_el is not None:
            break
    if nav_el is None and navs:
        nav_el = navs[0]
    if nav_el is None:
        return nav_path.parent, []
    items = []

    def walk(node):
        for child in node:
            name = _local_name(child.tag)
            if name in ("ol", "ul"):
                walk(child)
            elif name == "li":
                a_el = None
                for sub in child.iter():
                    if _local_name(sub.tag) == "a":
                        a_el = sub
                        break
                if a_el is not None:
                    href = a_el.attrib.get("href", "")
                    if href:
                        file_part, _, fragment = href.partition("#")
                        if file_part:
                            text = "".join(a_el.itertext()).strip()
                            title = text or "untitled"
                            items.append((title, file_part, fragment or None))
                for sub in child:
                    if _local_name(sub.tag) in ("ol", "ul"):
                        walk(sub)

    walk(nav_el)
    return nav_path.parent, items


def _find_toc(root):
    opf = _find_opf(root)
    if opf is None:
        return None, []
    try:
        tree = ET.parse(opf)
    except ET.ParseError:
        return None, []
    pkg = tree.getroot()
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    manifest_el = pkg.find("opf:manifest", ns)
    if manifest_el is None:
        return None, []
    manifest = {}
    for item in manifest_el:
        item_id = item.attrib.get("id")
        if item_id:
            manifest[item_id] = item
    spine_el = pkg.find("opf:spine", ns)

    nav_item = None
    for it in manifest.values():
        props = it.attrib.get("properties", "")
        if "nav" in props.split():
            nav_item = it
            break
    if nav_item is not None:
        href = nav_item.attrib.get("href", "")
        if href:
            nav_path = opf.parent / href
            base_dir, items = _parse_nav(nav_path)
            if items:
                return base_dir, items

    ncx_item = None
    if spine_el is not None:
        toc_id = spine_el.attrib.get("toc")
        if toc_id and toc_id in manifest:
            ncx_item = manifest[toc_id]
    if ncx_item is None:
        for it in manifest.values():
            if it.attrib.get("media-type") == "application/x-dtbncx+xml":
                ncx_item = it
                break
    if ncx_item is not None:
        href = ncx_item.attrib.get("href", "")
        if href:
            ncx_path = opf.parent / href
            base_dir, items = _parse_ncx(ncx_path)
            if items:
                return base_dir, items

    return None, []


def _find_anchor_position(text, anchor):
    if not anchor:
        return None
    patterns = [
        f'id="{anchor}"',
        f"id='{anchor}'",
        f'name="{anchor}"',
        f"name='{anchor}'",
    ]
    positions = []
    for pattern in patterns:
        idx = text.find(pattern)
        if idx != -1:
            positions.append(idx)
    if not positions:
        return None
    attr_pos = min(positions)
    lt_pos = text.rfind("<", 0, attr_pos)
    return lt_pos if lt_pos != -1 else attr_pos


def _extract_html_segment(text, start_id, end_id):
    if not start_id and not end_id:
        return None

    start_pos = 0
    if start_id:
        s = _find_anchor_position(text, start_id)
        if s is None:
            return None
        start_pos = s

    end_pos = len(text)
    if end_id:
        e = _find_anchor_position(text, end_id)
        if e is not None and e > start_pos:
            end_pos = e

    if start_pos >= end_pos:
        return None

    return text[start_pos:end_pos]


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ["-h", "--help"]:
        print(
            "epub2md - Convert EPUB to Markdown\n\n"
            "Usage: epub2md <book.epub> [outdir]\n\n"
            "Output:\n"
            "  <outdir>/*.md: Markdown files\n"
            "  <outdir>/images/: Images"
        )
        sys.exit(0)

    epub = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else epub.stem).resolve()

    if not epub.exists():
        sys.exit(f"Error: {epub} not found")
    if not shutil.which("pandoc"):
        sys.exit("Error: pandoc not found. Install: brew install pandoc")

    print(f"Converting {epub.name}...")
    out.mkdir(exist_ok=True)
    media = out / "images"
    media.mkdir(exist_ok=True)
    (media / ".gitignore").write_text("*\n")

    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        subprocess.run(["unzip", "-q", str(epub), "-d", str(t)], check=True)
        (t / "f.lua").write_text(LUA)

        base_dir, items = _find_toc(t)
        if base_dir is None or not items:
            sys.exit("Error: toc not found")

        print(f"Found {len(items)} entries in toc")

        chapters = []
        for order, item in enumerate(items, start=1):
            if len(item) == 2:
                title, src = item
                fragment = None
            else:
                title, src, fragment = item
            if not src.endswith((".xhtml", ".html")):
                continue
            html_path = base_dir / src
            if not html_path.exists():
                continue
            chapters.append(
                {
                    "order": order,
                    "title": title,
                    "src": src,
                    "fragment": fragment,
                    "html_path": html_path,
                    "start_id": None,
                    "end_id": None,
                }
            )

        if not chapters:
            sys.exit("Error: no html chapters found in toc")

        by_file = defaultdict(list)
        for ch in chapters:
            by_file[ch["html_path"]].append(ch)

        for html_path, group in by_file.items():
            group.sort(key=lambda c: c["order"])
            any_fragment = any(c["fragment"] for c in group)
            if not any_fragment:
                continue
            for idx, ch in enumerate(group):
                frag = ch["fragment"]
                end_id = None
                for later in group[idx + 1 :]:
                    if later["fragment"]:
                        end_id = later["fragment"]
                        break
                if frag:
                    ch["start_id"] = frag
                    ch["end_id"] = end_id
                elif idx == 0 and end_id:
                    ch["start_id"] = None
                    ch["end_id"] = end_id

        chapters.sort(key=lambda c: c["order"])

        html_cache = {}
        n = 0
        for ch in chapters:
            title = ch["title"]
            src = ch["src"]
            html_path = ch["html_path"]
            start_id = ch.get("start_id")
            end_id = ch.get("end_id")

            snippet = None
            if start_id is not None or end_id is not None:
                text = html_cache.get(html_path)
                if text is None:
                    try:
                        text = html_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        text = html_path.read_text(encoding="utf-8", errors="ignore")
                    html_cache[html_path] = text
                snippet = _extract_html_segment(text, start_id, end_id)

            input_arg = src
            input_text = None
            if snippet is not None:
                input_arg = "-"
                input_text = snippet

            n += 1
            safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "untitled"
            name = out / f"{n:02d}-{safe}.md"

            r = subprocess.run(
                [
                    "pandoc",
                    input_arg,
                    "-f",
                    "html",
                    "-t",
                    "gfm",
                    "--wrap=none",
                    "--lua-filter",
                    str(t / "f.lua"),
                    "--extract-media",
                    str(media),
                    "-o",
                    str(name),
                ],
                cwd=base_dir,
                capture_output=True,
                text=True,
                input=input_text,
            )

            if r.returncode == 0:
                print(f"✓ {n:02d} {title}")
            else:
                print(f"✗ {title}")
                if r.stderr:
                    print(f"  Error: {r.stderr[:200]}")

    print(f"\nDone! {n} chapters → {out}/")
    if media.exists() and list(media.iterdir()):
        imgs = len(list(media.rglob("*.*")))
        print(f"{imgs} images → {out}/media/")


if __name__ == "__main__":
    main()
