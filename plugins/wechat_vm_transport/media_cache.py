"""Conservative visual cache reuse; no language inference or memory replacement."""
import io,json
from PIL import Image,ImageChops

def feature(data):
    image=Image.open(io.BytesIO(data)).convert('RGB')
    background=Image.new('RGB',image.size,image.getpixel((0,0)))
    mask=ImageChops.difference(image,background).convert('L').point(lambda p:255 if p>24 else 0)
    box=mask.getbbox()
    if box:image=image.crop(box)
    return image.resize((24,24)).tobytes()

def valid(caption):
    try:return json.loads(caption).get('caption_schema')=='literal_v2'
    except (TypeError,ValueError):return False

def lookup(db,digest,data):
    exact=db.execute('SELECT caption FROM captions WHERE hash=?',(digest,)).fetchone()
    if exact and valid(exact[0]):return exact[0]
    target=feature(data);scores=[]
    for raw,caption in db.execute('SELECT f.feature,c.caption FROM features f JOIN captions c ON c.hash=f.hash'):
        if len(raw)!=len(target) or not valid(caption):continue
        error=sum(abs(a-b) for a,b in zip(raw,target))/len(target)
        scores.append((error,caption))
    scores.sort()
    if scores and scores[0][0]<=3 and (len(scores)==1 or scores[1][0]-scores[0][0]>=1.5 or scores[1][1]==scores[0][1]):return scores[0][1]
    return None
