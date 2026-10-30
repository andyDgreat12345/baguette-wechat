import importlib.util
import json
import io
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"app"))
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('astrbot_backend', Path(__file__).parents[1] / 'app/astrbot_backend.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


def stream(*events):
    return [b'data: ' + json.dumps(event).encode() + b'\n' for event in events]


class AstrBotBackendTests(unittest.TestCase):
    def test_native_group_sticker_intent_reaches_bridge_without_fake_send_text(self):
        import io
        from unittest.mock import Mock
        model=b.AstrBotModel(Path('/unused'));model._token='local-test';model._token_time=time.monotonic()
        payload={'status':'ok','data':{'outputs':[{'type':'plain','data':'[已选好 S35 并提交给微信端发送]'}],'sticker_id':'S35','completed':True}}
        model.opener=Mock();model.opener.open.return_value=io.BytesIO(json.dumps(payload).encode())
        self.assertEqual(model.reply('Example group',[{'text':'@baguette 晚安，回个表情','sender_name':'Member'}]),'[SILENT]')
        self.assertEqual(model.selected_sticker,'S35')

    def test_batch_submits_once_with_original_sender_context(self):
        from unittest.mock import Mock
        model=b.AstrBotModel(Path('/unused'));model._token='local-test';model._token_time=time.monotonic()
        model.opener=Mock();model.opener.open.return_value=io.BytesIO(json.dumps({'status':'ok','data':{'outputs':[{'type':'plain','data':'final reply'}]}}).encode())
        self.assertEqual(model.reply('Example group',[{'text':'@baguette send a sticker','sender_name':'first'},{'text':'@baguette come back','sender_name':'second'}]),'final reply')
        model.opener.open.assert_called_once()
        payload=json.loads(model.opener.open.call_args.args[0].data)
        self.assertIn('first: @baguette send a sticker',payload['text'])
        self.assertEqual(payload['sender']['name'],'second')
        self.assertIsNone(model.selected_sticker)

    def test_active_group_mode_does_not_require_mentions(self):
        model=b.AstrBotModel(Path('/unused'));model.participation_mode='active'
        self.assertFalse(model.is_passive('Example group',[{'text':'hello everyone','sender_name':'member'}]))
        model.participation_mode='directed'
        self.assertTrue(model.is_passive('Example group',[{'text':'hello everyone','sender_name':'member'}]))

    def test_still_visible_prior_image_is_attached_to_following_interpretation(self):
        from unittest.mock import Mock
        model=b.AstrBotModel(Path('/unused'));model._token='test';model._token_time=time.monotonic()
        model.observe_visible_context('Example group',[{'sender':'OTHER','text':'[image]','image_base64':'actual-visible-crop','at':0}])
        model.opener=Mock();model.opener.open.return_value=io.BytesIO(json.dumps({'status':'ok','data':{'outputs':[{'type':'plain','data':'Visible description'}]}}).encode())
        self.assertEqual(model.reply('Example group',[{'text':'@baguette interpret this sticker'}]),'Visible description')
        payload=json.loads(model.opener.open.call_args.args[0].data)
        self.assertEqual(payload['images'],['actual-visible-crop'])
        self.assertEqual(payload['coverage']['image_role'],'currently_visible_prior_context')

    def test_sticker_only_request_suppresses_preface_but_keeps_selected_action(self):
        from unittest.mock import Mock
        model=b.AstrBotModel(Path('/unused'));model._token='test';model._token_time=time.monotonic()
        model.opener=Mock();model.opener.open.return_value=io.BytesIO(json.dumps({'status':'ok','data':{'outputs':[{'type':'plain','data':'Here you go.'}],'sticker_id':'S04'}}).encode())
        self.assertEqual(model.reply('Example group',[{'text':'@baguette send a sticker'}]),'[SILENT]')
        self.assertEqual(model.selected_sticker,'S04')
        self.assertFalse(model.sticker_only_request('@baguette explain this sticker'))
        self.assertFalse(model.sticker_only_request('@baguette say hello and send a sticker'))

    def test_invalid_native_group_sticker_intent_is_rejected(self):
        import io
        from unittest.mock import Mock
        model=b.AstrBotModel(Path('/unused'));model._token='local-test';model._token_time=time.monotonic()
        model.opener=Mock();model.opener.open.return_value=io.BytesIO(json.dumps({'status':'ok','data':{'outputs':[],'sticker_id':'S99'}}).encode())
        with self.assertRaises(b.AstrBotBackendError):
            model.reply('Example group',[{'text':'@baguette sticker','sender_name':'Member'}])

    def test_direct_follow_up_does_not_require_repeating_the_bot_name(self):
        model=b.AstrBotModel(Path('/unused'))
        chat='Example group'
        self.assertFalse(model.is_passive(chat,[{'text':'@baguette hello','sender_name':'Member'}]))
        model._group_attention[chat]=(('Member',None),time.monotonic())
        self.assertFalse(model.is_passive(chat,[{'text':'Speak English','sender_name':'Member','sender_avatar_hash':'abc'}]))
        self.assertTrue(model.is_passive(chat,[{'text':'unrelated','sender_name':'someone else'}]))
        model._group_attention[chat]=(('Member',None),time.monotonic()-121)
        self.assertTrue(model.is_passive(chat,[{'text':'hello','sender_name':'Member'}]))

    def test_only_final_text_is_exposed(self):
        events = stream({'type': 'plain', 'chain_type': 'reasoning', 'data': 'private reasoning'},
                        {'type': 'plain', 'chain_type': 'tool_call', 'data': 'private arguments'},
                        {'type': 'plain', 'chain_type': 'tool_call_result', 'data': 'private memory'},
                        {'type': 'plain', 'chain_type': None, 'data': '你好。'}, {'type': 'end'})
        self.assertEqual(b.final_text(events, time.monotonic()+10), '你好。')

    def test_failed_or_truncated_runs_never_become_a_reply(self):
        for events in [stream({'type': 'plain', 'data': 'partial'}),
                       stream({'type': 'error', 'data': 'failed'}, {'type': 'end'}),
                       stream({'type': 'plain', 'data': 'LLM 响应错误: provider error'}, {'type': 'end'}),
                       stream({'type': 'end'})]:
            with self.subTest(events=events), self.assertRaises(b.AstrBotBackendError):
                b.final_text(events, time.monotonic()+10)

    def test_memory_session_is_stable_and_separated_by_chat(self):
        self.assertEqual(b.session_id('Owner'), b.session_id('Owner'))
        self.assertNotEqual(b.session_id('Owner'), b.session_id('another chat'))

    def test_sticker_intent_requires_the_matching_registered_tool_result(self):
        selection = {}
        events = stream(
            {'type':'plain','chain_type':'tool_call','data':json.dumps({'id':'one','name':'select_wechat_sticker'})},
            {'type':'plain','chain_type':'tool_call_result','data':json.dumps({'id':'one','result':json.dumps({'selected':True,'sticker_id':'S35'})})},
            {'type':'end'})
        self.assertEqual(b.final_text(events,time.monotonic()+10,selection),'')
        self.assertEqual(selection,{'sticker_id':'S35'})
        ignored = {}
        events = stream({'type':'plain','chain_type':'tool_call_result','data':json.dumps({'id':'unmatched','result':json.dumps({'selected':True,'sticker_id':'S35'})})},
                        {'type':'plain','data':'hello'},{'type':'end'})
        self.assertEqual(b.final_text(events,time.monotonic()+10,ignored),'hello')
        self.assertEqual(ignored,{})

    def test_unknown_sticker_tool_result_is_rejected(self):
        events = stream({'type':'plain','chain_type':'tool_call','data':json.dumps({'id':'one','name':'select_wechat_sticker'})},
                        {'type':'plain','chain_type':'tool_call_result','data':json.dumps({'id':'one','result':json.dumps({'selected':True,'sticker_id':'S99'})})},
                        {'type':'end'})
        with self.assertRaises(b.AstrBotBackendError):
            b.final_text(events,time.monotonic()+10,{})

    def test_reply_submits_only_fresh_input_once(self):
        model = b.AstrBotModel(Path('/unused'))
        with patch.object(model, '_chat', return_value='reply') as call:
            self.assertEqual(model.reply('Owner', [{'text': 'first'}, {'text': 'second'}]), 'reply')
            call.assert_called_once_with(b.session_id('Owner'), 'first\nsecond')

    def test_other_chats_cannot_reuse_owner_memory(self):
        model = b.AstrBotModel(Path('/unused'))
        with patch.object(model, '_chat') as call:
            for chat, pending in [('other', [{'text': 'hi'}]),
                                  ('other', [{'text': 'hi', 'image_base64': 'abc'}])]:
                with self.assertRaises(b.AstrBotBackendError):
                    model.reply(chat, pending)
            call.assert_not_called()

    def test_owner_images_use_native_media_pipeline(self):
        model=b.AstrBotModel(Path('/unused'));pending=[{'text':'image','image_base64':'abc'}]
        with patch.object(model,'_group_reply',return_value='understood') as native,patch.object(model,'_chat') as text:
            self.assertEqual(model.reply('Owner',pending),'understood')
            native.assert_called_once_with('Owner',pending,kind='private')
            text.assert_not_called()

    def test_diagnostics_have_separate_sessions(self):
        model = b.AstrBotModel(Path('/unused'))
        with patch.object(model, '_chat', return_value='ok') as call:
            model.complete([{'role': 'user', 'content': 'diagnostic'}])
            model.complete([{'role': 'user', 'content': 'diagnostic'}])
            ids = [args.args[0] for args in call.call_args_list]
            self.assertNotEqual(ids[0], ids[1])
            self.assertNotIn(b.session_id('Owner'), ids)

    def test_backend_rejects_remote_or_credential_urls(self):
        for url in ['https://example.com', 'http://127.0.0.1:6186/path',
                    'http://user:pass@127.0.0.1:6186', 'http://127.0.0.1:6186?query=1']:
            with self.subTest(url=url), self.assertRaises(b.AstrBotBackendError):
                b.AstrBotModel(Path('/unused'), url)

    def test_login_is_cached_so_fast_chat_does_not_hit_auth_rate_limit(self):
        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout):
                self.requests.append(request)
                if request.full_url.endswith('/api/auth/login'):
                    return io.BytesIO(json.dumps({'status':'ok','data':{'token':'dummy-local-token'}}).encode())
                payload = json.loads(request.data)
                assert payload['flags']['enable_streaming'] is False
                assert payload['flags']['enable_reasoning'] is False
                return io.BytesIO(b''.join(stream({'type':'plain','data':'ok'},{'type':'end'})))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'auth.json'
            path.write_text(json.dumps({'username':'owner','password':'dummy'}))
            model = b.AstrBotModel(path)
            model.opener = Opener()
            self.assertEqual(model.reply('Owner',[{'text':'first'}]),'ok')
            self.assertEqual(model.reply('Owner',[{'text':'second'}]),'ok')
            self.assertEqual(len(model.opener.requests),3)
            self.assertTrue(model.connected)


if __name__ == '__main__':
    unittest.main()
