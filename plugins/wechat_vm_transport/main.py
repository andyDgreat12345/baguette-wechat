"""Map observed WeChat messages onto AstrBot's native message pipeline."""
import asyncio
import base64
import hashlib
import json
from baguette_config import load_config
import sqlite3
import time
import uuid
from collections import OrderedDict

from quart import request
from .media_cache import lookup,feature

from astrbot.api.star import Star, StarTools
from astrbot.api.event import filter
from astrbot.core.message.components import At, Image, Plain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, Group, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform import Platform
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.register import register_platform_adapter
from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent


def chat_id(name):
    return hashlib.sha256(('wechat\0'+load_config()['bot_id']+'\0'+name).encode()).hexdigest()[:32]


class WeChatVMEvent(WebChatMessageEvent):
    """Reuse AstrBot's lifecycle closing frame, with real group/speaker metadata."""
    def __init__(self, message, meta, request_id):
        super().__init__(message.message_str,message,meta,message.session_id)
        self.request_id=request_id
        self.done=asyncio.Event()
        self.outputs=[]
        self.set_extra('enable_streaming',False)
        self.set_extra('enable_reasoning',False)
        self.set_extra('enable_inline_genui',False)
        self.set_extra('_api_key_allow_admin_role',message.sender.user_id==load_config()['owner_id'])

    async def send(self, message):
        if message is None:
            self.done.set()
            return
        for part in message.chain:
            if isinstance(part,Plain):
                self.outputs.append({'type':'plain','chain_type':message.type,'data':part.text})
        await AstrMessageEvent.send(self,message)


@register_platform_adapter('wechat_vm','Verified WeChat VM transport',
    default_config_tmpl={'type':'wechat_vm','id':'wechat-vm','enable':False},
    support_streaming_message=False)
class WeChatVMPlatform(Platform):
    def __init__(self, config, settings, event_queue):
        super().__init__(config,event_queue)
        self._stop=asyncio.Event()

    def meta(self):
        return PlatformMetadata(name='wechat_vm',description='Observed WeChat VM messages',id='wechat-vm',
                                support_streaming_message=False,support_proactive_message=False)

    async def run(self):
        await self._stop.wait()

    async def terminate(self):
        self._stop.set()


class WeChatVMTransport(Star):
    def __init__(self, context):
        super().__init__(context)
        self.context=context
        self.events=OrderedDict()
        data_dir=StarTools.get_data_dir('wechat_vm_transport')
        self.media_dir=data_dir/'media';self.media_dir.mkdir(parents=True,exist_ok=True)
        self.vision=sqlite3.connect(data_dir/'vision.sqlite3')
        self.vision.execute('CREATE TABLE IF NOT EXISTS captions(hash TEXT PRIMARY KEY,caption TEXT NOT NULL,at REAL)')
        self.vision.execute('CREATE TABLE IF NOT EXISTS features(hash TEXT PRIMARY KEY,feature BLOB)')
        self.vision.execute('CREATE TABLE IF NOT EXISTS recent_media(scope TEXT,hash TEXT,sender TEXT,at REAL,PRIMARY KEY(scope,hash))')
        self.vision.commit()
        context.register_web_api('/wechat_vm/events',self.ingest,['POST'],'Native WeChat message ingest')

    @filter.on_llm_request()
    async def platform_context(self,event,req):
        if not isinstance(event,WeChatVMEvent):return
        if not event.get_group_id():
            req.system_prompt=(req.system_prompt or '')+'\n【实际微信平台上下文】当前是已核实主号的私聊，图片由原版QQ表情插件和本机视觉识别后提供。沿用该主号原有的私聊记忆和偏好，不把群聊资料带进来。'
            return
        observed=event.get_extra('wechat_ui_observation') or {}
        if observed.get('participation_mode')=='active':
            req.system_prompt=(req.system_prompt or '')+'\n【用户明确启用的群聊参与模式】本群启用活跃参与。无需每条@也可以接新话题、回应群友和合适的表情；短而自然，一次一两句，不机械刷屏，不把普通群友当主人。确实无可回应时可保持安静。此模式优先于默认仅@回复描述。'
        req.system_prompt=(req.system_prompt or '')+'\n【实际微信平台上下文，优先于默认私聊描述】当前是微信群 '+str(observed.get('chat_name'))+'。当前发言人显示名为 '+str(event.get_sender_name())+'，身份是普通群成员，不是已核实主号。按当前群聊上下文回答，不带入主号私聊资料。收到的图像说明来自原版QQ表情插件及本机视觉模型，依据实际文字、画面与语境理解，不猜图片外内容。可按语义调用 select_wechat_sticker 从已核实S01-S36中选一张，最多一张，不强行每轮配图；需要解释或认真回答时先讲清楚。纯表情回应可只调用工具。明确只要求发表情时只调用 select_wechat_sticker，不再补一句已发/给你等文字，减少等待。对方英文优先简短英文，跟随群聊语境，不反复自称鱼或教训群友；不提工程测试、ID、坐标或后台。'

    async def ingest(self):
        payload=await request.get_json(silent=True) or {}
        try:
            rid=payload.get('request_id') or uuid.uuid4().hex
            if not isinstance(rid,str) or len(rid)>100:raise ValueError('Invalid request ID')
            if rid in self.events:
                event=self.events[rid]
            else:
                name=payload['chat_name'];kind=payload['chat_type'];sender=payload['sender']
                if not isinstance(name,str) or not name.strip() or len(name)>200:raise ValueError('Invalid chat name')
                if kind not in {'private','group'}:raise ValueError('Chat type must be observed')
                if kind=='private' and name!=load_config()['owner_chat']:raise ValueError('Only the verified owner private chat is enabled')
                text=payload.get('text','')
                if not isinstance(text,str) or len(text)>16000:raise ValueError('Invalid text')
                display=str(sender.get('name') or '未核实显示名')[:100]
                identity=load_config()['owner_id'] if kind=='private' else 'observed:'+hashlib.sha256(
                    (name+'\0'+display+'\0'+str(sender.get('avatar_hash') or '')).encode()).hexdigest()[:24]
                message=AstrBotMessage();message.self_id=load_config()['bot_id'];message.message_id=rid
                message.type=MessageType.GROUP_MESSAGE if kind=='group' else MessageType.FRIEND_MESSAGE
                message.session_id='group-'+chat_id(name) if kind=='group' else 'webchat!'+load_config()['owner_id']+'!wechat-'+chat_id(name)
                message.sender=MessageMember(identity,display)
                if kind=='group':message.group=Group(group_id=message.session_id,group_name=name)
                parts=[]
                if payload.get('directed') is True:parts.append(At(qq=load_config()['bot_id']))
                captions=[];image_hashes=[]
                scope=kind+'\0'+name
                received_at=time.time()
                for media in payload.get('images',[])[:4]:
                    data=base64.b64decode(media,validate=True)
                    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>4_000_000:raise ValueError('Invalid observed PNG crop')
                    digest=hashlib.sha256(data).hexdigest();image_hashes.append(digest)
                    path=self.media_dir/(digest+'.png')
                    if not path.exists():path.write_bytes(data)
                    cached=lookup(self.vision,digest,data)
                    if cached:caption=cached
                    else:
                        star=self.context.get_registered_star('astrbot_plugin_stealer')
                        if star is None or star.star_cls is None:raise ValueError('Original QQ sticker classifier is not ready')
                        service=star.star_cls.image_processor_service
                        category,tags,desc,emotion,scenes,overlay,emotions=await service.classify_image(None,str(path))
                        if not desc and not overlay:raise ValueError('QQ sticker vision returned no readable description')
                        stored,store_note=await service.steal_image_direct(str(path),category,tags,desc,scenes,
                            extra_meta={'scope_mode':'local','origin_target':('wechat-vm:GroupMessage:group-'+chat_id(name) if kind=='group' else 'webchat:FriendMessage:webchat!'+load_config()['owner_id']+'!wechat-'+chat_id(name)),
                                        'overlay_text':overlay,'emotions':emotions,'source':'WeChat visible crop; current animation frame only'})
                        caption=json.dumps({'caption_schema':'literal_v2','source':'original QQ stealer 3.1.11 + local Qwen',
                            'visible_text':overlay,'description':desc,'emotion':emotion,'tags':tags,'use_scenarios':scenes,
                            'library_saved':stored,'coverage':'visible crop; current animation frame only'},ensure_ascii=False)
                        self.vision.execute('INSERT OR REPLACE INTO captions VALUES (?,?,?)',(digest,caption,time.time()));self.vision.commit()
                    self.vision.execute('INSERT OR REPLACE INTO captions VALUES (?,?,?)',(digest,caption,time.time()))
                    self.vision.execute('INSERT OR REPLACE INTO features VALUES (?,?)',(digest,feature(data)))
                    self.vision.execute('INSERT OR REPLACE INTO recent_media VALUES (?,?,?,?)',(scope,digest,display,received_at))
                    self.vision.commit()
                    captions.append('[图像证据 '+digest[:12]+'；本机 Qwen 转述，可能有误] '+caption)
                # Passive QQ group events do not necessarily enter the LLM's
                # conversation history. Carry recent observed media explicitly,
                # in this chat only, so a later "interpret this sticker" has its
                # referent. This is short-lived transport context, not a second
                # learning/memory implementation; LivingMemory remains original.
                self.vision.execute('DELETE FROM recent_media WHERE at < ?',(received_at-300,))
                self.vision.commit()
                if not image_hashes and payload.get('directed') is True:
                    recent=self.vision.execute(
                        'SELECT r.hash,r.sender,r.at,c.caption FROM recent_media r JOIN captions c ON c.hash=r.hash WHERE r.scope=? AND r.at>=? ORDER BY r.at DESC LIMIT 4',
                        (scope,received_at-300)).fetchall()
                    for digest,who,when,caption in reversed(recent):
                        captions.append('[本会话前序图像证据 '+digest[:12]+'；发言人 '+who+'；距今 '+str(round(received_at-when))+' 秒；不是本条新图片；视觉转述可能有误] '+caption)
                text='\n'.join([text,*captions]).strip()
                if kind=='group' and payload.get('directed') is not True:
                    text='[先前观察，仅供上下文，不请求回复] '+text
                if text:parts.append(Plain(text))
                if not parts:raise ValueError('No observed message content')
                message.message=parts;message.message_str=text
                message.raw_message={'transport':'visible_ui','chat_name':name,'sender_identity':'observed_display_and_avatar',
                                     'received_at':time.time(),'participation_mode':payload.get('participation_mode','directed'),'batch_observations':payload.get('observed_messages',[]),'directed':payload.get('directed') is True,'coverage':payload.get('coverage',{})}
                message.raw_message['image_hashes']=image_hashes
                platform=self.context.get_platform_inst('wechat-vm')
                if platform is None:raise ValueError('WeChat platform is not ready')
                meta=platform.meta() if kind=='group' else PlatformMetadata(name='webchat',description='Verified WeChat owner media',id='webchat')
                event=WeChatVMEvent(message,meta,rid)
                event.set_extra('wechat_ui_observation',message.raw_message)
                self.events[rid]=event
                while len(self.events)>256:
                    first=next(iter(self.events))
                    if not self.events[first].done.is_set():raise ValueError('Transport queue is busy')
                    self.events.pop(first)
                platform.commit_event(event)
            await asyncio.wait_for(event.done.wait(),timeout=170)
            return {'status':'ok','data':{'request_id':rid,'session':event.unified_msg_origin,
                                        'outputs':event.outputs,'sticker_id':event.get_extra('wechat_sticker_selected'),
                                        'completed':True}}
        except asyncio.TimeoutError:
            return {'status':'error','message':'Native pipeline timed out; event was not resubmitted'}
        except Exception as exc:
            return {'status':'error','message':str(exc)}
