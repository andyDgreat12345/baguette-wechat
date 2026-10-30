"""Synthetic tree/image tests. These never import PyObjC or touch WeChat."""
import base64
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "app" / "guest_adapter.py"
SPEC = importlib.util.spec_from_file_location("guest_adapter", MODULE)
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)


def node(role="AXStaticText", text="", identifier="", bounds=None, children=None):
    value = {"role": role, "value": text, "identifier": identifier, "children": children or []}
    if bounds is not None:
        value["bounds"] = bounds
    return value


def bubble(text, y=80, side="left", sender=None, image=False):
    x = 30 if side == "left" else 600
    children = [node("AXImage" if image else "AXStaticText", text, bounds=[x, y, 150, 60])]
    content = node("AXGroup", identifier="message_bubble", bounds=[x, y, 150, 60], children=children)
    row_children = [content]
    if sender:
        row_children.append(node(text=sender, identifier="sender_name", bounds=[x, y - 15, 80, 14]))
    return node("AXRow", bounds=[0, y - 20, 800, 100], children=row_children)


def tree(rows, label="消息", title="朋友群（3）"):
    return node("AXApplication", children=[node(text=title, identifier="big_title_line_h_view"), node("AXList", text=label, bounds=[0, 40, 800, 600], children=rows)])


class ParsingTests(unittest.TestCase):
    def test_non_mac_readiness_does_not_import_or_activate_wechat(self):
        with patch.object(guest.sys, "platform", "linux"):
            result = guest.readiness_status()
        self.assertFalse(result["ok"])
        self.assertEqual(result["login"], "unknown")
        self.assertFalse(result["app_running"])

    def test_multilingual_titles_and_unicode_faces_survive(self):
        for label in ("Messages", "消息", "訊息", "聊天消息"):
            result = guest.parse_snapshot(tree([bubble("哈哈😂 [旺柴] 笑死我了", sender="小林")], label), "朋友群")
            message = result["messages"][0]
            self.assertEqual(message["text"], "哈哈😂 [旺柴] 笑死我了")
            self.assertEqual(message["sender"], "OTHER")
            self.assertEqual(message["sender_name"], "小林")
            self.assertNotIn("message_id", message)

    def test_anonymous_group_member_remains_explicitly_anonymous(self):
        message = guest.parse_snapshot(tree([bubble("来了")]), "朋友群")["messages"][0]
        self.assertIsNone(message["sender_name"])
        self.assertIn("member_name_not_exposed_by_accessibility", message["uncertainties"])

    def test_ambiguous_center_and_partial_bubbles_are_skipped(self):
        centered = node("AXStaticText", "unclear", bounds=[330, 90, 140, 20])
        clipped = bubble("partially visible", y=625)
        result = guest.parse_snapshot(tree([centered, clipped]), "朋友群")
        self.assertEqual(result["messages"], [])
        self.assertEqual(len(result["skipped"]), 2)

    def test_conflicting_sender_names_are_not_guessed(self):
        row = bubble("消息", sender="甲")
        row["children"].append(node(text="乙", identifier="member_name", bounds=[50, 65, 50, 10]))
        result = guest.parse_snapshot(tree([row]), "朋友群")
        self.assertEqual(result["skipped"][0]["reason"], "conflicting_sender_names")

    def test_unknown_or_conflicting_chat_title_fails_closed(self):
        with self.assertRaises(guest.AdapterError):
            guest.parse_snapshot(tree([bubble("hello")]), "另一群")
        fixture = tree([bubble("hello")])
        fixture["children"].append(node(text="另一群", identifier="chat_title"))
        with self.assertRaises(guest.AdapterError):
            guest.parse_snapshot(fixture, "朋友群")

    def test_row_order_and_uncertain_newer_message_are_preserved(self):
        timestamp = node(text="12:34", identifier="timestamp", bounds=[330, 50, 100, 20])
        ambiguous = node(text="new uncertain bubble", bounds=[330, 300, 140, 30])
        result = guest.parse_snapshot(tree([timestamp, bubble("hello"), ambiguous]), "朋友群")
        self.assertEqual(result["messages"][0]["row_index"], 1)
        self.assertEqual(result["skipped"], [{"row": 0, "reason": "non_message"}, {"row": 2, "reason": "bubble_side_ambiguous"}])

    def test_avatar_is_not_mistaken_for_sticker(self):
        row = node("AXRow", bounds=[0, 70, 800, 100], children=[node("AXImage", identifier="avatar", bounds=[5, 80, 25, 25]), node(text="普通文本", bounds=[35, 80, 140, 40])])
        message = guest.parse_snapshot(tree([row]), "朋友群")["messages"][0]
        self.assertEqual(message["kind"], "text")
        self.assertIsNone(message["image_base64"])

    def test_discovery_flags_duplicate_names_and_only_lists_sidebar(self):
        fixture = node("AXApplication", children=[node(identifier="session_item_小明", bounds=[0, 0, 100, 40]), node(identifier="session_item_小明", bounds=[0, 50, 100, 40]), node(text="不是会话")])
        result = guest.discover_chats(fixture)
        self.assertEqual(len(result["chats"]), 1)
        self.assertTrue(result["chats"][0]["duplicate_name"])

    def test_send_requires_new_own_bubble_not_existing_repeat(self):
        old = [{"sender": "OTHER", "text": "hello"}, {"sender": "ME", "text": "收到"}]
        self.assertFalse(guest.observed_send(old, old, "收到"))
        self.assertFalse(guest.observed_send(old, old + [{"sender": "OTHER", "text": "收到"}], "收到"))
        self.assertTrue(guest.observed_send(old, old + [{"sender": "ME", "text": "收到"}], "收到"))
        self.assertTrue(guest.observed_send(old, old + [{"sender": "ME", "text": "新的答复"}], "新的答复"))

    def test_viewport_only_change_or_mismatched_text_is_not_send_confirmation(self):
        old = [{"sender": "OTHER", "text": "anchor"}]
        self.assertFalse(guest.observed_send(old, [{"sender": "ME", "text": "hello"}, *old], "hello"))
        self.assertFalse(guest.observed_send(old, [*old, {"sender": "ME", "text": "different"}], "hello"))
        self.assertTrue(guest.observed_send(old, [*old, {"sender": "ME", "text": "hello"}], "hello"))


class ImageTests(unittest.TestCase):
    def test_media_crop_handles_retina_scaling_without_whole_screen_leak(self):
        from PIL import Image
        image = Image.new("RGB", (1600, 1200), "red")
        # Panel starts at logical y=40; crop y=100 -> pixel y=120.
        for x in range(60, 360):
            for y in range(120, 240):
                image.putpixel((x, y), (0, 255, 0))
        fixture = tree([bubble("[动画表情]", y=100, image=True)])
        message = guest.parse_snapshot(fixture, "朋友群", image)["messages"][0]
        decoded = Image.open(io.BytesIO(base64.b64decode(message["image_base64"])))
        self.assertEqual(decoded.size, (300, 120))
        self.assertEqual(decoded.getpixel((0, 0)), (0, 255, 0))
        self.assertEqual(message["kind"], "sticker")
        self.assertIn("screenshot_crop_not_original_media", message["uncertainties"])

    def test_media_without_screenshot_is_skipped(self):
        result = guest.parse_snapshot(tree([bubble("[图片]", image=True)]), "朋友群")
        self.assertFalse(result["messages"])
        self.assertIn("screenshot unavailable", result["skipped"][0]["reason"])


class FakeKeyboard:
    kCGHIDEventTap = 0

    def __init__(self):
        self.posted = []

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return {"code": code, "down": down}

    def CGEventSetFlags(self, event, flags):
        pass

    def CGEventPost(self, tap, event):
        self.posted.append(event)


class FakeApp:
    def isActive(self):
        return True


class FakeMac(guest.MacWeChat):
    def __init__(self, before=None, after=None, draft="", focus_works=True, change_chat=False):
        self.Q, self.app = FakeKeyboard(), FakeApp()
        self.composer = {"AXValue": draft, "AXFocused": False}
        self.before, self.after = before or [], after or []
        self.snapshots = 0
        self.trees = 0
        self.focus_works, self.change_chat = focus_works, change_chat

    def ensure_chat(self, chat):
        pass

    def snapshot_current(self, chat):
        self.snapshots += 1
        if self.snapshots > 1 and self.Q.posted:
            self.composer["AXValue"] = ""
        return {"messages": self.before if self.snapshots == 1 else self.after}

    def tree(self):
        self.trees += 1
        current = tree([], title="另一群" if self.change_chat and self.trees > 1 else "朋友群")
        field = node("AXTextArea", identifier="chat_input_field")
        field["_ref"] = self.composer
        current["children"].append(field)
        return current

    def set_value(self, node, attr, value):
        if attr != "AXFocused" or self.focus_works:
            node["_ref"][attr] = value

    def get(self, ref, attr):
        return ref.get(attr)


class SendingTests(unittest.TestCase):
    def test_existing_draft_is_preserved_without_keypress(self):
        adapter = FakeMac(draft="user draft")
        with self.assertRaises(guest.AdapterError):
            adapter.send("朋友群", {"text": "hello"})
        self.assertEqual(adapter.composer["AXValue"], "user draft")
        self.assertEqual(adapter.Q.posted, [])

    def test_focus_or_target_change_prevents_keypress(self):
        for kwargs in ({"focus_works": False}, {"change_chat": True}):
            adapter = FakeMac(**kwargs)
            with self.assertRaises(guest.AdapterError):
                adapter.send("朋友群", {"text": "hello"})
            self.assertEqual(adapter.Q.posted, [])

    def test_unobserved_send_is_uncertain_and_never_retries_return(self):
        adapter = FakeMac()
        with patch.object(guest.time, "sleep"):
            result = adapter.send("朋友群", {"text": "hello"})
        self.assertFalse(result["sent"])
        self.assertEqual(result["status"], "uncertain")
        self.assertFalse(result["retry_allowed"])
        self.assertEqual([e["down"] for e in adapter.Q.posted], [True, False])

    def test_new_own_matching_bubble_is_required_for_sent(self):
        baseline = [{"sender": "OTHER", "text": "new chat first hi"}]
        adapter = FakeMac(before=baseline, after=[*baseline, {"sender": "ME", "text": "hello"}])
        with patch.object(guest.time, "sleep"):
            result = adapter.send("朋友群", {"text": "hello", "expected_chat": "朋友群"})
        self.assertTrue(result["sent"])
        self.assertEqual(result["status"], "observed")

    def test_mismatched_expected_chat_never_touches_composer(self):
        adapter = FakeMac()
        with self.assertRaises(guest.AdapterError):
            adapter.send("朋友群", {"text": "hello", "expected_chat": "别的群"})
        self.assertEqual(adapter.composer["AXValue"], "")
        self.assertEqual(adapter.Q.posted, [])


if __name__ == "__main__":
    unittest.main()
