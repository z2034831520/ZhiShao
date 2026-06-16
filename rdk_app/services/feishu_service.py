import json
import re
import time
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

from settings import FEISHU_APP_ID, FEISHU_APP_SECRET
from services.feishu_cards import (
    APP_COMMANDS, PTZ_COMMANDS, SLOW_COMMANDS, TEXT_COMMANDS, build_control_card,
    card_response_payload, short_reply,
)


class FeishuService:
    """Feishu event routing with table-like command matching."""

    VISUAL_QUESTION_KEYWORDS = [
        "他在干什么", "她在干什么", "他们在干什么", "老人在干什么", "人在干什么",
        "他现在在做什么", "她现在在做什么", "他们现在在做什么", "现在在做什么",
        "在干嘛", "在干啥", "正在干什么", "在做什么", "在活动吗", "看看他在做什么",
    ]

    def __init__(self, app_service, bot):
        self.app_service = app_service
        self.bot = bot
        self.processed = set()
        self.card_action_times = {}
        self.client = None
        if FEISHU_APP_ID and FEISHU_APP_SECRET:
            self.client = lark.Client.builder().app_id(FEISHU_APP_ID).app_secret(FEISHU_APP_SECRET).build()

    def start(self):
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            self.app_service.runtime.update(feishu_ok=False)
            print("?? [飞书组件] 未配置 FEISHU_APP_ID / FEISHU_APP_SECRET，飞书对话服务未启动。")
            return
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.handle_message)
            .register_p2_card_action_trigger(self.handle_card_action)
            .build()
        )
        cli = lark.ws.Client(FEISHU_APP_ID, FEISHU_APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO)
        self.app_service.runtime.update(feishu_ok=True)
        print("? [飞书组件] WebSocket 监听服务已就绪！")
        threading.Thread(target=cli.start, daemon=True).start()

    def _control_card(self):
        return build_control_card(self.app_service.status_payload())

    def _reply_control_card(self, message_id):
        resp = self.bot.reply_interactive_card(message_id, self._control_card())
        if not resp or resp.get("code", 0) != 0:
            detail = ""
            if isinstance(resp, dict):
                detail = resp.get("msg") or resp.get("message") or ""
            print(f"[Feishu Card] send failed: {detail or resp}")
            self.bot.reply_text(
                message_id,
                "控制卡片暂时发送失败，已切换为文字菜单。\n\n"
                + self.app_service.quick_help()
                + "\n\n你也可以继续发送：查看状态、当前活动、左转、右转、锁定当前人物、日报。",
            )
        return resp

    def _normalize_question(self, text):
        text = str(text or "")
        text = text.replace("@智哨管家", " ").replace("＠智哨管家", " ")
        text = re.sub(r"@[_a-zA-Z0-9\-]+", " ", text)
        text = re.sub(r"@[\u4e00-\u9fffA-Za-z0-9_\-]+", " ", text)
        text = text.replace("\u200b", " ").replace("\xa0", " ").replace("　", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text.strip(" ，,。.!！?？：:")

    def _card_event_value(self, data):
        event = getattr(data, "event", None)
        action = getattr(event, "action", None)
        value = getattr(action, "value", None)
        return value if isinstance(value, dict) else {}

    def _card_event_message_id(self, data):
        event = getattr(data, "event", None)
        context = getattr(event, "context", None)
        return getattr(context, "open_message_id", "") if context else ""

    def _card_event_user(self, data):
        event = getattr(data, "event", None)
        operator = getattr(event, "operator", None)
        return getattr(operator, "open_id", "") or getattr(operator, "user_id", "") or "unknown"

    def _card_rate_limited(self, user_key, command):
        now = time.time()
        cooldown = 0.35 if command in PTZ_COMMANDS else 2.0 if command in SLOW_COMMANDS else 0.6
        key = (user_key, command)
        last = self.card_action_times.get(key, 0.0)
        if now - last < cooldown:
            return True
        self.card_action_times[key] = now
        if len(self.card_action_times) > 500:
            self.card_action_times = {k: v for k, v in self.card_action_times.items() if now - v < 60}
        return False

    def _send_text_followup(self, message_id, text):
        if message_id:
            self.bot.reply_text(message_id, text)

    def _send_visual_followup(self, message_id):
        result = self.app_service.visual_question_answer("看看当前画面里的人在做什么")
        answer = result.get("answer") or "当前暂时没有看清活动状态。"
        gif_path = self.app_service.make_reply_gif()
        image_key = self.bot.upload_image(gif_path) if gif_path else None
        blocks = [
            [{"tag": "text", "text": f"{answer}\n\n"}],
            [{"tag": "text", "text": "隐私保护：这里只展示脱敏骨架 GIF，不展示真实画面。"}],
        ]
        if image_key:
            blocks.append([{"tag": "img", "image_key": image_key}])
        if message_id:
            self.bot.reply_rich_post(message_id, "智哨当前活动", blocks)

    def _execute_card_command(self, command, message_id):
        if command == "refresh_card":
            return True, "卡片已刷新。"
        if command == "current_activity":
            self._send_visual_followup(message_id)
            return True, "已发送当前活动分析。"
        if command in TEXT_COMMANDS:
            text_map = {
                "status_text": self.app_service.status_text,
                "recent_events": self.app_service.recent_events_text,
                "privacy_status": self.app_service.privacy_status_text,
                "monitor_link": self._monitor_link,
                "manual": self.app_service.manual,
                "self_check": self.app_service.self_check,
            }
            text = text_map[command]()
            self._send_text_followup(message_id, text)
            return True, "已发送详细信息。"
        if command in APP_COMMANDS:
            return self.app_service.handle_command(command, source="feishu_card")
        return False, "未知卡片按钮。"

    def handle_card_action(self, data):
        value = self._card_event_value(data)
        command = str(value.get("command", "")).strip()
        label = str(value.get("label", command)).strip() or command
        user_key = self._card_event_user(data)
        message_id = self._card_event_message_id(data)
        if not command:
            return P2CardActionTriggerResponse(card_response_payload("按钮缺少命令，已忽略。", "warning", self._control_card()))
        if self._card_rate_limited(user_key, command):
            return P2CardActionTriggerResponse(card_response_payload(f"{label} 点得太快了，请稍等一下。", "warning", self._control_card()))
        ok, reply = self._execute_card_command(command, message_id)
        toast_type = "success" if ok else "warning"
        toast = short_reply(reply)
        print(f"? [飞书卡片] {label} -> {command}: {toast}")
        return P2CardActionTriggerResponse(card_response_payload(toast, toast_type, self._control_card()))

    def _text(self, data):
        try:
            raw = json.loads(data.event.message.content).get("text", "")
            return self._normalize_question(raw)
        except Exception:
            return ""

    def handle_message(self, data):
        msg = data.event.message
        msg_id = msg.message_id
        if msg_id in self.processed:
            return
        self.processed.add(msg_id)
        if msg.message_type != "text":
            return
        question = self._text(data)
        if not question:
            return
        print(f"\n? [飞书管家] 收到用户指令: {question}")

        if question in {"\u83dc\u5355", "\u4e3b\u83dc\u5355", "\u63a7\u5236\u9762\u677f", "\u64cd\u4f5c\u9762\u677f", "\u6309\u94ae", "\u5361\u7247", "\u63a7\u5236\u5361\u7247", "\u4ea4\u4e92\u5361\u7247"}:
            self._reply_control_card(msg_id)
            return

        if self._is_visual_question(question):
            self._reply_visual_question(msg_id, question)
            return

        for keywords, handler in self._routes():
            if any(keyword in question for keyword in keywords):
                reply = handler(question)
                self.bot.reply_text(msg_id, reply)
                return

        # 异步处理大模型请求，避免阻塞飞书 WebSocket 接收线程
        threading.Thread(target=self._async_ask_brain, args=(msg_id, question), daemon=True).start()

    def _async_ask_brain(self, msg_id, question):
        """在独立线程中请求大模型并回复"""
        result = self.app_service.ask_brain(question)
        answer = result.get("answer", "系统大脑开小差了，稍后再试。")
        if result.get("need_image"):
            gif_path = self.app_service.make_reply_gif()
            image_key = self.bot.upload_image(gif_path) if gif_path else None
            blocks = [
                [{"tag": "text", "text": f"{answer}\n\n"}],
                [{"tag": "text", "text": "隐私保护：这里只展示脱敏骨架 GIF，不展示真实画面。"}],
            ]
            if image_key:
                blocks.append([{"tag": "img", "image_key": image_key}])
            self.bot.reply_rich_post(msg_id, "智哨管家回复", blocks)
        else:
            self.bot.reply_text(msg_id, answer)

    def _routes(self):
        return [
            (["说明书", "使用说明", "产品说明"], lambda _q: self.app_service.manual()),
            (["帮助", "指令"], lambda _q: "发送“菜单”或“控制面板”即可打开可点击按钮卡片；也可以继续直接输入文字指令。"),
            (["实时监控", "监控链接", "打开监控", "看护画面"], lambda _q: self._monitor_link()),
            (
                ["查看当前状态", "当前状态", "现在状态", "目前状态", "设备当前状态", "看护状态", "今天状态"],
                lambda _q: self.app_service.status_text(),
            ),
            (
                ["当前活动", "活动情况"],
                lambda _q: self.app_service.current_activity_text(),
            ),
            (
                ["我想确认一下", "确认一下", "是否安全", "现在情况", "安全吗", "安全么", "现在安全吗", "现在安全么", "有没有异常"],
                lambda _q: self.app_service.reassurance_text(),
            ),
            (["临时查看真实画面", "开启真实画面", "打开真实画面"], lambda _q: self._command("open_raw_view")),
            (["关闭真实画面", "停止真实画面"], lambda _q: self._command("close_raw_view")),
            (["查看隐私状态", "隐私状态", "边界看护"], lambda _q: self.app_service.privacy_status_text()),
            (["查看状态", "设备状态", "系统状态"], lambda _q: self.app_service.status_text()),
            (["系统自检", "设备自检", "自检"], lambda _q: self.app_service.self_check()),
            (["最近事件", "事件记录"], lambda _q: self.app_service.recent_events_text()),
            (["日报", "报告"], lambda _q: self._command("report")),
            (["锁定老人"], lambda _q: self._command("lock_elder")),
            (["锁定当前人物", "锁定当前目标"], lambda _q: self._command("lock")),
            (["取消锁定"], lambda _q: self._command("unlock")),
            (["查看锁定状态", "锁定状态"], lambda _q: self.app_service.vision_worker.lock_status_text()),
            (["暂停跟随", "暂停巡航"], lambda _q: self._command("pause_follow")),
            (["恢复跟随", "恢复巡航", "自动巡航"], lambda _q: self._command("resume_follow")),
            (["云台回中", "回中", "归中"], lambda _q: self._command("center")),
            (["左转"], lambda _q: self._command("left")),
            (["右转"], lambda _q: self._command("right")),
            (["上调", "向上"], lambda _q: self._command("up")),
            (["下调", "向下"], lambda _q: self._command("down")),
            (["保守模式"], lambda _q: self._command("mode_conservative")),
            (["灵敏模式"], lambda _q: self._command("mode_sensitive")),
            (["已确认安全", "确认安全"], lambda _q: self._command("family_safe")),
            (["误报"], lambda _q: self._command("family_false_alarm")),
            (["照片录入", "录入老人", "完成录入"], lambda _q: "当前版本不使用人脸识别和照片录入。请让目标出现在画面中，然后发送“锁定当前人物”。"),
        ]

    def _is_visual_question(self, question):
        return any(keyword in question for keyword in self.VISUAL_QUESTION_KEYWORDS)

    def _reply_visual_question(self, msg_id, question):
        result = self.app_service.visual_question_answer(question)
        answer = result.get("answer") or "我暂时没有看清当前状态，但本地看护仍在运行。"
        gif_path = self.app_service.make_reply_gif()
        image_key = self.bot.upload_image(gif_path) if gif_path else None
        blocks = [
            [{"tag": "text", "text": f"{answer}\n\n"}],
            [{"tag": "text", "text": "隐私保护：下面只展示脱敏骨架 GIF，不展示、不转发真实摄像头画面。"}],
        ]
        if image_key:
            blocks.append([{"tag": "img", "image_key": image_key}])
        resp = self.bot.reply_rich_post(msg_id, "? 智哨管家回复", blocks)
        if not resp or resp.get("code", 0) != 0:
            self.bot.reply_text(msg_id, f"{answer}\n\n隐私保护：本次只展示脱敏骨架，不展示真实摄像头画面。")

    def _monitor_link(self):
        url = self.app_service.runtime.snapshot().get("monitor_url")
        health_url = f"{url}/health" if url else ""
        return "\n".join([
            "安心看护页（局域网）：",
            url or "暂无地址",
            "",
            "连通性测试：",
            health_url or "暂无地址",
            "",
            "手机能打开的前提：手机和 RDK 在同一 Wi-Fi/热点网络内。",
            "如果子女在外地或使用手机流量，这个内网地址通常打不开，需要后续配置 HTTPS 中转或内网穿透。",
            "页面默认展示状态卡和脱敏画面；真实画面默认关闭，开启前需要隐私复核，并会限时自动关闭。",
        ])

    def _command(self, command):
        _ok, reply = self.app_service.handle_command(command, source="feishu")
        return reply

    def _send_chat(self, chat_id, payload):
        if self.client is None:
            return None
        req = CreateMessageRequest.builder().receive_id_type("chat_id").request_body(
            CreateMessageRequestBody.builder().receive_id(chat_id)
            .msg_type(payload["msg_type"]).content(json.dumps(payload["content"], ensure_ascii=False)).build()
        ).build()
        self.client.im.v1.message.create(req)
