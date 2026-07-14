#!/usr/bin/env python3
"""Verifica struttura e frontmatter della skill presentation-production."""
import argparse, json, sys
from pathlib import Path
FILES=["SKILL.md","references/design-system.md","references/qa-accessibility.md","references/sources-licenses.md","references/source-register.md","assets/ASSET_MANIFEST.json","examples/storyboard-template.md","scripts/validate_pptx.py","scripts/asset_audit.py"]
def main():
 p=argparse.ArgumentParser(); p.add_argument("root",type=Path); a=p.parse_args(); missing=[x for x in FILES if not (a.root/x).is_file()]; errors=[]
 if missing: errors.append("missing: "+", ".join(missing))
 skill=a.root/"SKILL.md"
 text=skill.read_text(encoding="utf-8") if skill.is_file() else ""
 if not text.startswith("---\n"): errors.append("missing YAML opening delimiter")
 else:
  parts=text.split("---",2); fm=parts[1] if len(parts)>2 else ""
  if "name: presentation-production" not in fm: errors.append("frontmatter name missing")
  if "description:" not in fm: errors.append("frontmatter description missing")
 try: json.loads((a.root/"assets/ASSET_MANIFEST.json").read_text(encoding="utf-8"))
 except Exception as e: errors.append("invalid asset manifest: "+str(e))
 for e in errors: print("ERROR:",e,file=sys.stderr)
 print(f"Skill package check: {len(FILES)-len(missing)}/{len(FILES)} required files found; {len(errors)} error(s).")
 return 1 if errors else 0
if __name__=="__main__": sys.exit(main())
