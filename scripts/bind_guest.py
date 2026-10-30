"""Bind only after the owner has visually confirmed the spare account/current chat."""
import argparse,hashlib,json,platform,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'app'))
from baguette_config import load_config

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--chat',required=True);p.add_argument('--group',action='store_true');p.add_argument('--owner-confirmed-spare',action='store_true',required=True);a=p.parse_args()
 model=subprocess.check_output(['/usr/sbin/sysctl','-n','hw.model'],text=True).strip()
 if not model.startswith('VirtualMac') or BASE!=Path.home()/'baguette':raise SystemExit('Run only from ~/baguette inside the dedicated VM')
 from visual_adapter import VisualWeChat,current_title,normalize_title,selected_group_avatar
 v=VisualWeChat();im,lines,_=v.frame();title=current_title(lines,im.width)
 if normalize_title(title or '')!=a.chat:raise SystemExit('Open the exact named chat first; no binding changed')
 if list(im.size)!=[1280,800]:raise SystemExit('Use calibrated 1280x800 logical display')
 avatar=im.crop((12,52,48,88)).resize((24,24)).convert('RGB');digest=hashlib.sha256(avatar.tobytes()).hexdigest()
 path=BASE/'runtime/visual-profile.json';old=json.loads(path.read_text()) if path.exists() else {}
 if old and old.get('avatar_sha256')!=digest:raise SystemExit('Existing bound account avatar differs; review/rebind deliberately')
 allowed=list(dict.fromkeys(old.get('allowed_chats',[])+[a.chat]));bindings=old.get('group_bindings',{})
 if a.group:
  group=selected_group_avatar(im)
  if not group:raise SystemExit('Selected group avatar is not visible')
  bindings[a.chat]={'owner_confirmed':True,'avatar_sha256':group,'evidence':'Owner explicitly confirmed during local binding'}
 value={'spare_account_verified':True,'wechat_pid':v.ui.app.processIdentifier(),'avatar_sha256':digest,'window_size':[1280,800],'allowed_chats':allowed,'group_bindings':bindings,'force_dark_appearance':True}
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2));path.chmod(0o600)
 print('Bound visible dedicated account/current chat locally. Host verification flags still require review and a live test.')
if __name__=='__main__':main()
