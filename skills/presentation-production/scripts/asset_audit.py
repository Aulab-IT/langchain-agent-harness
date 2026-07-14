#!/usr/bin/env python3
"""Validate an asset manifest used by the presentation-production skill."""
import argparse, json, sys
from pathlib import Path

REQUIRED={"id","type","title_or_description","creator_or_provider","license_or_permission","modifications","placement","attribution_required","status"}
VALID_STATUS={"pending-review","approved","do-not-use"}
def main():
    p=argparse.ArgumentParser(); p.add_argument("manifest",type=Path); p.add_argument("--strict",action="store_true"); a=p.parse_args()
    try: data=json.loads(a.manifest.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: print(f"ERROR: cannot parse manifest: {exc}",file=sys.stderr); return 2
    assets=data.get("project_assets",data.get("skill_assets",[]))
    if not isinstance(assets,list): print("ERROR: assets must be a list",file=sys.stderr); return 2
    errors=[]; warnings=[]; ids=set()
    for i,item in enumerate(assets,1):
        if not isinstance(item,dict): errors.append(f"item {i}: not an object"); continue
        ident=item.get("id",f"item {i}"); missing=REQUIRED-set(item)
        if missing: errors.append(f"{ident}: missing {', '.join(sorted(missing))}")
        if ident in ids: errors.append(f"{ident}: duplicate id")
        ids.add(ident)
        if item.get("status") not in VALID_STATUS: errors.append(f"{ident}: invalid status")
        external=item.get("creator_or_provider") not in (None,"Presentation Production skill")
        if a.strict and external and (not item.get("url") or not item.get("retrieved_on")): errors.append(f"{ident}: external asset requires url and retrieved_on")
        if item.get("attribution_required") and not item.get("attribution_text"): warnings.append(f"{ident}: attribution required but text is empty")
        if item.get("status")=="approved" and not item.get("license_or_permission"): errors.append(f"{ident}: approved without license/permission")
    for x in warnings: print("WARNING:",x)
    for x in errors: print("ERROR:",x,file=sys.stderr)
    print(f"Asset audit: {len(assets)} item(s), {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0
if __name__=="__main__": sys.exit(main())
