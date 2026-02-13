#!/usr/bin/env python3
import sys, re, subprocess, tempfile, shutil
from collections import defaultdict
from urllib.parse import unquote
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

def _ln(tag): return tag.split("}", 1)[-1] if "}" in tag else tag

def _parse_xml(path):
  try: return ET.parse(path)
  except (ET.ParseError, FileNotFoundError): return None

def _find_opf(root):
  if not (tree := _parse_xml(root / "META-INF" / "container.xml")): return None
  rf = tree.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
  if rf is None or not (fp := rf.attrib.get("full-path")): return None
  opf = root / fp
  return opf if opf.exists() else None

def _parse_opf(root):
  if not (opf := _find_opf(root)) or not (tree := _parse_xml(opf)): return opf, {}, None
  ns = {"opf": "http://www.idpf.org/2007/opf"}
  pkg = tree.getroot()
  mel = pkg.find("opf:manifest", ns)
  manifest = {item.attrib["id"]: item for item in (mel or []) if "id" in item.attrib}
  spine_el = pkg.find("opf:spine", ns)
  return opf, manifest, spine_el

def _parse_ncx(ncx_path):
  if not (tree := _parse_xml(ncx_path)): return ncx_path.parent, []
  ns = {"n": "http://www.daisy.org/z3986/2005/ncx/"}
  items = []
  for nav in tree.findall(".//n:navPoint", ns):
    te, ce = nav.find(".//n:text", ns), nav.find(".//n:content", ns)
    if te is None or ce is None: continue
    href = ce.get("src", "")
    if not href: continue
    fp, _, frag = href.partition("#")
    if fp: items.append((te.text or "untitled", fp, frag or None))
  return ncx_path.parent, items

def _parse_nav(nav_path):
  if not (tree := _parse_xml(nav_path)): return nav_path.parent, []
  navs = [el for el in tree.getroot().iter() if _ln(el.tag) == "nav"]
  nav_el = next((c for c in navs for k, v in c.attrib.items() if _ln(k) == "type" and "toc" in v), None)
  if nav_el is None: nav_el = navs[0] if navs else None
  if nav_el is None: return nav_path.parent, []
  items = []
  def walk(node):
    for child in node:
      name = _ln(child.tag)
      if name in ("ol", "ul"): walk(child)
      elif name == "li":
        a = next((s for s in child.iter() if _ln(s.tag) == "a"), None)
        if a and (href := a.attrib.get("href", "")):
          fp, _, frag = href.partition("#")
          if fp: items.append(("".join(a.itertext()).strip() or "untitled", fp, frag or None))
        for sub in child:
          if _ln(sub.tag) in ("ol", "ul"): walk(sub)
  walk(nav_el)
  return nav_path.parent, items

def _find_toc(root):
  opf, manifest, spine_el = _parse_opf(root)
  if opf is None: return None, []
  # try EPUB3 nav
  for it in manifest.values():
    if "nav" in it.attrib.get("properties", "").split() and (href := it.attrib.get("href")):
      base, items = _parse_nav(opf.parent / href)
      if items: return base, items
  # try NCX
  ncx = None
  if spine_el is not None and (tid := spine_el.attrib.get("toc")) and tid in manifest: ncx = manifest[tid]
  if ncx is None: ncx = next((it for it in manifest.values() if it.attrib.get("media-type") == "application/x-dtbncx+xml"), None)
  if ncx is not None and (href := ncx.attrib.get("href")):
    base, items = _parse_ncx(opf.parent / href)
    if items: return base, items
  return None, []

def _find_spine(root):
  opf, manifest, spine_el = _parse_opf(root)
  if opf is None or spine_el is None: return None, []
  items = []
  for ref in spine_el:
    if _ln(ref.tag) != "itemref": continue
    idref = ref.attrib.get("idref", "")
    if idref not in manifest: continue
    it = manifest[idref]
    href, mt = it.attrib.get("href", ""), it.attrib.get("media-type", "")
    if href and "html" in mt: items.append(unquote(href))
  return opf.parent, items

def _extract_title(path):
  try: text = path.read_text(encoding="utf-8", errors="ignore")
  except OSError: return None
  for tag in ("h1", "h2", "h3"):
    if m := re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE):
      if inner := re.sub(r"<[^>]+>", "", m.group(1)).strip(): return inner
  return None

def _find_anchor(text, anchor):
  if not anchor: return None
  pats = [f'id="{anchor}"', f"id='{anchor}'", f'name="{anchor}"', f"name='{anchor}'"]
  positions = [i for p in pats if (i := text.find(p)) != -1]
  if not positions: return None
  pos = min(positions)
  lt = text.rfind("<", 0, pos)
  return lt if lt != -1 else pos

def _extract_segment(text, start_id, end_id):
  if not start_id and not end_id: return None
  start = _find_anchor(text, start_id) if start_id else 0
  if start is None: return None
  end = len(text)
  if end_id and (e := _find_anchor(text, end_id)) and e > start: end = e
  return text[start:end] if start < end else None

def main():
  if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    print("epub2md - Convert EPUB to Markdown\n\nUsage: epub2md <book.epub> [outdir]\n\nOutput:\n  <outdir>/*.md: Markdown files\n  <outdir>/images/: Images")
    sys.exit(0)

  epub = Path(sys.argv[1]).resolve()
  out = Path(sys.argv[2] if len(sys.argv) > 2 else epub.stem).resolve()
  if not epub.exists(): sys.exit(f"Error: {epub} not found")
  if not shutil.which("pandoc"): sys.exit("Error: pandoc not found")

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
    spine_dir, spine_files = _find_spine(t)

    # build chapters from TOC
    chapters, use_spine = [], False
    if base_dir and items:
      print(f"Found {len(items)} entries in toc")
      for i, item in enumerate(items, 1):
        title, src = item[0], unquote(item[1])
        frag = item[2] if len(item) > 2 else None
        if not src.endswith((".xhtml", ".html", ".htm")): continue
        hp = base_dir / src
        if not hp.exists(): continue
        chapters.append({"order": i, "title": title, "src": src, "fragment": frag, "html_path": hp, "start_id": None, "end_id": None})
      # check coverage
      if chapters and spine_files:
        toc_files = {ch["html_path"].resolve() for ch in chapters}
        spine_resolved = {(spine_dir / sf).resolve() for sf in spine_files if (spine_dir / sf).exists()}
        if spine_resolved and len(toc_files) < len(spine_resolved) * 0.5:
          print(f"TOC covers {len(toc_files)}/{len(spine_resolved)} spine files, using spine instead")
          use_spine = True
    else:
      use_spine = True

    # fallback to spine
    if use_spine:
      if not spine_dir or not spine_files: sys.exit("Error: no toc or spine found")
      base_dir, chapters = spine_dir, []
      for i, src in enumerate(spine_files, 1):
        hp = base_dir / src
        if not hp.exists(): continue
        chapters.append({"order": i, "title": _extract_title(hp) or Path(src).stem, "src": src, "fragment": None, "html_path": hp, "start_id": None, "end_id": None})
      print(f"Using spine: {len(chapters)} files")

    if not chapters: sys.exit("Error: no html chapters found")

    # resolve fragment ranges for multi-chapter files
    by_file = defaultdict(list)
    for ch in chapters: by_file[ch["html_path"]].append(ch)
    for group in by_file.values():
      group.sort(key=lambda c: c["order"])
      if not any(c["fragment"] for c in group): continue
      for i, ch in enumerate(group):
        end_id = next((l["fragment"] for l in group[i+1:] if l["fragment"]), None)
        if ch["fragment"]: ch["start_id"], ch["end_id"] = ch["fragment"], end_id
        elif i == 0 and end_id: ch["end_id"] = end_id

    # convert each chapter
    chapters.sort(key=lambda c: c["order"])
    abs_prefix = str(media) + "/"
    n = 0
    for ch in chapters:
      snippet = None
      if ch["start_id"] is not None or ch["end_id"] is not None:
        try: text = ch["html_path"].read_text(encoding="utf-8", errors="ignore")
        except OSError: text = ""
        snippet = _extract_segment(text, ch["start_id"], ch["end_id"])

      n += 1
      safe = re.sub(r"[^a-z0-9]+", "-", ch["title"].lower()).strip("-")[:60].rstrip("-") or "untitled"
      name = out / f"{n:02d}-{safe}.md"
      inp = ["-"] if snippet else [ch["src"]]

      r = subprocess.run(
        ["pandoc", *inp, "-f", "html", "-t", "gfm", "--wrap=none", "--lua-filter", str(t / "f.lua"), "--extract-media", str(media), "-o", str(name)],
        cwd=base_dir, capture_output=True, text=True, input=snippet)

      if r.returncode == 0:
        md = name.read_text(encoding="utf-8")
        if abs_prefix in md: name.write_text(md.replace(abs_prefix, "images/"), encoding="utf-8")
        print(f"✓ {n:02d} {ch['title']}")
      else:
        print(f"✗ {ch['title']}")
        if r.stderr: print(f"  {r.stderr[:200]}")

  print(f"\nDone! {n} chapters → {out}/")
  if media.exists() and any(media.iterdir()):
    print(f"{sum(1 for _ in media.rglob('*.*'))} images → {media}/")

if __name__ == "__main__": main()
