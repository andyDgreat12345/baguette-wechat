#!/usr/bin/env python3
"""Guest-local WeChat UI bridge. No UI or macOS imports occur on import.

This adapter returns observations, never invents stable WeChat message/user IDs.
It is intentionally conservative when the Accessibility tree is incomplete.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import platform
import re
import sys
import time
from typing import Any


MESSAGE_LABELS = {"Messages", "消息", "訊息", "消息列表", "訊息列表", "聊天消息"}
SEARCH_LABELS = {"Search", "搜索", "搜尋"}
CONTACT_HEADERS = {"Contacts", "联系人", "聯絡人", "通讯录", "通訊錄"}
GROUP_HEADERS = {"Group Chats", "群聊", "群組聊天"}
OTHER_HEADERS = {"Chat History", "聊天记录", "聊天記錄", "Official Accounts", "公众号", "公眾號", "More", "更多", "Internet search results", "网络搜索", "網路搜尋"}
TITLE_IDS = {"big_title_line_h_view", "chat_title", "conversation_title"}
MESSAGE_IDS = {"message_list", "messages_list", "chat_message_list", "chat_messages"}
NAME_IDS = {"sender_name", "nickname", "member_name", "group_member_name", "message_sender"}
CONTENT_IDS = {"message_text", "message_content", "msg_content", "chat_text", "message_bubble", "bubble"}
AVATAR_IDS = {"avatar", "avatar_image", "head_image", "profile_picture"}
MEDIA_LABELS = {"[图片]", "[圖片]", "[Image]", "图片", "圖片", "Image", "[动画表情]", "[動畫表情]", "[表情]", "[Sticker]", "表情", "Sticker"}
TIME_RE = re.compile(r"^(?:\d{1,2}:\d{2}(?:\s?[AP]M)?|(?:今天|昨天|今日|昨日|星期.|周.|週.)\s*\d{1,2}:\d{2})$")


class AdapterError(RuntimeError):
    pass


def readiness_status() -> dict:
    """Check permission/app availability without opening, activating or reading chats."""
    result = {"ok": True, "platform": sys.platform, "macos": platform.mac_ver()[0],
              "accessibility": False, "screen_recording": False, "app_running": False,
              "login": "unknown", "account_identity": "not_inspected",
              "uncertainties": ["login_and_spare_account_not_verified", "no_chat_ui_inspected"]}
    if sys.platform != "darwin":
        result["ok"] = False
        result["error"] = "Guest adapter requires macOS"
        return result
    try:
        import AppKit
        import ApplicationServices as AS
        import Quartz as Q
        result["accessibility"] = bool(AS.AXIsProcessTrusted())
        result["screen_recording"] = bool(Q.CGPreflightScreenCaptureAccess())
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat")
        result["app_running"] = len(apps) == 1
        result["app_instances"] = len(apps)
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"Read-only runtime probe failed ({type(exc).__name__})"
    return result


def walk(node: dict):
    yield node
    for child in node.get("children", []):
        yield from walk(child)


def text_of(node: dict) -> str:
    for key in ("value", "title", "description"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_title(value: str) -> str:
    return re.sub(r"\s*[（(]\d+[）)]$", "", value.strip()).strip()


def exact_chat_title(tree: dict, requested: str) -> bool:
    titles = [text_of(n) for n in walk(tree) if n.get("identifier") in TITLE_IDS and text_of(n)]
    # Multiple different title nodes mean that another window/dialog may be open.
    unique = set(titles)
    return len(unique) == 1 and (requested in unique or {normalize_title(t) for t in unique} == {requested})


def chat_rows(tree: dict) -> list[dict]:
    return [n for n in walk(tree) if str(n.get("identifier", "")).startswith("session_item_") and n.get("role") in {"AXStaticText", "AXRow", "AXButton", "AXGroup"}]


def discover_chats(tree: dict) -> dict:
    rows = chat_rows(tree)
    by_name: dict[str, list[dict]] = {}
    for row in rows:
        name = row["identifier"][len("session_item_"):].strip()
        if name:
            by_name.setdefault(name, []).append(row)
    chats = []
    for name, matches in by_name.items():
        # A nested AX wrapper can repeat the identifier, so compare geometry too.
        distinct = {tuple(n.get("bounds", [])) for n in matches}
        labels = [text_of(n) for row in matches for n in walk(row)]
        unread = True if any(re.search(r"(?:\d+\s*(?:条未读|則未讀|unread)|未读|未讀)", label, re.I) for label in labels) else None
        chats.append({"name": name, "duplicate_name": len(distinct) > 1, "unread": unread})
    return {"ok": True, "chats": chats, "uncertainties": ["visible_sidebar_only", "display_names_are_not_stable_account_ids"]}


def find_message_list(tree: dict) -> dict:
    lists = [n for n in walk(tree) if n.get("role") == "AXList" and (n.get("identifier") in MESSAGE_IDS or text_of(n) in MESSAGE_LABELS)]
    if len(lists) != 1 or not lists[0].get("bounds"):
        raise AdapterError("Expected one unambiguous message list with screen bounds")
    return lists[0]


def rect_inside(rect: list[float], panel: list[float], tolerance: float = 2) -> bool:
    x, y, w, h = rect
    px, py, pw, ph = panel
    return w > 0 and h > 0 and x >= px - tolerance and y >= py - tolerance and x + w <= px + pw + tolerance and y + h <= py + ph + tolerance


def union_rect(rects: list[list[float]]) -> list[float]:
    x = min(r[0] for r in rects)
    y = min(r[1] for r in rects)
    return [x, y, max(r[0] + r[2] for r in rects) - x, max(r[1] + r[3] for r in rects) - y]


def media_crop(image: Any, panel: list[float], bounds: list[float]) -> tuple[str, str]:
    """Crop a screenshot with explicit logical-point to pixel scaling."""
    if image is None or not rect_inside(bounds, panel):
        raise AdapterError("Media is partially obscured or screenshot unavailable")
    px, py, pw, ph = panel
    x, y, w, h = bounds
    sx, sy = image.width / pw, image.height / ph
    box = (round((x - px) * sx), round((y - py) * sy), round((x + w - px) * sx), round((y + h - py) * sy))
    cropped = image.crop(box).convert("RGB")
    if min(cropped.size) < 8:
        raise AdapterError("Media crop too small to understand")
    cropped.thumbnail((640, 640))
    buffer = io.BytesIO()
    cropped.save(buffer, format="PNG")
    raw = buffer.getvalue()
    return base64.b64encode(raw).decode("ascii"), hashlib.sha256(raw).hexdigest()


def parse_message_row(row: dict, panel: list[float], image: Any = None) -> tuple[dict | None, str | None]:
    nodes = list(walk(row))
    # Only an explicit UI timestamp marker is benign. A user's text that happens
    # to look like a time must remain a message or an uncertain observation.
    if row.get("identifier") in {"message_time", "timestamp", "time_label", "unread_separator"}:
        return None, "non_message"
    names = {text_of(n) for n in nodes if n.get("identifier") in NAME_IDS and text_of(n)}
    if len(names) > 1:
        return None, "conflicting_sender_names"
    name = next(iter(names), None)
    content = [n for n in nodes if n.get("identifier") in CONTENT_IDS and n.get("bounds")]
    if not content:
        content = [n for n in nodes if not n.get("children") and n.get("bounds") and n.get("identifier") not in NAME_IDS | AVATAR_IDS and n.get("role") in {"AXStaticText", "AXTextArea", "AXImage"} and (text_of(n) or n.get("role") == "AXImage") and not TIME_RE.fullmatch(text_of(n))]
    if not content:
        if row.get("bounds") and text_of(row):
            content = [row]
        else:
            return None, "no_readable_bubble_content"
    bounds = union_rect([n["bounds"] for n in content])
    if not rect_inside(bounds, panel):
        return None, "partially_visible_bubble"
    # Full-width AX rows do not establish which side sent a message.
    px, _, pw, _ = panel
    middle = bounds[0] + bounds[2] / 2
    if bounds[2] > pw * .78:
        return None, "bubble_side_ambiguous"
    if middle < px + pw * .40:
        sender = "OTHER"
    elif middle > px + pw * .60:
        sender = "ME"
    else:
        return None, "bubble_side_ambiguous"
    texts = []
    for node in content:
        # Prefer leaf text to composite parent values that may repeat sender names.
        leaves = [n for n in walk(node) if not n.get("children") and n.get("identifier") not in NAME_IDS]
        for leaf in leaves or [node]:
            value = text_of(leaf)
            if value and value not in texts and not TIME_RE.fullmatch(value):
                texts.append(value)
    text = "\n".join(texts)
    has_image = any(n.get("role") == "AXImage" for n in content for n in walk(n))
    is_media = has_image or (text in MEDIA_LABELS)
    uncertainties = ["sender_side_from_bubble_geometry", "no_stable_message_or_sender_id"]
    if sender == "OTHER" and name is None:
        uncertainties.append("member_name_not_exposed_by_accessibility")
    if not text and not is_media:
        return None, "empty_bubble"
    encoded, digest = None, ""
    if is_media:
        try:
            encoded, digest = media_crop(image, panel, bounds)
        except AdapterError as exc:
            return None, str(exc)
        uncertainties.append("screenshot_crop_not_original_media")
    kind = "sticker" if is_media and any("表情" in t or "Sticker" in t for t in texts) else "image" if is_media else "text"
    fingerprint = hashlib.sha256(json.dumps([sender, name, kind, text, digest], ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"sender": sender, "sender_name": name, "text": text, "kind": kind, "bounds": dict(zip(("x", "y", "width", "height"), bounds)), "image_base64": encoded, "image_mime": "image/png" if encoded else None, "image_ambiguous": False, "fingerprint": fingerprint, "uncertainties": uncertainties}, None


def parse_snapshot(tree: dict, chat: str, image: Any = None) -> dict:
    if not exact_chat_title(tree, chat):
        raise AdapterError("Chat title could not be verified exactly")
    panel = find_message_list(tree)
    messages, skipped = [], []
    for index, row in enumerate(panel.get("children", [])):
        message, error = parse_message_row(row, panel["bounds"], image)
        if error:
            skipped.append({"row": index, "reason": error})
        elif message:
            message["row_index"] = index
            # Index/geometry are local observations, not stable server IDs.
            message["observation_id"] = hashlib.sha256(json.dumps([message["fingerprint"], index, message["bounds"]], sort_keys=True).encode()).hexdigest()
            messages.append(message)
    return {"ok": True, "chat": chat, "verified_chat": True, "messages": messages, "skipped": skipped, "uncertainties": ["visible_messages_only", "no_stable_message_ids", "desktop_ui_compatibility_requires_live_validation"], "delivery_capabilities": {"text": True, "images": False, "stickers": False}, "captured_at": datetime.now(timezone.utc).isoformat()}


def own_text_count(messages: list[dict], text: str) -> int:
    return sum(m.get("sender") == "ME" and m.get("text") == text for m in messages)


def observed_send(before: list[dict], after: list[dict], text: str) -> bool:
    # Count-only confirmation can mistake a viewport change for a new message.
    # Require one unique ordered overlap and an appended matching final bubble.
    def signature(item):
        return (item.get("sender"), item.get("sender_name"), item.get("text"), item.get("fingerprint"))
    previous, current = [signature(m) for m in before], [signature(m) for m in after]
    if not previous or not current:
        return False
    overlaps = [n for n in range(1, min(len(previous), len(current)) + 1) if previous[-n:] == current[:n]]
    if len(overlaps) != 1 or overlaps[0] >= len(current):
        return False
    if overlaps[0] == 1 and (previous.count(previous[-1]) != 1 or current.count(previous[-1]) != 1):
        return False
    return after[-1].get("sender") == "ME" and after[-1].get("text") == text and own_text_count(after, text) > own_text_count(before, text)


class MacWeChat:
    def __init__(self):
        if sys.platform != "darwin":
            raise AdapterError("Guest adapter requires macOS")
        import AppKit
        import ApplicationServices as AS
        import Quartz as Q
        self.AppKit, self.AS, self.Q = AppKit, AS, Q
        session = Q.CGSessionCopyCurrentDictionary() or {}
        if session.get('CGSSessionScreenIsLocked'):
            raise AdapterError("Guest screen is locked; unlock the VM session to resume visual control")
        if not AS.AXIsProcessTrusted():
            raise AdapterError("Accessibility permission is required for the guest terminal/runtime")
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat")
        if len(apps) != 1:
            raise AdapterError("Exactly one running guest WeChat app is required")
        self.app = apps[0]
        self.ax = AS.AXUIElementCreateApplication(self.app.processIdentifier())

    def get(self, ref, attribute):
        err, value = self.AS.AXUIElementCopyAttributeValue(ref, attribute, None)
        return value if err == 0 else None

    def tree(self) -> dict:
        remaining = [3500]
        def visit(ref, depth=0):
            remaining[0] -= 1
            if remaining[0] < 0 or depth > 24:
                raise AdapterError("Accessibility tree exceeded bounded capture limits")
            node = {"_ref": ref}
            for key, attr in (("role", "AXRole"), ("identifier", "AXIdentifier"), ("value", "AXValue"), ("title", "AXTitle"), ("description", "AXDescription")):
                value = self.get(ref, attr)
                if isinstance(value, str):
                    node[key] = value
            pos, size = self.get(ref, "AXPosition"), self.get(ref, "AXSize")
            if pos is not None and size is not None:
                try:
                    okp, p = self.AS.AXValueGetValue(pos, self.AS.kAXValueCGPointType, None)
                    oks, s = self.AS.AXValueGetValue(size, self.AS.kAXValueCGSizeType, None)
                    if okp and oks:
                        node["bounds"] = [float(p.x), float(p.y), float(s.width), float(s.height)]
                except (TypeError, ValueError, AttributeError):
                    pass
            node["children"] = [visit(c, depth + 1) for c in (self.get(ref, "AXChildren") or [])]
            return node
        return visit(self.ax)

    def activate(self):
        self.app.activateWithOptions_(self.AppKit.NSApplicationActivateIgnoringOtherApps)
        time.sleep(.20)

    def set_value(self, node: dict, attr: str, value):
        err = self.AS.AXUIElementSetAttributeValue(node["_ref"], attr, value)
        if err:
            raise AdapterError(f"Accessibility could not set {attr}: {err}")

    def click(self, node: dict):
        if not node.get("bounds"):
            raise AdapterError("Cannot select target without its bounds")
        x, y, w, h = node["bounds"]
        for kind in (self.Q.kCGEventLeftMouseDown, self.Q.kCGEventLeftMouseUp):
            event = self.Q.CGEventCreateMouseEvent(None, kind, (x + w / 2, y + h / 2), 0)
            self.Q.CGEventPost(self.Q.kCGHIDEventTap, event)
        time.sleep(.25)

    def ensure_chat(self, chat: str):
        if not chat.strip() or len(chat) > 200 or "\n" in chat:
            raise AdapterError("Invalid exact chat display name")
        self.activate()
        tree = self.tree()
        rows = [n for n in chat_rows(tree) if n["identifier"] == "session_item_" + chat]
        geometries = {tuple(n.get("bounds", [])) for n in rows}
        if len(geometries) > 1:
            raise AdapterError("Duplicate chat display names cannot be resolved safely")
        if exact_chat_title(tree, chat):
            return
        if rows:
            self.click(rows[0])
        else:
            searches = [n for n in walk(tree) if n.get("role") in {"AXTextArea", "AXTextField", "AXSearchField"} and (text_of(n) in SEARCH_LABELS or n.get("identifier") in {"search_field", "search_input"})]
            if len(searches) != 1:
                raise AdapterError("Cannot find one multilingual chat search field")
            self.set_value(searches[0], "AXFocused", True)
            self.set_value(searches[0], "AXValue", chat)
            time.sleep(.45)
            tree = self.tree()
            lists = [n for n in walk(tree) if n.get("identifier") == "search_list"]
            if len(lists) != 1:
                raise AdapterError("Search results not exposed; no guessed selection")
            entries = sorted([n for n in walk(lists[0]) if n.get("role") == "AXStaticText" and n.get("bounds")], key=lambda n: n["bounds"][1])
            section, matches = None, []
            for node in entries:
                label = text_of(node)
                if label in CONTACT_HEADERS | GROUP_HEADERS | OTHER_HEADERS:
                    section = label
                elif label == chat and section in CONTACT_HEADERS | GROUP_HEADERS:
                    matches.append(node)
            if len(matches) != 1:
                raise AdapterError("Chat search must resolve one exact contact/group name")
            self.click(matches[0])
        if not exact_chat_title(self.tree(), chat):
            raise AdapterError("Selected chat title failed verification")

    def snapshot_current(self, chat: str) -> dict:
        if hasattr(self.Q, "CGPreflightScreenCaptureAccess") and not self.Q.CGPreflightScreenCaptureAccess():
            raise AdapterError("Guest Screen Recording permission is required for media/bubble verification")
        from PIL import ImageGrab
        tree = self.tree()
        if not exact_chat_title(tree, chat):
            raise AdapterError("Chat changed before snapshot")
        panel = find_message_list(tree)
        x, y, w, h = panel["bounds"]
        screenshot = ImageGrab.grab(bbox=(round(x), round(y), round(x + w), round(y + h)))
        if not exact_chat_title(self.tree(), chat):
            raise AdapterError("Chat changed during screenshot capture")
        return parse_snapshot(tree, chat, screenshot)

    def snapshot(self, chat: str) -> dict:
        self.ensure_chat(chat)
        return self.snapshot_current(chat)

    def send(self, chat: str, payload: dict) -> dict:
        text = payload.get("text")
        if payload.get("expected_chat", chat) != chat:
            raise AdapterError("expected_chat differs from selected chat")
        if not isinstance(text, str) or not text.strip() or len(text) > 1500 or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise AdapterError("text must contain 1–1500 printable Unicode characters")
        self.ensure_chat(chat)
        before = self.snapshot_current(chat)
        tree = self.tree()
        fields = [n for n in walk(tree) if n.get("role") == "AXTextArea" and n.get("identifier") == "chat_input_field"]
        if len(fields) != 1 or not exact_chat_title(tree, chat):
            raise AdapterError("Cannot verify one composer in the exact chat")
        field = fields[0]
        if str(self.get(field["_ref"], "AXValue") or "").strip():
            raise AdapterError("Composer contains an existing draft; preserving it")
        self.set_value(field, "AXFocused", True)
        if not self.get(field["_ref"], "AXFocused"):
            raise AdapterError("Composer focus could not be verified")
        self.set_value(field, "AXValue", text)
        if self.get(field["_ref"], "AXValue") != text:
            raise AdapterError("Composer text readback differs; no send attempted")
        if not self.get(field["_ref"], "AXFocused") or not exact_chat_title(self.tree(), chat) or not self.app.isActive():
            raise AdapterError("Target/focus changed immediately before send; draft left in composer")
        # Exactly one attempt. Any failure after this boundary is uncertain.
        try:
            for down in (True, False):
                event = self.Q.CGEventCreateKeyboardEvent(None, 36, down)
                self.Q.CGEventSetFlags(event, 0)
                self.Q.CGEventPost(self.Q.kCGHIDEventTap, event)
            for _ in range(8):
                time.sleep(.3)
                after = self.snapshot_current(chat)
                if observed_send(before["messages"], after["messages"], text) and not str(self.get(field["_ref"], "AXValue") or "").strip():
                    return {"ok": True, "chat": chat, "verified_chat": True, "sent": True, "status": "observed", "uncertainties": ["own_bubble_observed_recipient_delivery_not_confirmed"]}
        except Exception as exc:
            return {"ok": False, "chat": chat, "verified_chat": False, "sent": False, "status": "uncertain", "error": str(exc), "retry_allowed": False}
        return {"ok": False, "chat": chat, "verified_chat": True, "sent": False, "status": "uncertain", "error": "No new matching own bubble observed; message may have been sent", "retry_allowed": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("chats")
    for name in ("snapshot", "send"):
        sub.add_parser(name).add_argument("--chat", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = readiness_status()
        else:
            adapter = MacWeChat()
        if args.command == "status":
            pass
        elif args.command == "chats":
            adapter.activate()
            result = discover_chats(adapter.tree())
        elif args.command == "snapshot":
            result = adapter.snapshot(args.chat)
        else:
            raw = sys.stdin.read(16385)
            if len(raw) > 16384:
                raise AdapterError("Send payload exceeds bounded input size")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise AdapterError("Send stdin must be a JSON object")
            result = adapter.send(args.chat, payload)
    except Exception as exc:
        result = {"ok": False, "chat": getattr(args, "chat", None), "verified_chat": False, "sent": False, "status": "not_sent", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
