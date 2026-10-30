"""Prepare a fresh private AstrBot instance using pinned upstream schemas."""
import copy
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'app'))
from baguette_config import load_config
RUNTIME=BASE/'runtime';BRAIN=RUNTIME/'brain';INSTANCE=BRAIN/'instance'

def defaults(schema):
    return {k:defaults(v['items']) if v.get('type')=='object' else v.get('default') for k,v in schema.items()}

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)

def main():
    os.umask(0o077)
    from astrbot.core.config.default import DEFAULT_CONFIG
    from astrbot.cli.commands.cmd_conf import _set_dashboard_password
    target=INSTANCE/'data/cmd_config.json'
    if target.exists():raise SystemExit('Refusing to overwrite an existing brain. Back it up and migrate deliberately.')
    cfg=load_config();config=copy.deepcopy(DEFAULT_CONFIG)
    for part in ('data/config','data/plugins','data/temp'):(INSTANCE/part).mkdir(parents=True,exist_ok=True)
    (INSTANCE/'.astrbot').touch()
    password=secrets.token_urlsafe(32);write(BRAIN/'auth.json',{'username':cfg['owner_id'],'password':password})
    token_file=RUNTIME/'relay-token'
    if not token_file.exists():token_file.write_text(secrets.token_urlsafe(32));token_file.chmod(0o600)
    token=token_file.read_text().strip()
    config['admins_id']=[cfg['owner_id']]
    config['dashboard'].update(username=cfg['owner_id'],host='127.0.0.1',port=6186,password_change_required=False)
    _set_dashboard_password(config,password)
    config['provider_sources']=[
      {'id':'deepseek_flash_source','type':'openai_chat_completion','provider':'openai','provider_type':'chat_completion','key':[token],'api_base':'http://127.0.0.1:18764/v1','timeout':70,'proxy':''},
      {'id':'qwen_vision_local_source','type':'openai_chat_completion','provider':'ollama','provider_type':'chat_completion','key':['local'],'api_base':cfg['vision_base_url'],'timeout':40,'proxy':''}]
    config['provider']=[
      {'id':'deepseek_flash','enable':True,'model':cfg['deepseek_model'],'provider_source_id':'deepseek_flash_source','custom_extra_body':{'thinking':{'type':'disabled'}},'modalities':['text']},
      {'id':'bge_m3_local','type':'ollama_embedding','provider':'ollama','provider_type':'embedding','enable':True,'embedding_api_base':cfg['embedding_base_url'],'embedding_model':cfg['embedding_model'],'embedding_dimensions':1024,'timeout':120,'proxy':''},
      {'id':'qwen_vision_local','enable':True,'model':cfg['vision_model'],'provider_source_id':'qwen_vision_local_source','provider':'ollama','ollama_disable_thinking':True,'custom_extra_body':{'reasoning_effort':'none','max_tokens':500},'modalities':['text','image']}]
    config['platform']=[{'type':'wechat_vm','id':'wechat-vm','enable':True}]
    config['wake_prefix']=['大肥鱼','肥鱼',cfg['bot_id'],'@'+cfg['bot_id']]
    ps=config['platform_settings'];ps.update(unique_session=False,enable_id_white_list=False,reply_with_mention=False,reply_with_quote=False)
    ps['segmented_reply']['enable']=False
    ps['rate_limit']={'time':60,'count':30,'strategy':'stall'}
    config['provider_settings'].update(streaming_response=False,computer_use_runtime='none',proactive_capability={'add_cron_tools':False})
    runner=config['agent_runner']['config'];runner['model'].update(provider_id='deepseek_flash',fallback_provider_ids=[],request_max_retries=0)
    runner['persona']['persona_id']='baguette_qq_wechat';runner['misc'].update(max_steps=8,tool_call_timeout=120)
    runner['compression'].update(max_turns=32,trim_turns=4,overflow_strategy='llm_compress',provider_id='deepseek_flash')
    write(target,config)
    for upstream,name in [('livingmemory','astrbot_plugin_livingmemory'),('stealer','astrbot_plugin_stealer')]:
        src=RUNTIME/'upstream'/upstream;dest=INSTANCE/'data/plugins'/name
        if not src.exists():raise RuntimeError('Run fetch-upstreams first: '+upstream)
        shutil.copytree(src,dest,ignore=shutil.ignore_patterns('.git','__pycache__','.venv'))
        settings=defaults(json.loads((src/'_conf_schema.json').read_text(encoding='utf-8-sig')))
        if upstream=='livingmemory':
            settings['provider_settings'].update(embedding_provider_id='bge_m3_local',llm_provider_id='deepseek_flash',llm_stream_mode='never')
            settings['access_control'].update(whitelist_enabled=False,allowed_ids=cfg['owner_id'],identity_aliases='webchat:'+cfg['owner_id']+'='+cfg['owner_chat'])
            settings['session_manager']['enable_full_group_capture']=True
            settings['filtering_settings']['memory_scope_mode']='session'
            settings['reflection_engine']['summary_trigger_rounds']=5
            settings['agent_tools'].update(enable_recall_tool=True,enable_memorize_tool=True)
        else:
            settings.update(vision_provider_id='qwen_vision_local',auto_send_meme=False,steal_meme=False,external_sources_enabled=False)
            settings['custom_meme_classification_prompt']=(BASE/'resources/stickers/literal-vision-prompt.zh-CN.txt').read_text()
        write(INSTANCE/'data/config'/(name+'_config.json'),settings)
    for src in (BASE/'plugins').iterdir():
        if src.is_dir():shutil.copytree(src,INSTANCE/'data/plugins'/src.name,ignore=shutil.ignore_patterns('__pycache__'))
    print('Prepared private brain. Credentials are in ignored runtime/brain/auth.json (not printed).')
    print('Run brain.py start, then brain.py install-persona. Keep controller paused until VM binding/test.')
if __name__=='__main__':main()
