#!/usr/bin/env python3
import sys, os, re, subprocess, tempfile, shutil
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

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help']:
        print("epub2md - Convert EPUB to Markdown\n\nUsage: epub2md <book.epub> [outdir]\n\nOutput:\n  <outdir>/chapters/: Markdown files\n  <outdir>/media/: Images")
        sys.exit(0)
    
    epub = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else epub.stem).resolve()
    
    if not epub.exists(): sys.exit(f"Error: {epub} not found")
    if not shutil.which('pandoc'): sys.exit("Error: pandoc not found. Install: brew install pandoc")
    
    print(f"Converting {epub.name}...")
    out.mkdir(exist_ok=True)
    outdir = out / 'chapters'
    media = out / 'media'
    outdir.mkdir(exist_ok=True)
    
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        subprocess.run(['unzip', '-q', str(epub), '-d', str(t)], check=True)
        (t/'f.lua').write_text(LUA)
        
        toc = t/'toc.ncx'
        if not toc.exists(): sys.exit("Error: toc.ncx not found")
        
        tree = ET.parse(toc)
        ns = {'n': 'http://www.daisy.org/z3986/2005/ncx/'}
        
        n = 0
        for nav in tree.findall('.//n:navPoint', ns):
            te = nav.find('.//n:text', ns)
            ce = nav.find('.//n:content', ns)
            if te is None or ce is None: continue
            
            title = te.text or 'untitled'
            src = ce.get('src', '').split('#')[0]
            if not src.endswith(('.xhtml', '.html')): continue
            if not (t/src).exists(): continue
            
            n += 1
            safe = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or 'untitled'
            name = outdir / f"{n:02d}-{safe}.md"
            
            r = subprocess.run([
                'pandoc', src, '-f', 'html', '-t', 'gfm', '--wrap=none',
                '--lua-filter', 'f.lua', '--extract-media', str(media), '-o', str(name)
            ], cwd=t, capture_output=True)
            
            if r.returncode == 0:
                print(f"✓ {n:02d} {title}")
            else:
                print(f"✗ {title}")
    
    print(f"\nDone! {n} chapters → {out}/")
    if media.exists() and list(media.iterdir()):
        imgs = len(list(media.rglob('*.*')))
        print(f"{imgs} images → {out}/media/")

if __name__ == '__main__':
    main()
