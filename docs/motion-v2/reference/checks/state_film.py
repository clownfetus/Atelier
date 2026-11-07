"""Contact sheets of each state, for checking choreography by eye.

Usage:  python state_film.py <path-to-page.html> <out_dir> [--chrome <exe>]
Writes warnstrip.png, succstrip.png, errstrip.png (one frame every 150-170ms).
The page must expose window.__atelier.run(state) and a #main glyph host.
Note: call run() with `void`, since the working loop never resolves.
"""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
ap=argparse.ArgumentParser(); ap.add_argument('page'); ap.add_argument('out'); ap.add_argument('--chrome',default=None); args=ap.parse_args()
URL=Path(args.page).resolve().as_uri(); OUT=Path(args.out); OUT.mkdir(parents=True,exist_ok=True)
from PIL import Image
import io, sys
def strip(pg,state,n,dt,out,cols=8):
    pg.evaluate(f"void window.__atelier.run('{state}')")
    mb=pg.locator('#main').bounding_box(); fr=[]
    for k in range(n):
        pg.wait_for_timeout(dt); png=pg.screenshot(timeout=8000)
        fr.append(Image.open(io.BytesIO(png)).convert('RGB').crop((int(mb['x']),int(mb['y']),int(mb['x']+mb['width']),int(mb['y']+mb['height']))).resize((150,125)))
    rows=(n+cols-1)//cols; c=Image.new('RGB',(cols*154,rows*129),'white')
    for k,im in enumerate(fr): c.paste(im,((k%cols)*154,(k//cols)*129))
    c.save(out)
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=args.chrome) if args.chrome else p.chromium.launch()
    pg=b.new_page(viewport={"width":1180,"height":900}); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.wait_for_timeout(300)
    pg.evaluate("void window.__atelier.run('working')"); pg.wait_for_timeout(2500)
    strip(pg,'warning',24,170,str(OUT/'warnstrip.png'))
    strip(pg,'success',24,150,str(OUT/'succstrip.png'))
    strip(pg,'error',16,170,str(OUT/'errstrip.png'))
    print(errs); b.close()
