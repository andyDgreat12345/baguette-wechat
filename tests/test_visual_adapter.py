import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

APP = Path(__file__).parents[1]/'app'
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location('visual_adapter', APP/'visual_adapter.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


def line(text, bounds, confidence=1, **extra):
    return {'text': text, 'bounds': bounds, 'confidence': confidence, **extra}


class VisualTests(unittest.TestCase):
    def test_disconnected_rename_notice_is_not_part_of_an_incoming_image(self):
        image=Image.new('RGB',(1280,800),(30,30,31));d=ImageDraw.Draw(image)
        d.rectangle((319,100,354,135),fill='white')
        d.rectangle((375,127,380,139),fill='white')
        d.rectangle((650,170,900,181),fill=(140,140,140))
        result=v.incoming_media(image,[],{'messages':[],'skipped':[],'chat_type':'group'})
        self.assertEqual(result['messages'],[])

    def test_confirmed_group_binding_survives_rename_but_rejects_another_avatar(self):
        image=Image.new('RGB',(1280,800),(30,30,31));d=ImageDraw.Draw(image)
        d.rectangle((60,52,299,116),fill=(0,156,102));d.rectangle((74,78,103,97),fill=(220,60,140))
        digest=v.selected_group_avatar(image)
        adapter=v.VisualWeChat.__new__(v.VisualWeChat)
        with tempfile.TemporaryDirectory() as temporary:
            adapter.profile_path=Path(temporary)/'profile.json'
            import json
            adapter.profile_path.write_text(json.dumps({'group_bindings':{'original':{'owner_confirmed':True,'avatar_sha256':digest}}}))
            lines=[line('renamed (18)',[316,20,200,18])]
            self.assertTrue(adapter.matches_chat(image,lines,'original'))
            d.rectangle((74,78,103,97),fill=(40,160,230))
            self.assertFalse(adapter.matches_chat(image,lines,'original'))
            self.assertFalse(adapter.matches_chat(image,[line('renamed',[316,20,200,18])],'original'))

    def test_incoming_sticker_crop_is_anchored_to_sender_and_contains_pixels(self):
        image=Image.new('RGB',(1280,800),(30,30,31));d=ImageDraw.Draw(image)
        d.rectangle((319,100,354,135),fill='white')
        d.rectangle((370,122,500,230),fill=(220,60,140))
        result=v.incoming_media(image,[line('Member',[370,102,70,14])],{'messages':[],'skipped':[],'chat_type':'group'})
        self.assertEqual(len(result['messages']),1)
        message=result['messages'][0]
        self.assertEqual(message['sender_name'],'Member')
        self.assertEqual(message['sender'],'OTHER')
        self.assertTrue(message['image_base64'])
        self.assertFalse(message['image_ambiguous'])

    def test_only_known_nonmodal_history_tip_can_be_dismissed(self):
        dialog={'subrole':'AXDialog','modal':False,'bounds':[917,30,387,86]}
        label=[line('Click here to import more chat history from phone',[24,35,320,18])]
        self.assertEqual(v.history_tip_close_target(dialog,[0,0,1280,800],label),[1249,66.0,14,14])
        self.assertIsNone(v.history_tip_close_target({**dialog,'modal':True},[0,0,1280,800],label))
        self.assertIsNone(v.history_tip_close_target(dialog,[0,0,1280,800],[line('Confirm transfer',[24,35,320,18])]))
        self.assertIsNone(v.history_tip_close_target({**dialog,'bounds':[500,300,387,86]},[0,0,1280,800],label))

    def test_confident_full_frame_text_does_not_need_duplicate_crop_reads(self):
        high=[line('Test contact',[315,20,95,18]),line('Incoming',[380,110,80,18]),line('Outgoing',[670,170,80,18])]
        with patch.object(v,'recognize',return_value=high) as recognize:
            image,lines=v.recognize_frame(self.image,self.image.size)
        recognize.assert_called_once()
        self.assertEqual(lines,high)

    def test_punctuation_confirmation_normalizes_only_width_variants(self):
        self.assertEqual(v.compact('？'),v.compact('?'))
        self.assertNotEqual(v.compact('2²'),v.compact('22'))
        self.assertNotEqual(v.compact('Al'),v.compact('AI'))

    def test_nudge_to_bound_account_is_a_directed_group_event(self):
        image=Image.new('RGB',(1280,800),(30,30,31))
        lines=[line('Example group (18)',[316,20,200,18]),
               line('"Member" 拍了拍 "baguette"',[716,600,150,15],confidence=.3)]
        result=v.parse_frame(image,lines,'Example group')
        self.assertEqual(result['chat_type'],'group')
        self.assertEqual(result['messages'][0]['sender_name'],'Member')
        self.assertIn('@baguette',result['messages'][0]['text'])

    def test_truncated_sidebar_name_with_merged_time_requires_exact_opened_title(self):
        adapter=v.VisualWeChat.__new__(v.VisualWeChat)
        adapter.ui=Mock()
        image=Image.new('RGB',(1280,800),(30,30,31))
        sidebar=[line('Example gr... 04:52',[117,260,173,15])]
        opened=[line('Example group (18)',[316,20,200,18])]
        adapter.frame=Mock(side_effect=[(image,sidebar,[0,0,1280,800]),(image,opened,[0,0,1280,800])])
        result=adapter.ensure_chat('Example group')
        self.assertEqual(result[1],opened)
        adapter.ui.click.assert_called_once()

    def test_own_ai_glyph_tolerance_does_not_accept_changed_numbers_or_words(self):
        self.assertEqual(v.own_ocr_key("Tell me — I’m here."),v.own_ocr_key("Tell me - I'm here."))
        self.assertEqual(v.own_ocr_key('我是 AI 伙伴。'), v.own_ocr_key('我是 Al伙伴。'))
        self.assertNotEqual(v.own_ocr_key('Take 1 tablet'), v.own_ocr_key('Take 2 tablets'))
        self.assertNotEqual(v.own_ocr_key('Hello Andy'), v.own_ocr_key('Hello Bob'))

    def test_new_incoming_after_our_reply_does_not_hide_success(self):
        before=[{'sender':'OTHER','text':'@baguette interpret this'}]
        after=before+[{'sender':'ME','text':'It looks surprised.'},{'sender':'OTHER','text':'send a sticker'}]
        self.assertTrue(v.ordered_text_append(before,after,'It looks surprised.'))
        self.assertFalse(v.ordered_text_append(before,after,'A different reply'))

    def test_scroll_or_duplicate_anchor_cannot_prove_a_send(self):
        old={'sender':'ME','text':'Same reply'};anchor={'sender':'OTHER','text':'question'}
        self.assertFalse(v.ordered_text_append([old,anchor],[old,anchor],'Same reply'))
        self.assertFalse(v.ordered_text_append([anchor,anchor],[anchor,old],'Same reply'))
        self.assertFalse(v.ordered_text_append([anchor],[old],'Same reply'))

    def test_system_notification_at_right_is_not_a_second_chat_title(self):
        lines=[line('free (17)',[316,20,80,18]),line('App Background Activity',[980,22,180,18])]
        self.assertEqual(v.current_title(lines,1280),'free (17)')

    def setUp(self):
        self.image = Image.new('RGB', (880, 640), (30, 30, 31))
        draw = ImageDraw.Draw(self.image)
        draw.rounded_rectangle((365, 100, 480, 140), 5, fill=(47, 47, 48))
        draw.rounded_rectangle((650, 160, 815, 200), 5, fill=(149, 236, 105))
        self.lines = [line('Test contact', [315, 20, 95, 18]),
                      line('Incoming', [380, 110, 80, 18]),
                      line('Outgoing', [670, 170, 80, 18]),
                      line('Yesterday 12:30', [530, 65, 120, 16])]

    def test_bubble_alignment_and_color_separate_sides_and_ignore_system_label(self):
        result = v.parse_frame(self.image, self.lines, 'Test contact')
        self.assertEqual([(m['sender'], m['text']) for m in result['messages']],
                         [('OTHER', 'Incoming'), ('ME', 'Outgoing')])

    def test_wrong_or_ambiguous_title_is_rejected(self):
        with self.assertRaises(v.AdapterError):
            v.parse_frame(self.image, self.lines, 'Someone else')
        with self.assertRaises(v.AdapterError):
            v.parse_frame(self.image, self.lines+[line('Second title', [430, 20, 95, 18])], 'Test contact')

    def test_low_confidence_header_requires_matching_cropped_read(self):
        self.lines[0]['confidence'] = .3
        with self.assertRaises(v.AdapterError):
            v.parse_frame(self.image, self.lines, 'Test contact')
        self.lines[0]['region_confirmed'] = True
        self.assertTrue(v.parse_frame(self.image, self.lines, 'Test contact')['verified_chat'])

    def test_media_card_is_skipped_rather_than_treated_as_a_text_message(self):
        draw = ImageDraw.Draw(self.image)
        draw.rectangle((410, 108, 465, 135), fill=(200, 80, 15))
        result = v.parse_frame(self.image, self.lines, 'Test contact')
        self.assertEqual([m['sender'] for m in result['messages']], ['ME'])
        self.assertEqual(result['skipped'][0]['reason'], 'unsupported_media_or_unreadable_bubble')

    def test_partial_ocr_does_not_turn_a_card_into_a_complete_text_message(self):
        self.lines.append(line('unconfirmed second line', [380, 128, 80, 10], confidence=.3))
        result = v.parse_frame(self.image, self.lines, 'Test contact')
        self.assertEqual([m['sender'] for m in result['messages']], ['ME'])
        self.assertEqual(result['skipped'][0]['reason'], 'incomplete_or_inconsistent_bubble_ocr')

    def test_unbound_account_cannot_click_or_paste(self):
        adapter = v.VisualWeChat.__new__(v.VisualWeChat)
        adapter.ui = Mock()
        adapter.ensure_chat = Mock(return_value=(self.image, self.lines, [200, 80, 880, 640]))
        adapter.paste = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            adapter.profile_path = Path(temporary)/'absent.json'
            with self.assertRaises(v.AdapterError):
                adapter.send('Test contact', {'expected_chat': 'Test contact', 'text': 'Hello'})
        adapter.ui.click.assert_not_called()
        adapter.paste.assert_not_called()

    def test_unbound_snapshot_cannot_return_chat_messages(self):
        adapter = v.VisualWeChat.__new__(v.VisualWeChat)
        adapter.ui = Mock()
        adapter.ensure_chat = Mock(return_value=(self.image, self.lines, [0, 0, 880, 640]))
        with tempfile.TemporaryDirectory() as temporary:
            adapter.profile_path = Path(temporary)/'absent.json'
            with self.assertRaises(v.AdapterError):
                adapter.snapshot('Test contact')

    def test_existing_draft_cannot_be_overwritten(self):
        adapter = v.VisualWeChat.__new__(v.VisualWeChat)
        adapter.ui = Mock()
        adapter.verify_binding = Mock()
        lines = self.lines+[line('An existing draft', [330, 530, 150, 20])]
        adapter.ensure_chat = Mock(return_value=(self.image, lines, [200, 80, 880, 640]))
        adapter.paste = Mock()
        with self.assertRaises(v.AdapterError):
            adapter.send('Test contact', {'expected_chat': 'Test contact', 'text': 'Hello'})
        adapter.ui.click.assert_not_called()
        adapter.paste.assert_not_called()

    def test_transient_read_is_retried_before_exactly_one_paste(self):
        adapter = v.VisualWeChat.__new__(v.VisualWeChat)
        adapter.ui = Mock()
        adapter.verify_binding = Mock()
        adapter.ensure_chat = Mock(side_effect=[v.AdapterError('Transient window read'),
                                               (self.image,self.lines,[0,0,880,640])])
        adapter.paste = Mock()
        adapter.finish_draft = Mock(return_value={'sent':True})
        with patch.object(v.time, 'sleep'):
            result = adapter.send('Test contact', {'expected_chat':'Test contact','text':'Hello'})
        self.assertTrue(result['sent'])
        adapter.paste.assert_called_once_with('Hello')
        adapter.ui.click.assert_called_once()

    def test_unreadable_draft_pixels_are_preserved_but_caret_is_allowed(self):
        draw = ImageDraw.Draw(self.image)
        draw.rectangle((320, 520, 321, 538), fill=(0, 170, 95))
        self.assertTrue(v.VisualWeChat.draft_is_empty(self.image, self.lines))
        draw.rectangle((350, 530, 360, 542), fill=(200, 200, 200))
        self.assertFalse(v.VisualWeChat.draft_is_empty(self.image, self.lines))


if __name__ == '__main__':
    unittest.main()
