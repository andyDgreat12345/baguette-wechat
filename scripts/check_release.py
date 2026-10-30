#!/usr/bin/env python3
"""Check public source only. This is a targeted scan, not a complete secret audit."""
import ast
import json
from pathlib import Path
import re
import sys
BASE=Path(__file__).resolve().parents[1]
EXCLUDED={'.git','.venv','runtime','__pycache__','.pytest_cache','build','dist'}
ALLOWED={'app','tests','scripts','config','plugins','vm','docs','assets','resources','licenses','.github'}
PATTERNS=[re.compile(x) for x in (r'sk-[A-Za-z0-9_-]{24,}',r'gh[pousr]_[A-Za-z0-9]{24,}',r'github_pat_[A-Za-z0-9_]{25,}',r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',r'/Users'+r'/[A-Za-z][A-Za-z0-9_-]*/')]

def files():
 for p in sorted(BASE.rglob('*')):
  rel=p.relative_to(BASE)
  if any(part in EXCLUDED for part in rel.parts):continue
  if p.is_file():yield p

def main():
 errors=[];count=0;total=0
 for p in files():
  rel=p.relative_to(BASE);count+=1;total+=p.stat().st_size
  if p.is_symlink():errors.append(str(rel)+': symlink is not permitted in release');continue
  if len(rel.parts)>1 and rel.parts[0] not in ALLOWED:errors.append(str(rel)+': unexpected source directory')
  if p.suffix.lower() in {'.sqlite','.sqlite3','.db','.zip','.dmg','.ipsw','.png','.jpg','.jpeg','.gif','.pem','.key'}:errors.append(str(rel)+': private/binary asset requires explicit provenance review');continue
  try:text=p.read_text()
  except UnicodeDecodeError:errors.append(str(rel)+': non-text file');continue
  if any(rx.search(text) for rx in PATTERNS):errors.append(str(rel)+': credential/private-install pattern detected')
  if p.suffix=='.py':
   try:ast.parse(text,filename=str(rel))
   except SyntaxError as e:errors.append(str(rel)+': '+str(e))
  if p.suffix=='.json':
   try:json.loads(text)
   except ValueError:errors.append(str(rel)+': invalid JSON')
  if p.suffix=='.md':
   for target in re.findall(r'!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)',text):
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'):continue
    path=target.split('#',1)[0].strip('<>')
    if path and not (p.parent/path).exists():errors.append(str(rel)+': missing link '+path)
 for required in ('README.md','README.en.md','LICENSE','AGENTS.md','CONTRIBUTING.md','SECURITY.md','CITATION.cff','UPSTREAMS.lock.json','docs/INSTALL.zh-CN.md','docs/INSTALL.en.md'):
  if not (BASE/required).exists():errors.append('Missing '+required)
 print(json.dumps({'files':count,'bytes':total,'errors':errors,'scope':'public source; runtime and local environments excluded'},ensure_ascii=False,indent=2))
 return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
