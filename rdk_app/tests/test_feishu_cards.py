import json
import os
import sys
import time
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.feishu_cards import ALL_CARD_COMMANDS, build_control_card
from services.feishu_service import FeishuService


class FakeRuntime:
    def snapshot(self):
        return {"monitor_url": "http://10.0.0.2:5000"}


class FakeVision:
    def lock_status_text(self):
        return "锁定状态测试"


class FakeApp:
    def __init__(self):
        self.runtime = FakeRuntime()
        self.vision_worker = FakeVision()
        self.commands = []

    def status_payload(self):
        return {
            "comfort_text": "整体平稳",
            "family_summary": "当前状态平稳。\n最近看到目标：刚刚",
            "metrics": {"seen_seconds": 120, "active_seconds": 60, "suspect_fall_count": 0, "confirmed_fall_count": 0},
            "status": {
                "camera_ok": True,
                "follow_enabled": True,
                "locked_name": "老人",
                "locked_track_id": 7,
                "ptz_follow_track_id": 7,
                "fall_mode": "保守",
                "fall_state": "NORMAL",
                "raw_video_allowed": False,
            },
        }

    def status_text(self): return "状态详情"
    def current_activity_text(self): return "活动详情"
    def recent_events_text(self): return "最近事件"
    def privacy_status_text(self): return "隐私状态"
    def self_check(self): return "自检正常"
    def manual(self): return '完整说明书'
    def visual_question_answer(self, _q): return {"answer": "正在轻微活动", "need_image": True}
    def make_reply_gif(self): return ""

    def handle_command(self, command, source=""):
        self.commands.append((command, source))
        return True, f"执行 {command}"


class FakeBot:
    def __init__(self):
        self.texts = []
        self.cards = []
        self.posts = []

    def reply_text(self, message_id, text):
        self.texts.append((message_id, text)); return {"code": 0}

    def reply_interactive_card(self, message_id, card):
        self.cards.append((message_id, card)); return {"code": 0}

    def reply_rich_post(self, message_id, title, blocks):
        self.posts.append((message_id, title, blocks)); return {"code": 0}

    def upload_image(self, _path): return None


class CardAction:
    def __init__(self, command, user="u1", message="m1"):
        self.event = SimpleNamespace(
            action=SimpleNamespace(value={"command": command, "label": command}),
            operator=SimpleNamespace(open_id=user, user_id=user),
            context=SimpleNamespace(open_message_id=message, open_chat_id="c1"),
        )


class TextEvent:
    def __init__(self, text, message_id="txt-1"):
        self.event = SimpleNamespace(
            message=SimpleNamespace(
                message_id=message_id,
                message_type="text",
                content=json.dumps({"text": text}, ensure_ascii=False),
                chat_id="chat-1",
            )
        )


class FeishuCardTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.bot = FakeBot()
        self.service = FeishuService(self.app, self.bot)

    def test_card_schema_contains_all_buttons(self):
        card = build_control_card(self.app.status_payload())
        self.assertEqual(card["header"]["title"]["content"], "智哨安心看护控制台")
        dumped = str(card)
        for command in ALL_CARD_COMMANDS:
            self.assertIn(command, dumped)

    def test_text_menu_replies_card(self):
        self.service._reply_control_card("msg-1")
        self.assertEqual(len(self.bot.cards), 1)

    def test_text_menu_with_feishu_internal_mention_replies_card(self):
        self.service.handle_message(TextEvent('@_user_1 卡片'))
        self.service.handle_message(TextEvent('@智哨管家 菜单', message_id="txt-2"))
        self.assertEqual(len(self.bot.cards), 2)
        self.assertEqual(len(self.app.commands), 0)

    def test_all_card_commands_execute_without_exception(self):
        for command in sorted(ALL_CARD_COMMANDS):
            resp = self.service.handle_card_action(CardAction(command, user=f"u-{command}"))
            self.assertIsNotNone(resp)
        executed = {command for command, _source in self.app.commands}
        self.assertIn("left", executed)
        self.assertIn("report", executed)
        self.assertGreaterEqual(len(self.bot.texts), 4)
        self.assertGreaterEqual(len(self.bot.posts), 1)

    def test_extreme_rapid_ptz_clicks_are_rate_limited(self):
        first = self.service.handle_card_action(CardAction("left", user="fast"))
        second = self.service.handle_card_action(CardAction("left", user="fast"))
        self.assertIsNotNone(first)
        self.assertIn("太快", second.toast.content)

    def test_malformed_action_is_safe(self):
        bad = SimpleNamespace(event=SimpleNamespace(action=SimpleNamespace(value={}), operator=None, context=None))
        resp = self.service.handle_card_action(bad)
        self.assertIn("缺少命令", resp.toast.content)

    def test_long_status_does_not_break_toast(self):
        self.app.handle_command = lambda command, source="": (True, "很长" * 100)
        resp = self.service.handle_card_action(CardAction("unlock", user="long"))
        self.assertLessEqual(len(resp.toast.content), 90)

    def test_extreme_card_size_and_unique_commands(self):
        card = build_control_card(self.app.status_payload())
        raw = json.dumps(card, ensure_ascii=False)
        self.assertLess(len(raw.encode("utf-8")), 30000)
        seen = []
        for element in card["elements"]:
            for action in element.get("actions", []):
                seen.append(action["value"]["command"])
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), ALL_CARD_COMMANDS)

    def test_extreme_many_mixed_clicks(self):
        commands = sorted(ALL_CARD_COMMANDS)
        for i in range(200):
            command = commands[i % len(commands)]
            resp = self.service.handle_card_action(CardAction(command, user=f"stress-{i % 17}", message=f"m-{i}"))
            self.assertIsNotNone(resp)
        self.assertLessEqual(len(self.service.card_action_times), 500)


if __name__ == "__main__":
    unittest.main()
