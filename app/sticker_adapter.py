"""Verified Favorites selection for the bound WeChat VM, including lower rows."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import Image, ImageChops, ImageStat
from visual_adapter import VisualWeChat, MacWeChat, AdapterError, recognize, normalize_title, components


def difference(left, right):
    left = left.convert('RGB').resize((24, 24))
    right = right.convert('RGB').resize((24, 24))
    return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean)/3


def locate_thumbnail(image, entry, template, catalog, assets):
    x = entry['calibration_bounds'][0]
    scores = [(difference(image.crop((x,y,x+72,y+72)), template),y)
              for y in range(catalog['layout']['viewport_top'], catalog['layout']['viewport_bottom']-71)]
    error, y = min(scores)
    if error > 7:
        raise AdapterError('Expected sticker thumbnail is not visible; no selection attempted')
    crop = image.crop((x,y,x+72,y+72))
    ranked = sorted((difference(crop, Image.open(assets/e['template'])),e['id']) for e in catalog['entries'])
    if ranked[0][1] != entry['id'] or ranked[1][0]-ranked[0][0] < 3:
        raise AdapterError('Sticker identity is ambiguous; no selection attempted')
    return {'bounds':[x,y,72,72], 'mean_error':round(error,4), 'sticker_id':entry['id']}


def outgoing_rectangles(image):
    """Find opaque, right-aligned media/bubbles, excluding the avatar column."""
    pixels = image.load()
    width,height = image.size
    background = pixels[width-20,100][:3]
    points = set()
    for y in range(55,height-145):
        for x in range(650,width-68):
            p = pixels[x,y][:3]
            if max(abs(p[c]-background[c]) for c in range(3)) > 24:
                points.add((x,y))
    rectangles = []
    while points:
        start = points.pop(); stack = [start]
        x0=x1=start[0];y0=y1=start[1];count=0
        while stack:
            x,y=stack.pop();count+=1
            x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if p in points:
                    points.remove(p);stack.append(p)
        if 45 <= width-x1 <= 85 and x1-x0>=40 and y1-y0>=40 and count/((x1-x0+1)*(y1-y0+1))>.4:
            rectangles.append([x0,y0,x1-x0+1,y1-y0+1])
    return sorted(rectangles,key=lambda b:b[1])


def outgoing_matches(image, reference):
    matches=[]
    ratio=reference.width/reference.height
    for x,y,w,h in outgoing_rectangles(image):
        if abs(w/h-ratio)>.12*max(1,ratio):
            continue
        error=difference(image.crop((x,y,x+w,y+h)),reference)
        if error<12:
            matches.append({'bounds':[x,y,w,h],'mean_error':round(error,4)})
    return matches


def ordered_sticker_append(before,after,old,matches):
    """Verify an append when a repeated older sticker leaves the viewport."""
    if not old or not matches:return False
    def anchors(image):
        result=[]
        for row in components(image):
            x,y,w,h=row['bounds']
            if y<=55 or y+h>=image.height-145:continue
            crop=image.crop((x,y,x+w,y+h))
            result.append((hashlib.sha256(crop.tobytes()).hexdigest(),y,y+h))
        return result
    previous,current=anchors(before),anchors(after)
    old_bottom=max(m['bounds'][1]+m['bounds'][3] for m in old)
    new_top=matches[-1]['bounds'][1]
    return any(y>old_bottom and sum(a[0]==digest for a in previous)==1
               and sum(a[0]==digest for a in current)==1
               and any(a[0]==digest and a[2]<new_top for a in current)
               for digest,y,_ in previous)


class StickerWeChat:
    def __init__(self, assets=None):
        self.assets = Path(assets or Path.home()/'baguette/runtime/stickers')
        self.catalog = json.loads((self.assets/'catalog.json').read_text())
        self.entries = {e['id']:e for e in self.catalog['entries'] if e.get('wechat_verified') is True}
        self.visual = VisualWeChat()
        self.ui = self.visual.ui
        self.phase='preflight'

    def popup(self):
        q=self.ui.Q
        q.CGEventPost(q.kCGHIDEventTap,q.CGEventCreateMouseEvent(None,q.kCGEventMouseMoved,(700,20),0))
        time.sleep(.2)
        windows=[n for n in self.ui.tree().get('children',[]) if n.get('role')=='AXWindow']
        extra=[n for n in windows if n.get('bounds') and n['bounds'][2]<850]
        if not extra:
            return False
        expected=self.catalog['layout']['popup_ax_bounds']
        if len(extra)!=1 or any(abs(a-b)>1 for a,b in zip(extra[0]['bounds'],expected)):
            raise AdapterError('An unrecognized popup is covering WeChat')
        return True

    def close_panel(self):
        if self.popup():
            for down in (True,False):
                self.ui.Q.CGEventPost(self.ui.Q.kCGHIDEventTap,self.ui.Q.CGEventCreateKeyboardEvent(None,53,down))
            time.sleep(.2)
            if self.popup():
                raise AdapterError('Sticker panel did not close')

    def capture(self, chat, require_popup=True):
        from PIL import ImageGrab
        if require_popup and not self.popup():
            raise AdapterError('The verified sticker panel is no longer open')
        original=ImageGrab.grab().convert('RGB')
        image=original.resize(tuple(self.catalog['layout']['window_size']))
        self.visual.verify_binding(image,chat)
        # Independent native-scale crops preserve the space in the exact title.
        scale=original.width/image.width
        for rect in ((308,8,700,44),(310,6,900,46)):
            crop=original.crop(tuple(round(v*scale) for v in rect))
            text=[line['text'] for line in recognize(crop)]
            if len(text)!=1 or not self.visual.matches_chat(image,[{'text':text[0],'bounds':[316,20,500,18],'confidence':1}],chat):
                raise AdapterError('Chat title changed while selecting a sticker')
        return image

    def scroll(self, amount):
        q=self.ui.Q
        point=(420,550)
        q.CGEventPost(q.kCGHIDEventTap,q.CGEventCreateMouseEvent(None,q.kCGEventMouseMoved,point,0))
        event=q.CGEventCreateScrollWheelEvent(None,q.kCGScrollEventUnitPixel,1,amount)
        q.CGEventSetLocation(event,point);q.CGEventPost(q.kCGHIDEventTap,event)
        time.sleep(.35)

    def open_and_locate(self, chat, sticker_id):
        if sticker_id not in self.entries:
            raise AdapterError('Sticker/chat is not in the verified deployment')
        self.close_panel()
        before,lines,_=self.visual.ensure_chat(chat)
        self.visual.verify_binding(before,chat)
        if not self.visual.draft_is_empty(before,lines):
            raise AdapterError('Existing draft preserved; no sticker selected')
        self.phase='open_favorites'
        x,y=self.catalog['layout']['open_button']
        self.ui.click({'bounds':[x-5,y-5,10,10]});time.sleep(.25)
        if not self.popup():raise AdapterError('Sticker panel did not open')
        x,y=self.catalog['layout']['favorites_button']
        self.ui.click({'bounds':[x-5,y-5,10,10]})
        self.scroll(2500)
        top=self.capture(chat)
        # Check both leading stickers before relying on the reversed sequence.
        for sid in ('S36','S35'):
            e=self.entries[sid]
            found=locate_thumbnail(top,e,Image.open(self.assets/e['template']),self.catalog,self.assets)
            if abs(found['bounds'][1]-e['calibration_bounds'][1])>3:
                raise AdapterError('Favorites order changed; recalibration required')
        entry=self.entries[sticker_id]
        self.phase='scroll_to_row'
        amount=-88*max(0,entry['row']-2)
        if amount:self.scroll(amount)
        image=self.capture(chat)
        self.phase='verify_thumbnail'
        found=locate_thumbnail(image,entry,Image.open(self.assets/entry['template']),self.catalog,self.assets)
        return before,found

    def send(self, chat, sticker_id):
        before,found=self.open_and_locate(chat,sticker_id)
        reference=Image.open(self.assets/'originals'/f'{sticker_id}.jpg').convert('RGB')
        old=outgoing_matches(before,reference)
        self.capture(chat)
        self.phase='select_sticker_once'
        self.ui.click({'bounds':found['bounds']})
        time.sleep(.4)
        # Selection sends immediately. Never click again when verification is uncertain.
        self.close_panel()
        self.phase='observe_outgoing_sticker'
        for _ in range(3):
            image,lines,_=self.visual.ensure_chat(chat)
            self.visual.verify_binding(image,chat)
            matches=outgoing_matches(image,reference)
            if (matches and (len(matches)>len(old) or ordered_sticker_append(before,image,old,matches))
                    and matches[-1]['bounds'][1]>image.height-400 and self.visual.draft_is_empty(image,lines)):
                return {'ok':True,'sent':True,'verified_chat':True,'chat':chat,'sticker_id':sticker_id,
                        'status':'observed','retry_allowed':False,'selection':found,'outgoing':matches[-1],
                        'uncertainties':['own_sticker_observed_recipient_delivery_unconfirmed']}
            time.sleep(.3)
        return {'ok':False,'sent':False,'verified_chat':True,'chat':chat,'sticker_id':sticker_id,
                'status':'uncertain','retry_allowed':False,'selection':found,'phase':self.phase,
                'error':'Outgoing sticker was not verified; selection was not retried'}


def execute_sticker(chat, payload):
    driver=None
    try:
        if payload.get('expected_chat') != chat:
            raise AdapterError('Expected chat is required')
        driver=StickerWeChat()
        return driver.send(chat,payload.get('sticker_id'))
    except Exception as exc:
        clicked=driver is not None and driver.phase in {'select_sticker_once','observe_outgoing_sticker'}
        return {'ok':False,'sent':False,'chat':chat,'sticker_id':payload.get('sticker_id'),
                'status':'uncertain' if clicked else 'not_sent','retry_allowed':False,
                'phase':driver.phase if driver else 'initialize','error':str(exc)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['locate','send'])
    parser.add_argument('--chat',required=True)
    parser.add_argument('--sticker',required=True)
    args=parser.parse_args();driver=None
    try:
        driver=StickerWeChat()
        if args.action=='locate':
            _,selection=driver.open_and_locate(args.chat,args.sticker)
            value={'ok':True,'sent':False,'chat':args.chat,'selection':selection}
        else:value=driver.send(args.chat,args.sticker)
    except Exception as exc:
        clicked=driver is not None and driver.phase in {'select_sticker_once','observe_outgoing_sticker'}
        value={'ok':False,'sent':False,'chat':args.chat,'sticker_id':args.sticker,
               'status':'uncertain' if clicked else 'not_sent','retry_allowed':False,
               'phase':driver.phase if driver else 'initialize','error':str(exc)}
    print(json.dumps(value,ensure_ascii=False))
    return 0 if value.get('ok') else 1


if __name__=='__main__':
    raise SystemExit(main())
