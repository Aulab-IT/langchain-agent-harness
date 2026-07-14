#!/usr/bin/env python3
"""Diagnostica strutturale conservativa per PPTX; non certifica accessibilità."""
import argparse, json, re, sys, zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
A="http://schemas.openxmlformats.org/drawingml/2006/main"; P="http://schemas.openxmlformats.org/presentationml/2006/main"; NS={"a":A,"p":P}
def txt(el): return "".join(t.text or "" for t in el.findall(".//a:t",NS)).strip()
def main():
 p=argparse.ArgumentParser(); p.add_argument("pptx",type=Path); p.add_argument("--report",type=Path); a=p.parse_args(); r={"file":str(a.pptx),"status":"pass","slide_count":0,"slides":[],"warnings":[],"errors":[],"limitations":["Controllo OOXML strutturale; ispezionare il render e usare Accessibility Checker di PowerPoint."]}
 try:
  with zipfile.ZipFile(a.pptx) as z:
   names=set(z.namelist())
   if "[Content_Types].xml" not in names: raise ValueError("not an OOXML package")
   slides=sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml",n)),key=lambda n:int(re.search(r"\d+",n).group())); r["slide_count"]=len(slides); titles=[]
   for n in slides:
    root=ET.fromstring(z.read(n)); values=[]; title=""; images=len(root.findall(".//p:pic",NS))
    for s in root.findall(".//p:sp",NS):
     value=txt(s); values.append(value); ph=s.find(".//p:nvPr/p:ph",NS)
     if ph is not None and ph.get("type") in ("title","ctrTitle") and value: title=value
    words=len(" ".join(values).split())
    if not title: r["warnings"].append(f"{n}: no explicit title placeholder")
    if words>85: r["warnings"].append(f"{n}: dense text ({words} words)")
    if images: r["warnings"].append(f"{n}: verify alt text for {images} image(s)")
    r["slides"].append({"part":n,"title":title,"word_count":words,"image_count":images})
    if title: titles.append(title.casefold())
   dup=[t for t,c in Counter(titles).items() if c>1]
   if dup: r["warnings"].append("duplicate slide titles: "+"; ".join(dup))
 except (OSError,zipfile.BadZipFile,ValueError,ET.ParseError) as e: r["status"]="fail"; r["errors"].append(str(e))
 if r["warnings"] and r["status"]=="pass": r["status"]="pass-with-warnings"
 out=json.dumps(r,indent=2,ensure_ascii=False)
 if a.report: a.report.write_text(out+"\n",encoding="utf-8")
 print(out); return 1 if r["status"]=="fail" else 0
if __name__=="__main__": sys.exit(main())
