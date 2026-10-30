"""Import user-owned semantics through the original LivingMemory API, scoped per chat."""
import argparse,json,sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'app'));sys.path.insert(0,str(BASE/'scripts'))
from baguette import http
from baguette_config import load_config
from astrbot_backend import session_id

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--chat',required=True);p.add_argument('--group',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args()
 cfg=load_config();catalog=json.loads((BASE/'runtime/stickers/catalog.json').read_text());records=[];glossary=[]
 if a.chat not in [cfg['owner_chat'],*cfg['group_chats']]:raise SystemExit('Chat is outside configured allowlist')
 scope=('wechat-vm:GroupMessage:group-'+session_id(a.chat).removeprefix('wechat-') if a.group else 'webchat:FriendMessage:webchat!'+cfg['owner_id']+'!'+session_id(a.chat))
 for e in catalog['entries']:
  if e.get('wechat_verified') is not True:raise SystemExit('Catalog is not calibrated')
  text=e['id']+' '+e.get('name','')+'：'+e['meaning']+'。适用：'+'；'.join(e['use_when'])+'。避免：'+'；'.join(e['avoid_when'])+'。'
  glossary.append(text);records.append({'content':text,'session_id':scope,'persona_id':'baguette_qq_wechat','importance':1.0,'metadata':{'memory_type':'KNOWLEDGE','source':'Owner-provided local sticker semantics','topics':['表情语义',e['id']]}})
 auth=json.loads((BASE/'runtime/brain/auth.json').read_text());login=http('/api/auth/login',auth,port=6186);token=login['data']['token']
 value=http('/api/plug/astrbot_plugin_livingmemory/page/memories/import',{'format':'json','content':json.dumps({'memories':records},ensure_ascii=False),'dry_run':not a.apply,'duplicate_strategy':'skip'},port=6186,token=token)
 if value.get('status')!='ok':raise SystemExit('LivingMemory import was not confirmed')
 if a.apply:
  current=http('/api/v1/personas/by-id?persona_id=baguette_qq_wechat',port=6186,token=token)
  data=current['data'];data=data.get('persona',data)
  prompt=data['system_prompt'];marker='\n【本地已校准表情定义】\n';prompt=prompt.split(marker)[0]+marker+'\n'.join(glossary)
  result=http('/api/v1/personas/by-id',{'persona_id':'baguette_qq_wechat','system_prompt':prompt,'tools':['memorize_long_term_memory','recall_long_term_memory','select_wechat_sticker'],'skills':[]},port=6186,token=token,method='PUT')
  if result.get('status')!='ok':raise SystemExit('Memory imported but persona update not confirmed')
 print(json.dumps({'dry_run':not a.apply,'records':len(records),'status':value['status']},ensure_ascii=False))
if __name__=='__main__':main()
