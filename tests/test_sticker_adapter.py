import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image,ImageDraw

APP=Path(__file__).parents[1]/'app'
sys.path.insert(0,str(APP))
spec=importlib.util.spec_from_file_location('sticker_adapter',APP/'sticker_adapter.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)


class StickerTests(unittest.TestCase):
    def test_repeated_sticker_append_requires_crossing_a_unique_existing_anchor(self):
        before=Image.new('RGB',(1280,800),(30,30,31));after=before.copy()
        ImageDraw.Draw(before).rectangle((1080,300,1210,330),fill=(149,236,105))
        ImageDraw.Draw(after).rectangle((1080,350,1210,380),fill=(149,236,105))
        old=[{'bounds':[1072,100,132,132]}];new=[{'bounds':[1072,512,132,132]}]
        self.assertTrue(s.ordered_sticker_append(before,after,old,new))
        self.assertFalse(s.ordered_sticker_append(before,after,old,[{'bounds':[1072,200,132,132]}]))

    def test_scrolled_thumbnail_is_located_by_picture_and_rejects_wrong_picture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            first=Image.new('RGB',(72,72),(210,30,90));ImageDraw.Draw(first).rectangle((15,15,50,50),fill=(20,240,60))
            second=Image.new('RGB',(72,72),(20,40,230))
            first.save(root/'first.png');second.save(root/'second.png')
            entries=[{'id':'S01','template':'first.png','calibration_bounds':[118,619,72,72]},
                     {'id':'S02','template':'second.png','calibration_bounds':[118,531,72,72]}]
            catalog={'entries':entries,'layout':{'viewport_top':294,'viewport_bottom':700}}
            screen=Image.new('RGB',(1280,800),(30,30,30));screen.paste(first,(118,512))
            found=s.locate_thumbnail(screen,entries[0],first,catalog,root)
            self.assertEqual(found['bounds'],[118,512,72,72])
            with self.assertRaises(s.AdapterError):
                s.locate_thumbnail(screen,entries[1],second,catalog,root)

    def test_outgoing_confirmation_matches_image_and_excludes_avatar_column(self):
        image=Image.new('RGB',(1280,800),(30,30,30))
        reference=Image.new('RGB',(100,100),(220,40,140))
        image.paste(reference.resize((132,132)),(1072,512))
        self.assertEqual(len(s.outgoing_matches(image,reference)),1)
        other=Image.new('RGB',(100,100),(50,190,20))
        self.assertEqual(s.outgoing_matches(image,other),[])


if __name__=='__main__':unittest.main()
