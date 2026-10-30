#!/usr/bin/env python3
"""Screenshot fallback for WeChat's collapsed AX renderer.

Reads only the visible window. Sending stays locked until a live spare-account
profile is created; account/avatar, exact title, empty draft and outgoing bubble
are checked around each send. No WeChat database or app files are accessed.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import subprocess
import time
import unicodedata

from baguette_config import load_config
from guest_adapter import AdapterError, MacWeChat, normalize_title, observed_send, readiness_status


def compact(text):
    punctuation=str.maketrans({'？':'?','！':'!','（':'(', '）':')','，':',','。':'.','：':':','；':';'})
    return re.sub(r'\s+', '', text.translate(punctuation))


def own_ocr_key(text):
    """Only for our own bubbles after exact native composer readback.

    Vision confuses uppercase I with lowercase l in the rendered token AI.
    Never apply this spelling tolerance to received messages or chat titles.
    """
    return compact(unicodedata.normalize('NFKC', text).translate(str.maketrans({'—':'-', '–':'-', '−':'-', '’':"'", '‘':"'", '“':'\"', '”':'\"'}))).replace('Al', 'AI').replace('A1', 'AI')


def ordered_text_append(before, after, text):
    """Prove an exact new own bubble after a unique previous final anchor.

    Incoming messages may arrive after our send. Their presence must not make a
    successfully appended own bubble look unsent. A viewport/count change alone
    is insufficient: the previous final row must still occur exactly once.
    """
    key=lambda m:(m.get('sender'), own_ocr_key(m.get('text','')) if m.get('sender')=='ME' else compact(m.get('text','')))
    if not before or not after:return False
    previous=[key(m) for m in before];current=[key(m) for m in after]
    anchor=previous[-1]
    if previous.count(anchor)!=1 or current.count(anchor)!=1:return False
    index=current.index(anchor)
    return any(key(m)==('ME',own_ocr_key(text)) for m in after[index+1:])


def recognize(image):
    import Foundation
    import Vision
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    raw = buffer.getvalue()
    data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)  # accurate, including Chinese
    request.setRecognitionLanguages_(['zh-Hans', 'en-US'])
    request.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise AdapterError('Local OCR failed; no text was inferred')
    lines = []
    for observation in request.results() or []:
        choices = observation.topCandidates_(1)
        if not choices:
            continue
        candidate = choices[0]
        box = observation.boundingBox()
        lines.append({'text': str(candidate.string()), 'confidence': float(candidate.confidence()),
                      'bounds': [float(box.origin.x)*image.width,
                                 (1-float(box.origin.y)-float(box.size.height))*image.height,
                                 float(box.size.width)*image.width,
                                 float(box.size.height)*image.height]})
    return sorted(lines, key=lambda line: (round(line['bounds'][1]/5), line['bounds'][0]))


def components(image, split=300, body_top=55, body_bottom=None):
    """Find filled gray incoming and green outgoing bubbles in the dark theme."""
    width, height = image.size
    body_bottom = body_bottom or height-145
    pixels = image.load()
    eligible = {}
    for y in range(body_top, body_bottom):
        for x in range(split+45, width-45):
            r, g, b = pixels[x, y][:3]
            if max(r, g, b)-min(r, g, b) <= 4 and 40 <= r <= 62:
                eligible[(x, y)] = 'OTHER'
            elif g > 90 and g > r*1.18 and g > b*1.15:
                eligible[(x, y)] = 'ME'
    rectangles = []
    while eligible:
        start, side = eligible.popitem()
        stack = [start]
        count = 0
        minx = maxx = start[0]
        miny = maxy = start[1]
        while stack:
            x, y = stack.pop()
            count += 1
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
            for p in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if eligible.get(p) == side:
                    eligible.pop(p)
                    stack.append(p)
        w, h = maxx-minx+1, maxy-miny+1
        aligned = (split+45 <= minx <= split+85) if side == 'OTHER' else (45 <= width-maxx <= 85)
        if aligned and w >= 22 and h >= 19 and count/(w*h) >= .35:
            rectangles.append({'sender': side, 'bounds': [minx, miny, w, h]})
    return sorted(rectangles, key=lambda row: row['bounds'][1])


def inside(line, rect, tolerance=1):
    x, y, w, h = line['bounds']
    rx, ry, rw, rh = rect
    return x >= rx-tolerance and y >= ry-tolerance and x+w <= rx+rw+tolerance and y+h <= ry+rh+tolerance


def bubble_pixel_rows(image):
    """Compare complete visible bubble images when OCR of an old row jitters."""
    rows = []
    for row in components(image):
        x,y,w,h = row['bounds']
        if y <= 55 or y+h >= image.height-145:
            continue
        crop = image.crop((x,y,x+w,y+h))
        digest = hashlib.sha256(str(crop.size).encode()+crop.tobytes()).hexdigest()
        rows.append({'sender':row['sender'],'text':digest})
    return rows


def current_title(lines, width, split=300):
    candidates = [line['text'] for line in lines
                  if split+8 < line['bounds'][0] < split+160
                  and 8 < line['bounds'][1] < 43
                  and (line['confidence'] >= .85 or line.get('region_confirmed') is True)]
    return candidates[0] if len(candidates) == 1 else None


def selected_group_avatar(image):
    """Fingerprint the selected sidebar avatar, excluding unread-count badges."""
    runs=[]; start=None
    for y in range(45,image.height-20):
        r,g,b=image.getpixel((65,y))[:3]
        selected=g>100 and r<50 and g>b*1.15
        if selected and start is None:start=y
        if not selected and start is not None:
            if 48<=y-start<=85:runs.append((start,y))
            start=None
    if len(runs)!=1:return None
    top,bottom=runs[0]
    crop=image.crop((74,top+26,104,top+46)).convert('RGB')
    return hashlib.sha256(crop.tobytes()).hexdigest()


def incoming_media(image,lines,result,original=None):
    """Capture unread image/emoji rows anchored to actual incoming avatars."""
    from PIL import Image,ImageChops,ImageFilter
    width,height=image.size;limit=height-145
    anchors=[]
    for side,left in [('OTHER',322),('ME',width-56)]:
        start=None
        for y in range(55,limit):
            bg=image.getpixel((310,y))[:3]
            count=sum(max(abs(image.getpixel((x,y))[i]-bg[i]) for i in range(3))>35
                      for x in range(left,left+30))
            if count>=15 and start is None:start=y
            if count<15 and start is not None:
                if 22<=y-start<=42:anchors.append((start,side))
                start=None
    anchors.sort();added=[];replaced=set()
    text_rows=result['messages']
    rects=components(image)
    for pos,(top,side) in enumerate(anchors):
        if side!='OTHER':continue
        end=min(anchors[pos+1][0]-6 if pos+1<len(anchors) else limit,limit)
        if any(m['sender']=='OTHER' and top<=m['bounds']['y']<end for m in text_rows):continue
        body=top+(22 if result['chat_type']=='group' else 0)
        if end-body<20:continue
        region=image.crop((365,body,min(width-95,930),end)).convert('RGB')
        bg=image.getpixel((310,body))[:3]
        mask=ImageChops.difference(region,Image.new('RGB',region.size,bg)).convert('L').point(lambda p:255 if p>24 else 0)
        # Separate left-aligned media from disconnected timestamps/rename notices.
        small=mask.resize((max(1,mask.width//2),max(1,mask.height//2))).filter(ImageFilter.MaxFilter(5))
        pending={(x,y) for y in range(small.height) for x in range(small.width) if small.getpixel((x,y))>100}
        boxes=[]
        while pending:
            x,y=pending.pop();stack=[(x,y)];xs=[x];ys=[y]
            while stack:
                px,py=stack.pop()
                for point in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                    if point in pending:
                        pending.remove(point);stack.append(point);xs.append(point[0]);ys.append(point[1])
            box=(min(xs)*2,min(ys)*2,min(mask.width,(max(xs)+1)*2),min(mask.height,(max(ys)+1)*2))
            if box[0]<=60 and box[2]-box[0]>=28 and box[3]-box[1]>=28:boxes.append(box)
        if not boxes:continue
        box=max(boxes,key=lambda b:(b[2]-b[0])*(b[3]-b[1]))
        x0,y0,x1,y1=box
        # Do not reinterpret a floating timestamp or another speaker as media.
        if x0>60:continue
        bounds=[365+max(0,x0-3),body+max(0,y0-3),min(region.width,x1+3)-max(0,x0-3),min(region.height,y1+3)-max(0,y0-3)]
        crop=image.crop((bounds[0],bounds[1],bounds[0]+bounds[2],bounds[1]+bounds[3]))
        native_ocr=''
        if original is not None:
            sx,sy=original.width/image.width,original.height/image.height
            crop=original.crop((round(bounds[0]*sx),round(bounds[1]*sy),round((bounds[0]+bounds[2])*sx),round((bounds[1]+bounds[3])*sy)))
            cache_path=Path.home()/'baguette/runtime/media-ocr-cache.json'
            crop_key=hashlib.sha256(str(crop.size).encode()+crop.tobytes()).hexdigest()
            try:ocr_cache=json.loads(cache_path.read_text())
            except (OSError,ValueError):ocr_cache={}
            if crop_key in ocr_cache:reads=ocr_cache[crop_key]
            else:
                reads=recognize(crop);ocr_cache[crop_key]=reads
                if len(ocr_cache)>128:ocr_cache=dict(list(ocr_cache.items())[-128:])
                cache_path.parent.mkdir(parents=True,exist_ok=True)
                cache_path.write_text(json.dumps(ocr_cache,ensure_ascii=False))
            native_ocr='\n'.join(l['text'] for l in reads if l['confidence']>=.85)[:2000]
        data=io.BytesIO();crop.save(data,format='PNG')
        labels=[l for l in lines if 365<l['bounds'][0]<700 and top-3<=l['bounds'][1]<body-2]
        name=labels[0]['text'] if labels else ''
        avatar=image.crop((319,top,355,top+36)).convert('RGB')
        added.append({'sender':'OTHER','sender_name':name,'sender_avatar_hash':hashlib.sha256(avatar.tobytes()).hexdigest(),
                      'text':'[图片/表情]','kind':'image','image_base64':base64.b64encode(data.getvalue()).decode(),
                      'image_mime':'image/png','image_ocr':native_ocr,'image_ambiguous':bool(y1>=region.height-1),
                      'bounds':dict(zip(('x','y','width','height'),bounds)),
                      'uncertainties':['visible_screenshot_crop_not_original_media','animation_current_frame_only']})
        for skipped in result['skipped']:
            row=skipped['row']
            if row<len(rects) and top<=rects[row]['bounds'][1]<end:replaced.add(row)
    if not added:return result
    merged=[(m['bounds']['y'],True,m) for m in text_rows+added]
    merged += [(rects[s['row']]['bounds'][1],False,s) for s in result['skipped'] if s['row'] not in replaced and s['row']<len(rects)]
    result['messages']=[];result['skipped']=[]
    for index,(_,known,item) in enumerate(sorted(merged,key=lambda x:x[0])):
        if known:item['row_index']=index;result['messages'].append(item)
        else:item['row']=index;result['skipped'].append(item)
    result['media_capture']={'captured':len(added),'source':'visible avatar-anchored crops','original_files':False}
    return result


def recognize_frame(original, logical_size, split=300):
    """Confirm low-confidence small text with a separate, tightly cropped read."""
    width, height = logical_size
    sx, sy = original.width/width, original.height/height
    image = original.resize(logical_size)
    lines = [{**line, 'bounds': [line['bounds'][0]/sx, line['bounds'][1]/sy,
                                 line['bounds'][2]/sx, line['bounds'][3]/sy]}
             for line in recognize(original)]
    regions = [([split+8, 8, width-145-(split+8), 37], False)]
    regions += [(row['bounds'], row['sender'] == 'ME') for row in components(image, split)]
    for rect, own in regions:
        included = [line for line in lines if inside(line, rect, 2)]
        if included and all(line['confidence'] >= .85 for line in included):
            continue
        x, y, w, h = rect
        crop = original.crop((round(x*sx), round(y*sy), round((x+w)*sx), round((y+h)*sy)))
        reread = recognize(crop)
        if not included:
            padded=original.crop((round((x-2)*sx),round((y-2)*sy),round((x+w+2)*sx),round((y+h+2)*sy)))
            confirmation=recognize(padded)
            key=own_ocr_key if own else compact
            if reread and key(''.join(l['text'] for l in reread))==key(''.join(l['text'] for l in confirmation)):
                for line in reread:
                    lines.append({**line,'bounds':[x+line['bounds'][0]/sx,y+line['bounds'][1]/sy,
                                                   line['bounds'][2]/sx,line['bounds'][3]/sy],
                                  'region_confirmed':True})
            continue
        first = compact(''.join(line['text'] for line in included))
        second = compact(''.join(line['text'] for line in reread))
        if first and (first == second or (own and own_ocr_key(first) == own_ocr_key(second))):
            for line in included:
                line['region_confirmed'] = True
    return image, lines


def history_tip_close_target(dialog, main_bounds, lines):
    """Dismiss only the observed nonmodal import-history tip, never other dialogs."""
    if dialog.get('subrole') != 'AXDialog' or dialog.get('modal') is not False:
        return None
    bounds = dialog.get('bounds')
    if not bounds:
        return None
    x, y, w, h = bounds
    mx, my, mw, mh = main_bounds
    if not (mx+mw-430 <= x <= mx+mw-300 and my <= y <= my+60
            and 350 <= w <= 420 and 60 <= h <= 100):
        return None
    label = compact(''.join(line['text'] for line in lines)).removesuffix('×').removesuffix('X')
    if label != compact('Click here to import more chat history from phone'):
        return None
    return [x+w-55, y+h/2-7, 14, 14]


def recognize_send_controls(original, logical_size, include_sent=False):
    """Read the title/composer and final own bubbles without rereading old chat."""
    width,height=logical_size
    sx,sy=original.width/width,original.height/height
    image=original.resize(logical_size)
    lines=[]
    regions=[([308,8,width-145-308,37],False),([width-105,height-55,100,50],False)]
    if include_sent:
        regions += [(r['bounds'],True) for r in components(image) if r['sender']=='ME'][-2:]
    for rect,own in regions:
        x,y,w,h=rect
        crop=original.crop((round(x*sx),round(y*sy),round((x+w)*sx),round((y+h)*sy)))
        read=recognize(crop)
        if (y==8 or own) and any(line['confidence'] < .85 for line in read):
            padded=original.crop((round((x-2)*sx),round((y-2)*sy),round((x+w+2)*sx),round((y+h+2)*sy)))
            second=recognize(padded)
            key=own_ocr_key if own else compact
            confirmed=bool(read and key(''.join(l['text'] for l in read))==key(''.join(l['text'] for l in second)))
        else:confirmed=False
        for line in read:
            lines.append({**line,'bounds':[x+line['bounds'][0]/sx,y+line['bounds'][1]/sy,
                                           line['bounds'][2]/sx,line['bounds'][3]/sy],
                          'region_confirmed':confirmed})
    return image,lines


def parse_frame(image, lines, expected_chat, split=300):
    width, height = image.size
    title = current_title(lines, width, split)
    if title is None or normalize_title(title) != expected_chat:
        raise AdapterError('Exact visible chat title was not verified by OCR')
    if max(image.getpixel((width-12, 70))[:3]) > 75:
        raise AdapterError('Visual adapter is calibrated for the dark WeChat theme')
    messages, skipped = [], []
    is_group = bool(re.search(r'[（(]\d+[）)]$',title.strip()))
    for index, row in enumerate(components(image, split)):
        rect = row['bounds']
        bubble_lines = [line for line in lines if inside(line, rect, 2)]
        accepted = [line for line in bubble_lines
                    if line['confidence'] >= .85 or line.get('region_confirmed') is True]
        if len(accepted) != len(bubble_lines):
            skipped.append({'row': index, 'reason': 'incomplete_or_inconsistent_bubble_ocr'})
            continue
        texts = [line['text'] for line in accepted]
        text = '\n'.join(texts)
        crop = image.crop((rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3]))
        pixels = crop.load()
        colorful = sum(max(pixels[x, y])-min(pixels[x, y]) > 35
                       for y in range(crop.height) for x in range(crop.width))/max(1, crop.width*crop.height)
        if (not text or (row['sender'] == 'OTHER' and colorful > .02)
                or any(marker in compact(text) for marker in ('邀请你加入群聊', '邀请你加入了群聊'))):
            skipped.append({'row': index, 'reason': 'unsupported_media_or_unreadable_bubble'})
            continue
        key = own_ocr_key(text) if row['sender'] == 'ME' else compact(text)
        fingerprint = hashlib.sha256(json.dumps([row['sender'], key], ensure_ascii=False).encode()).hexdigest()
        sender_name = None
        avatar_hash = ''
        if is_group and row['sender'] == 'OTHER':
            labels = [line for line in lines if split+60 < line['bounds'][0] < split+400
                      and rect[1]-32 < line['bounds'][1] < rect[1]-3
                      and line['bounds'][1]+line['bounds'][3] <= rect[1]+2]
            if labels:
                label=max(labels,key=lambda line:line['bounds'][1])
                sender_name=label['text']
            avatar=image.crop((319,max(55,rect[1]-22),355,max(55,rect[1]-22)+36))
            avatar_hash=hashlib.sha256(avatar.tobytes()).hexdigest()
        messages.append({'sender': row['sender'], 'sender_name': sender_name, 'text': text,
                         'sender_avatar_hash':avatar_hash,
                         'kind': 'text', 'row_index': index, 'fingerprint': fingerprint,
                         'bounds': dict(zip(('x', 'y', 'width', 'height'), rect)),
                         'uncertainties': ['local_screenshot_ocr_with_region_confirmation', 'sender_from_bubble_color_and_alignment',
                                           'no_stable_message_id', 'visible_text_only']})
    if is_group:
        events=[]
        for line in lines:
            if not (split+100<line['bounds'][0]<width-100 and 55<line['bounds'][1]<height-145):
                continue
            match=re.fullmatch(r'["“](.+?)["”]\s*拍了拍\s*["“]'+re.escape(load_config()['bot_id'])+r'["”]',line['text'].strip())
            if match:
                events.append({'sender':'OTHER','sender_name':match.group(1),'text':'@'+load_config()['bot_id']+' [拍了拍我]',
                               'kind':'nudge','bounds':dict(zip(('x','y','width','height'),line['bounds'])),
                               'uncertainties':['sender_from_visible_system_notice','no_stable_message_id']})
        if events:
            positions={i:r['bounds'][1] for i,r in enumerate(components(image,split))}
            merged=[(m['bounds']['y'],True,m) for m in messages]+[(positions[s['row']],False,s) for s in skipped]
            merged += [(e['bounds']['y'],True,e) for e in events]
            messages=[];skipped=[]
            for i,(_,known,item) in enumerate(sorted(merged,key=lambda p:p[0])):
                if known:item['row_index']=i;messages.append(item)
                else:item['row']=i;skipped.append(item)
    return {'ok': True, 'chat': expected_chat, 'verified_chat': True,
            'chat_type':'group' if is_group else 'private',
            'messages': messages, 'skipped': skipped,
            'delivery_capabilities': {'text': True, 'images': False, 'stickers': False},
            'uncertainties': ['dark_theme_calibration', 'visible_text_only',
                              'media_and_group_sender_names_not_supported', 'live_send_not_yet_validated']}


class VisualWeChat:
    def __init__(self):
        self.ui = MacWeChat()
        self.profile_path = Path.home()/'baguette/runtime/visual-profile.json'
        self.send_phase = 'initializing'

    def matches_chat(self,image,lines,chat):
        title=current_title(lines,image.width)
        if not title:return False
        try:profile=json.loads(self.profile_path.read_text())
        except (OSError,ValueError,AttributeError):profile={}
        binding=profile.get('group_bindings',{}).get(chat)
        if binding:
            return (binding.get('owner_confirmed') is True
                    and bool(re.search(r'[（(]\d+[）)]$',title.strip()))
                    and selected_group_avatar(image)==binding.get('avatar_sha256'))
        return normalize_title(title)==chat

    def parse_chat(self,image,lines,chat,media=False):
        if not self.matches_chat(image,lines,chat):
            raise AdapterError('Bound chat identity was not verified')
        visible=normalize_title(current_title(lines,image.width))
        result=parse_frame(image,lines,visible)
        result.update(chat=chat,visible_title=visible)
        if media:result=incoming_media(image,lines,result,getattr(self,'_original_frame',None))
        return result

    def frame(self, scope='full'):
        from PIL import ImageGrab
        self.ui.activate()
        tree = self.ui.tree()
        window = [n for n in tree.get('children', []) if n.get('role') == 'AXWindow'
                  and n.get('bounds') and n['bounds'][2] >= 850 and n['bounds'][3] >= 600]
        if len(window) != 1:
            raise AdapterError('Window geometry unavailable')
        if not bool(self.ui.get(window[0]['_ref'], 'AXFullScreen')):
            self.ui.set_value(window[0], 'AXFullScreen', True)
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                time.sleep(.2)
                tree = self.ui.tree()
                window = [n for n in tree.get('children', []) if n.get('role') == 'AXWindow'
                          and n.get('bounds') and n['bounds'][2] >= 850 and n['bounds'][3] >= 600]
                if len(window) == 1 and bool(self.ui.get(window[0]['_ref'], 'AXFullScreen')):
                    break
            else:
                raise AdapterError('WeChat did not enter the required full-screen mode')
        x, y, w, h = window[0]['bounds']
        # Hover tooltips create extra AX windows and can obscure text. Park the
        # pointer in the blank chat header before taking every observation.
        event = self.ui.Q.CGEventCreateMouseEvent(None, self.ui.Q.kCGEventMouseMoved,
                                                 (x+min(w-180, 700), y+20), 0)
        self.ui.Q.CGEventPost(self.ui.Q.kCGHIDEventTap, event)
        time.sleep(.15)
        windows = self.ui.get(self.ui.ax, 'AXWindows') or []
        if len(windows) != 1:
            # This transient nonmodal tip has no AX children and was previously
            # mistaken for a modal dialog. Confirm its exact pixels before closing.
            tree = self.ui.tree()
            extras = [n for n in tree.get('children', []) if n.get('role') == 'AXWindow'
                      and n.get('bounds') != window[0]['bounds']]
            if len(extras) == 1:
                extra = extras[0]
                extra = {**extra, 'subrole': self.ui.get(extra['_ref'], 'AXSubrole'),
                         'modal': self.ui.get(extra['_ref'], 'AXModal')}
                screen = ImageGrab.grab().convert('RGB')
                display = self.ui.Q.CGDisplayBounds(self.ui.Q.CGMainDisplayID())
                sx, sy = screen.width/display.size.width, screen.height/display.size.height
                ex, ey, ew, eh = extra.get('bounds', [0,0,0,0])
                crop = screen.crop((round(ex*sx),round(ey*sy),round((ex+ew)*sx),round((ey+eh)*sy)))
                target = history_tip_close_target(extra, [x,y,w,h], recognize(crop))
                if target:
                    self.ui.click({'bounds': target})
                    time.sleep(.25)
            if len(self.ui.get(self.ui.ax, 'AXWindows') or []) != 1:
                raise AdapterError('A popup or dialog is covering WeChat')
        screen = ImageGrab.grab().convert('RGB')
        display = self.ui.Q.CGDisplayBounds(self.ui.Q.CGMainDisplayID())
        sx, sy = screen.width/display.size.width, screen.height/display.size.height
        original = screen.crop((round(x*sx), round(y*sy), round((x+w)*sx), round((y+h)*sy)))
        if max(original.resize((round(w),round(h))).getpixel((round(w)-12,70))[:3])>200:
            try:profile=json.loads(self.profile_path.read_text())
            except (OSError,ValueError):profile={}
            if profile.get('force_dark_appearance') is True and not getattr(self,'_theme_retry',False):
                self._theme_retry=True
                try:
                    subprocess.run(['/usr/bin/osascript','-e','tell application "System Events" to tell appearance preferences to set dark mode to true'],
                                   check=True,capture_output=True,timeout=6)
                    time.sleep(.4)
                    return self.frame(scope=scope)
                finally:self._theme_retry=False
        self._original_frame=original
        if scope=='full':
            image=original.resize((round(w),round(h)))
            digest=hashlib.sha256(image.crop((0,0,image.width,image.height-145)).tobytes()).hexdigest()
            cache_path=Path.home()/'baguette/runtime/frame-ocr-cache.json'
            try:cached=json.loads(cache_path.read_text())
            except (OSError,ValueError):cached={}
            if cached.get('version')==4 and cached.get('digest')==digest and cached.get('pid')==self.ui.app.processIdentifier():
                lines=cached['lines']
            else:
                image, lines = recognize_frame(original, (round(w), round(h)))
                cache_path.write_text(json.dumps({'version':4,'digest':digest,'pid':self.ui.app.processIdentifier(),'lines':lines},ensure_ascii=False))
        else:
            image, lines = recognize_send_controls(original,(round(w),round(h)),include_sent=scope=='sent')
        return image, lines, [x, y, w, h]

    def ensure_chat(self, chat, scope='full'):
        image, lines, bounds = self.frame(scope=scope)
        if self.matches_chat(image,lines,chat):
            return image, lines, bounds
        try:binding=json.loads(self.profile_path.read_text()).get('group_bindings',{}).get(chat)
        except (AttributeError,OSError,ValueError):binding=None
        if binding and binding.get('owner_confirmed') is True:
            rows=[y for y in range(52,image.height-90,65)
                  if hashlib.sha256(image.crop((74,y+26,104,y+46)).convert('RGB').tobytes()).hexdigest()==binding.get('avatar_sha256')]
            if len(rows)!=1:raise AdapterError('Bound group avatar is not uniquely visible in the sidebar')
            self.ui.click({'bounds':[bounds[0]+140,bounds[1]+rows[0]+20,80,20]})
            for attempt in range(4):
                image,lines,bounds=self.frame(scope=scope)
                if self.matches_chat(image,lines,chat):return image,lines,bounds
                if attempt<3:time.sleep(.35)
            raise AdapterError('Selected group binding did not match')
        if scope!='full':
            return self.ensure_chat(chat)
        def matches_label(label):
            label=re.sub(r'\s+\d{1,2}:\d{2}\s*$','',label)
            if label==chat:return True
            if label.endswith(('…','...')):
                prefix=label.rstrip('.…').strip()
                return len(prefix)>=6 and chat.startswith(prefix)
            return False
        matches = [line for line in lines if matches_label(line['text'])
                   and 105 < line['bounds'][0] < 280 and line['bounds'][1] > 55]
        if len(matches) != 1:
            raise AdapterError('Open the exact chat manually; no guessed search or selection')
        x, y, w, h = matches[0]['bounds']
        if matches[0]['confidence'] < .85:
            from PIL import ImageGrab
            original = ImageGrab.grab().convert('RGB')
            display = self.ui.Q.CGDisplayBounds(self.ui.Q.CGMainDisplayID())
            sx,sy=original.width/display.size.width,original.height/display.size.height
            crop=original.crop((round((bounds[0]+x-3)*sx),round((bounds[1]+y-3)*sy),
                                round((bounds[0]+x+w+4)*sx),round((bounds[1]+y+h+3)*sy)))
            if compact(' '.join(line['text'] for line in recognize(crop))) != compact(matches[0]['text']):
                raise AdapterError('The sidebar chat name could not be independently confirmed')
        self.ui.click({'bounds': [bounds[0]+x, bounds[1]+y, w, h]})
        image, lines, bounds = self.frame()
        if not self.matches_chat(image,lines,chat):
            raise AdapterError('Selected chat title did not match')
        return image, lines, bounds

    def snapshot(self, chat):
        image, lines, _ = self.ensure_chat(chat)
        self.verify_binding(image, chat)
        return self.parse_chat(image,lines,chat,media=True)

    def verify_binding(self, image, chat):
        if not self.profile_path.is_file():
            raise AdapterError('Visual sending is locked pending live spare-account verification')
        profile = json.loads(self.profile_path.read_text())
        avatar = image.crop((12, 52, 48, 88)).resize((24, 24)).convert('RGB')
        digest = hashlib.sha256(avatar.tobytes()).hexdigest()
        if (profile.get('spare_account_verified') is not True
                or chat not in profile.get('allowed_chats', [])
                or profile.get('avatar_sha256') != digest
                or profile.get('window_size') != list(image.size)
                or profile.get('wechat_pid') != self.ui.app.processIdentifier()):
            raise AdapterError('Spare account/session/chat binding is absent or changed')

    @staticmethod
    def draft_lines(lines, width, height):
        return [line for line in lines if 315 < line['bounds'][0] < width-15
                and height-140 < line['bounds'][1] < height-45]

    @staticmethod
    def draft_is_empty(image, lines):
        if VisualWeChat.draft_lines(lines, image.width, image.height):
            return False
        # Also preserve symbols/images OCR cannot read. Only a narrow green
        # insertion caret is allowed in the otherwise uniform dark composer.
        pixels = image.load()
        background = pixels[image.width-25, image.height-70]
        foreground, green_columns = 0, set()
        for y in range(image.height-132, image.height-48):
            for x in range(318, image.width-22):
                r, g, b = pixels[x, y][:3]
                if max(abs(r-background[0]), abs(g-background[1]), abs(b-background[2])) <= 30:
                    continue
                if g > 90 and g > r*1.3 and g > b*1.3:
                    green_columns.add(x)
                else:
                    foreground += 1
                if foreground > 6 or len(green_columns) > 2:
                    return False
        return True

    def paste(self, text):
        app = self.ui.AppKit
        board = app.NSPasteboard.generalPasteboard()
        previous = []
        for item in board.pasteboardItems() or []:
            previous.append({str(t): item.dataForType_(t) for t in item.types()})
        board.clearContents()
        board.setString_forType_(text, app.NSPasteboardTypeString)
        version = board.changeCount()
        try:
            for down in (True, False):
                event = self.ui.Q.CGEventCreateKeyboardEvent(None, 9, down)
                self.ui.Q.CGEventSetFlags(event, self.ui.Q.kCGEventFlagMaskCommand)
                self.ui.Q.CGEventPost(self.ui.Q.kCGHIDEventTap, event)
            time.sleep(.35)
        finally:
            if board.changeCount() == version:
                board.clearContents()
                items = []
                for values in previous:
                    item = app.NSPasteboardItem.alloc().init()
                    for kind, data in values.items():
                        if data is not None:
                            item.setData_forType_(data, kind)
                    items.append(item)
                if items:
                    board.writeObjects_(items)

    def read_composer(self, bounds):
        """Use the app's native Copy for exact draft readback, not OCR spelling."""
        app, quartz = self.ui.AppKit, self.ui.Q
        self.ui.click({'bounds': [bounds[0]+330, bounds[1]+bounds[3]-125, 100, 40]})
        board = app.NSPasteboard.generalPasteboard()
        previous = [{str(t): item.dataForType_(t) for t in item.types()}
                    for item in board.pasteboardItems() or []]
        sentinel = 'baguette-copy-check-' + str(time.time_ns())
        board.clearContents()
        board.setString_forType_(sentinel, app.NSPasteboardTypeString)
        version = board.changeCount()
        restore_version = version
        try:
            for key in (0, 8):  # Cmd+A, Cmd+C in the guest's US keyboard layout
                for down in (True, False):
                    event = quartz.CGEventCreateKeyboardEvent(None, key, down)
                    quartz.CGEventSetFlags(event, quartz.kCGEventFlagMaskCommand)
                    quartz.CGEventPost(quartz.kCGHIDEventTap, event)
                time.sleep(.15)
            deadline = time.monotonic()+2
            while time.monotonic() < deadline:
                restore_version = board.changeCount()
                value = board.stringForType_(app.NSPasteboardTypeString)
                if restore_version != version and value is not None and str(value) != sentinel:
                    return str(value).replace('\r\n', '\n')
                time.sleep(.1)
            raise AdapterError('Composer Copy did not return text; draft retained')
        finally:
            if board.changeCount() == restore_version:
                board.clearContents()
                items = []
                for values in previous:
                    item = app.NSPasteboardItem.alloc().init()
                    for kind, data in values.items():
                        if data is not None:
                            item.setData_forType_(data, kind)
                    items.append(item)
                if items:
                    board.writeObjects_(items)

    def send(self, chat, payload):
        self.send_phase = 'validate_payload'
        text = payload.get('text')
        if (payload.get('expected_chat') != chat or not isinstance(text, str) or not 1 <= len(text) <= 500
                or any(ord(c) < 32 and c not in '\n\t' for c in text)):
            raise AdapterError('A bounded text and exact expected_chat are required')
        # Reading a newly updated Qt window can briefly fail. Retry observations
        # before typing; never retry paste or a Send click.
        last_error = None
        for attempt in range(3):
            try:
                self.send_phase = 'select_chat'
                image, lines, bounds = self.ensure_chat(chat,scope='full')
                self.verify_binding(image, chat)
                before = self.parse_chat(image, lines, chat)
                before['_bubble_pixels'] = bubble_pixel_rows(image)
                self.send_phase = 'check_empty_draft'
                if not self.draft_is_empty(image, lines):
                    raise AdapterError('Existing draft preserved; no send attempted')
                break
            except AdapterError as error:
                last_error = error
                if attempt == 2:
                    raise
                time.sleep(.25)
        self.ui.click({'bounds': [bounds[0]+330, bounds[1]+bounds[3]-125, 100, 40]})
        self.send_phase = 'paste'
        self.paste(text)
        return self.finish_draft(chat, text, before)

    def finish_draft(self, chat, text, before=None):
        """Finish only an exactly matching existing draft in the bound chat."""
        self.send_phase = 'verify_target'
        image, lines, bounds = self.frame(scope='controls')
        self.verify_binding(image, chat)
        if not self.matches_chat(image,lines,chat):
            raise AdapterError('Chat changed after paste; no send attempted')
        if before is None:
            before = self.parse_chat(image,lines,chat)
        self.send_phase = 'copy_draft'
        draft = self.read_composer(bounds)
        if draft != text.replace('\r\n', '\n'):
            raise AdapterError('Composer Copy did not match the requested text exactly; draft retained')
        self.send_phase = 'locate_send'
        image, lines, bounds = self.frame(scope='controls')
        self.verify_binding(image, chat)
        if not self.matches_chat(image,lines,chat) or not self.ui.app.isActive():
            raise AdapterError('Target changed before Send; draft retained')
        buttons = [line for line in lines if line['text'] in {'Send', '发送', '傳送'}
                   and line['bounds'][0] > image.width-100 and line['bounds'][1] > image.height-55]
        if len(buttons) != 1:
            raise AdapterError('Visible Send button could not be verified; draft retained')
        x, y, w, h = buttons[0]['bounds']
        # Exactly one send attempt. Uncertain outcomes are never retried.
        self.send_phase = 'press_send'
        self.ui.click({'bounds': [bounds[0]+x, bounds[1]+y, w, h]})
        self.send_phase = 'observe_bubble'
        for attempt in range(3):
            time.sleep(.3)
            try:
                image, lines, _ = self.frame(scope='sent' if attempt==0 else 'full')
                self.verify_binding(image, chat)
                after = self.parse_chat(image,lines,chat)
            except AdapterError:
                continue
            normalized = lambda rows: [{**row, 'text': own_ocr_key(row['text']) if row['sender'] == 'ME' else compact(row['text'])} for row in rows]
            pixel_rows = bubble_pixel_rows(image)
            prior_pixels=before.get('_bubble_pixels',[])
            complete_append=bool(prior_pixels and len(pixel_rows)==len(prior_pixels)+1
                                 and pixel_rows[:-1]==prior_pixels and pixel_rows[-1]['sender']=='ME')
            pixel_verified = bool(pixel_rows and before.get('_bubble_pixels') and
                (observed_send(before['_bubble_pixels'],pixel_rows,pixel_rows[-1]['text']) or complete_append))
            exact_tail = bool(after['messages'] and after['messages'][-1]['sender'] == 'ME'
                              and own_ocr_key(after['messages'][-1]['text']) == own_ocr_key(text))
            text_append = ordered_text_append(before.get('messages',[]),after['messages'],text)
            if ((text_append or (exact_tail and
                    (observed_send(normalized(before['messages']), normalized(after['messages']), own_ocr_key(text)) or pixel_verified)))
                    and self.draft_is_empty(image, lines)):
                return {'ok': True, 'chat': chat, 'verified_chat': True, 'sent': True,
                        'status': 'observed', 'retry_allowed': False,
                        'uncertainties': ['own_bubble_observed_recipient_delivery_unconfirmed']}
        return {'ok': False, 'chat': chat, 'verified_chat': True, 'sent': False,
                'status': 'uncertain', 'retry_allowed': False, 'error': 'Outgoing bubble was not verified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('chats')
    for name in ('snapshot', 'send', 'sticker'):
        sub.add_parser(name).add_argument('--chat', required=True)
    args = parser.parse_args()
    sending = False
    try:
        if args.command == 'status':
            result = readiness_status()
            result.update(adapter='visual_ocr', live_send_verified=False)
        else:
            adapter = VisualWeChat()
            if args.command == 'chats':
                image, lines, _ = adapter.frame()
                title = current_title(lines, image.width)
                if not title:
                    raise AdapterError('No exact current chat title; login/selection required')
                result = {'ok': True, 'chats': [{'name': normalize_title(title), 'duplicate_name': False}],
                          'uncertainties': ['currently_open_chat_only']}
            elif args.command == 'snapshot':
                result = adapter.snapshot(args.chat)
            elif args.command == 'sticker':
                from sticker_adapter import execute_sticker
                payload = json.loads(sys.stdin.read(16385))
                result = execute_sticker(args.chat, payload)
                receipt=Path.home()/'baguette/runtime/last-sticker-send.json'
                receipt.parent.mkdir(parents=True,exist_ok=True)
                receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            else:
                payload = json.loads(sys.stdin.read(16385))
                sending = True
                result = adapter.send(args.chat, payload)
    except Exception as error:
        phase=getattr(locals().get('adapter'),'send_phase','initializing')
        attempted=sending and phase in {'press_send','observe_bubble'}
        result = {'ok': False, 'chat': getattr(args, 'chat', None), 'verified_chat': False,
                  'sent': False, 'status': 'uncertain' if attempted else 'not_sent',
                  'retry_allowed': False, 'error': str(error),
                  'phase': phase}
    if args.command == 'send':
        receipt = Path.home()/'baguette/runtime/last-adapter-send.json'
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
