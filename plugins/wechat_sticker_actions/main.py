"""Choose a catalog sticker; the verified WeChat transport performs delivery."""
import json
from baguette_config import load_config
import re

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star


class WeChatStickerActions(Star):
    @filter.llm_tool(name="select_wechat_sticker")
    async def select_wechat_sticker(self, event: AstrMessageEvent, sticker_id: str, reason: str = "") -> str:
        """Select one matching sticker from the locally imported S01-S36 catalog for this reply.

        This selects an intent; it does not confirm sending. The WeChat bridge
        opens Favorites, scrolls, verifies the thumbnail and clicks it once.

        Args:
            sticker_id(string): Exact guide ID from S01 to S36, chosen by meaning and context.
            reason(string): Brief explanation of why this sticker fits the current conversation.
        """
        if not ((event.get_sender_id() == load_config()["owner_id"] and event.get_platform_name() == "webchat")
                or event.get_platform_name() == "wechat_vm"):
            return json.dumps({"selected": False, "error": "This deployment is restricted to the verified owner"})
        observed=event.get_extra('wechat_ui_observation') or {}
        if event.get_platform_name()=='wechat_vm' and observed.get('directed') is not True:
            return json.dumps({'selected':False,'error':'Passive context does not authorize a sticker reply'})
        if not re.fullmatch(r"S(?:0[1-9]|[12][0-9]|3[0-6])", sticker_id):
            return json.dumps({"selected": False, "error": "Unknown sticker ID"})
        if event.get_extra("wechat_sticker_selected"):
            return json.dumps({"selected": False, "error": "Only one sticker per reply"})
        event.set_extra("wechat_sticker_selected", sticker_id)
        return json.dumps({"selected": True, "sent": False, "sticker_id": sticker_id,
                           "reason": reason[:120]}, ensure_ascii=False)
