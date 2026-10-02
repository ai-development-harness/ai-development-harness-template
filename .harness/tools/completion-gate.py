#!/usr/bin/env python3
"""CLI deterministic precheck for STEP Completion Gate."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from completion_gate import deterministic_precheck

def main()->int:
    p=argparse.ArgumentParser(description="Run deterministic STEP completion precheck.")
    p.add_argument("step_id")
    p.add_argument("--root",type=Path,default=None)
    p.add_argument("--json",action="store_true",dest="as_json")
    a=p.parse_args()
    root=(a.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        result=deterministic_precheck(root,a.step_id)
    except Exception as exc:
        result={"schemaVersion":1,"status":"BLOCKED","stepId":a.step_id,"error":str(exc)}
    print(json.dumps(result,ensure_ascii=False,separators=(",",":")) if a.as_json else json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
