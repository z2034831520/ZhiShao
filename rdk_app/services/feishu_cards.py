# -*- coding: utf-8 -*-
import time

CARD_ACTION_GROUPS = [
    (
        "\u5e38\u7528\u770b\u62a4",
        [
            ("\u67e5\u770b\u72b6\u6001", "status_text", "primary"),
            ("\u5f53\u524d\u6d3b\u52a8", "current_activity", "default"),
            ("\u6700\u8fd1\u4e8b\u4ef6", "recent_events", "default"),
            ("\u751f\u6210\u65e5\u62a5", "report", "primary"),
        ],
    ),
    (
        "\u4eba\u7269\u4e0e\u8ddf\u968f",
        [
            ("\u9501\u5b9a\u5f53\u524d", "lock", "primary"),
            ("\u9501\u5b9a\u8001\u4eba", "lock_elder", "default"),
            ("\u53d6\u6d88\u9501\u5b9a", "unlock", "danger"),
            ("\u6682\u505c\u8ddf\u968f", "pause_follow", "default"),
            ("\u6062\u590d\u8ddf\u968f", "resume_follow", "primary"),
        ],
    ),
    (
        "\u4e91\u53f0\u63a7\u5236",
        [
            ("\u5de6\u8f6c", "left", "default"),
            ("\u53f3\u8f6c", "right", "default"),
            ("\u4e0a\u8c03", "up", "default"),
            ("\u4e0b\u8c03", "down", "default"),
            ("\u56de\u4e2d", "center", "primary"),
        ],
    ),
    (
        "\u5b89\u5168\u4e0e\u6a21\u5f0f",
        [
            ("\u4fdd\u5b88\u6a21\u5f0f", "mode_conservative", "default"),
            ("\u7075\u654f\u6a21\u5f0f", "mode_sensitive", "default"),
            ("\u786e\u8ba4\u5b89\u5168", "family_safe", "primary"),
            ("\u8bef\u62a5", "family_false_alarm", "danger"),
        ],
    ),
    (
        "\u9690\u79c1\u4e0e\u5e2e\u52a9",
        [
            ("\u7533\u8bf7\u771f\u5b9e\u753b\u9762", "open_raw_view", "primary"),
            ("\u5173\u95ed\u771f\u5b9e\u753b\u9762", "close_raw_view", "default"),
            ("\u9690\u79c1\u72b6\u6001", "privacy_status", "default"),
            ("\u76d1\u63a7\u8bf4\u660e", "monitor_link", "default"),
            ("\u8bf4\u660e\u4e66", "manual", "default"),
            ("\u7cfb\u7edf\u81ea\u68c0", "self_check", "default"),
            ("\u5237\u65b0\u5361\u7247", "refresh_card", "primary"),
        ],
    ),
]

APP_COMMANDS = {
    "lock", "lock_elder", "unlock", "pause_follow", "resume_follow", "center",
    "left", "right", "up", "down", "mode_conservative", "mode_sensitive",
    "report", "family_safe", "family_false_alarm", "open_raw_view", "close_raw_view",
}

TEXT_COMMANDS = {
    "status_text", "current_activity", "recent_events", "privacy_status", "monitor_link", "manual", "self_check",
}

PTZ_COMMANDS = {"left", "right", "up", "down", "center"}
SLOW_COMMANDS = {"report", "open_raw_view", "close_raw_view"}
ALL_CARD_COMMANDS = APP_COMMANDS | TEXT_COMMANDS | {"refresh_card"}


def _minute(seconds):
    try:
        return f"{float(seconds or 0) / 60:.1f}"
    except Exception:
        return "0.0"


def _text(value, default="\u65e0"):
    value = "" if value is None else str(value)
    return value if value.strip() else default


def _button(label, command, button_type="default"):
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": button_type,
        "value": {"command": command, "label": label, "source": "zhishao_card"},
    }


def build_control_card(status_payload=None):
    status_payload = status_payload or {}
    status = status_payload.get("status") or {}
    metrics = status_payload.get("metrics") or {}
    comfort = status_payload.get("comfort_text") or "\u5b89\u5fc3\u770b\u62a4"
    summary = status_payload.get("family_summary") or "\u6b63\u5728\u7b49\u5f85\u672c\u5730\u770b\u62a4\u72b6\u6001\u3002"
    updated = time.strftime("%H:%M:%S")

    seen = _minute(metrics.get("seen_seconds"))
    active = _minute(metrics.get("active_seconds"))
    suspect = int(metrics.get("suspect_fall_count", 0) or 0)
    alert = int(metrics.get("confirmed_fall_count", 0) or 0)
    camera = "\u6b63\u5e38" if status.get("camera_ok") else "\u65e0\u753b\u9762"
    follow = "\u5f00\u542f" if status.get("follow_enabled") else "\u6682\u505c"
    locked = _text(status.get("locked_name"), "\u672a\u9501\u5b9a")
    lock_track = _text(status.get("locked_track_id"), "\u65e0")
    ptz_track = _text(status.get("ptz_follow_track_id"), "\u65e0")
    fall_mode = _text(status.get("fall_mode"), "\u4fdd\u5b88")
    fall_state = _text(status.get("fall_state"), "NORMAL")
    privacy = "\u4e34\u65f6\u5f00\u542f" if status.get("raw_video_allowed") else "\u9ed8\u8ba4\u5173\u95ed"

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{comfort}**\n{summary}\n"
                    f"\u66f4\u65b0\u65f6\u95f4\uff1a{updated}\uff5c\u771f\u5b9e\u753b\u9762\uff1a{privacy}\n"
                    "\u70b9\u51fb\u6309\u94ae\u5373\u53ef\u64cd\u4f5c\uff1b\u771f\u5b9e\u753b\u9762\u9ed8\u8ba4\u5173\u95ed\uff0c\u9700\u5148\u901a\u8fc7\u9690\u79c1\u590d\u6838\u3002"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u770b\u5230\u76ee\u6807**\n{seen} \u5206\u949f"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u6d3b\u52a8\u65f6\u957f**\n{active} \u5206\u949f"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u7591\u4f3c\u98ce\u9669**\n{suspect} \u6b21"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u786e\u8ba4\u544a\u8b66**\n{alert} \u6b21"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u6444\u50cf\u5934**\n{camera}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u81ea\u52a8\u8ddf\u968f**\n{follow}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u9501\u5b9a\u5bf9\u8c61**\n{locked}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u9501\u5b9a/\u8ddf\u968f**\n{lock_track} / {ptz_track}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u6454\u5012\u68c0\u6d4b**\n{fall_mode}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**\u72b6\u6001\u673a**\n{fall_state}"}},
            ],
        },
    ]
    for title, actions in CARD_ACTION_GROUPS:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{title}**"}})
        for start in range(0, len(actions), 4):
            elements.append({"tag": "action", "actions": [_button(*item) for item in actions[start:start + 4]]})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "\u9690\u79c1\u8fb9\u754c\uff1a\u9ed8\u8ba4\u53ea\u770b\u72b6\u6001\u548c\u8131\u654f\u9aa8\u67b6\uff1b\u771f\u5b9e\u753b\u9762\u9700\u590d\u6838\u5e76\u9650\u65f6\u5f00\u653e\u3002"}]})
    return {
        "config": {"wide_screen_mode": True, "enable_forward": False},
        "header": {
            "template": "green" if alert == 0 and suspect == 0 else "yellow",
            "title": {"tag": "plain_text", "content": "\u667a\u54e8\u5b89\u5fc3\u770b\u62a4\u63a7\u5236\u53f0"},
        },
        "elements": elements,
    }


def card_response_payload(toast_text, toast_type="success", card=None):
    payload = {"toast": {"type": toast_type, "content": str(toast_text or "")[:90]}}
    if card is not None:
        payload["card"] = {"type": "raw", "data": card}
    return payload


def short_reply(text, limit=90):
    text = str(text or "\u64cd\u4f5c\u5df2\u6267\u884c\u3002").replace("\r", " " ).strip()
    first = text.split("\n", 1)[0]
    return first[:limit]
