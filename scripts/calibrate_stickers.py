"""Create a local 36-item reverse Favorites catalog from user-owned assets/screenshots."""
import argparse,json,shutil,sys
from pathlib import Path
from PIL import Image,ImageOps
BASE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(BASE/'app'))
from sticker_adapter import difference

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--top',type=Path,required=True);p.add_argument('--middle',type=Path,required=True);p.add_argument('--bottom',type=Path,required=True);p.add_argument('--confirm-reverse-order',action='store_true',required=True);a=p.parse_args()
 catalog=json.loads((a.source/'catalog.json').read_text());entries=catalog['entries']
 if sorted(e['id'] for e in entries)!=[f'S{i:02}' for i in range(1,37)]:raise SystemExit('This alpha requires exactly S01-S36')
 out=BASE/'runtime/stickers'
 if out.exists():raise SystemExit('Refusing to overwrite an existing calibration; move it aside first')
 shots={name:Image.open(getattr(a,name)).convert('RGB').resize((1280,800)) for name in ('top','middle','bottom')}
 references={}
 for e in entries:
  if not e.get('meaning') or not e.get('use_when') or 'avoid_when' not in e:raise SystemExit('Meaning/use_when/avoid_when required: '+e['id'])
  im=Image.open(a.source/'originals'/(e['id']+'.jpg')).convert('RGB');fit=ImageOps.contain(im,(72,72));canvas=Image.new('RGB',(72,72),(30,30,30));canvas.paste(fit,((72-fit.width)//2,(72-fit.height)//2));references[e['id']]=canvas
 results=[]
 for e in entries:
  pos=36-int(e['id'][1:]);row,col=divmod(pos,5);x=118+88*col;candidates=[]
  for name,im in shots.items():
   for dx in range(-2,3):
    for y in range(294,629):
     crop=im.crop((x+dx,y,x+dx+72,y+72));candidates.append((difference(crop,references[e['id']]),name,x+dx,y))
  error,name,x,y=min(candidates)
  if error>18:raise SystemExit('No reliable source match for '+e['id']+'; capture/review your screenshots')
  results.append((e,name,x,y,error,row,col))
 (out/'templates').mkdir(parents=True);shutil.copytree(a.source/'originals',out/'originals')
 for e,name,x,y,error,row,col in results:
  rel='templates/'+e['id']+'.png';shots[name].crop((x,y,x+72,y+72)).save(out/rel)
  e.update(template=rel,calibration_bounds=[x,y,72,72],wechat_position=37-int(e['id'][1:]),row=row,column=col,wechat_verified=True,reference_match_mean_error=round(error,3))
 catalog['layout']={'window_size':[1280,800],'columns':5,'cell_pitch':88,'first_x':118,'first_y':302,'cell_size':72,'viewport_top':294,'viewport_bottom':700,'popup_ax_bounds':[73,258,514,514],'open_button':[330,766],'favorites_button':[230,724]}
 (out/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
 print('Matched 36 thumbnails. Review all entries before sending; then run read-only locate for top and bottom IDs.')
if __name__=='__main__':main()
