import os

import cv2

from settings import BASE_DIR
from core.ptz_controller import ptz
from services.text_overlay import draw_chinese_text


class AppService:
    """Unified command/status facade used by Feishu and Web."""

    RAW_VIEW_SECONDS = 180

    def __init__(self, store, runtime, frame_hub, vision_worker, ptz_service, report_service, brain, bot):
        self.store = store
        self.runtime = runtime
        self.frame_hub = frame_hub
        self.vision_worker = vision_worker
        self.ptz_service = ptz_service
        self.report_service = report_service
        self.brain = brain
        self.bot = bot

    def status_payload(self):
        metrics = self.store.get_metrics()
        events = self.store.list_events(limit=8, date=self.store.today())
        return {
            "ok": True,
            "status": self.runtime.snapshot(),
            "metrics": metrics,
            "events": events,
            "status_text": self.status_text(),
            "system_brief_text": self.system_brief_text(metrics),
            "comfort_text": self.comfort_text(metrics),
            "family_summary": self.family_summary(metrics),
            "privacy_text": self.privacy_status_text(),
            "video_age": {
                "raw": self.frame_hub.raw_age(),
                "skeleton": self.frame_hub.skeleton_age(),
            },
        }

    def comfort_text(self, metrics=None):
        metrics = metrics or self.store.get_metrics()
        confirmed = int(metrics.get("confirmed_fall_count", 0) or 0)
        suspects = int(metrics.get("suspect_fall_count", 0) or 0)
        seen_minutes = float(metrics.get("seen_seconds", 0) or 0) / 60
        active_minutes = float(metrics.get("active_seconds", 0) or 0) / 60
        if confirmed:
            return "需要尽快确认"
        if suspects:
            return "有过疑似风险"
        if seen_minutes < 5:
            return "今日数据较少"
        if active_minutes < 10:
            return "整体平稳，活动偏少"
        return "整体平稳"

    def family_summary(self, metrics=None):
        metrics = metrics or self.store.get_metrics()
        state = self.runtime.snapshot()
        last_seen = metrics.get("last_seen_time") or state.get("last_seen_time") or "今天暂未看到目标"
        target_count = int(state.get("target_count", 0) or 0)
        if state.get("fall_state") in ("SUSPECT", "VALIDATING"):
            risk = "系统正在复核一个可能需要关心的姿态。"
        elif int(metrics.get("confirmed_fall_count", 0) or 0):
            risk = "今天出现过高风险提醒，请优先确认父母是否安好。"
        elif int(metrics.get("suspect_fall_count", 0) or 0):
            risk = "今天出现过疑似风险，系统已记录并保持关注。"
        elif target_count:
            risk = "当前能看到可信人体目标，安全状态平稳。"
        else:
            risk = "当前暂未看到目标，设备仍在线守护。"
        return f"{risk}\n最近看到目标：{last_seen}"

    def status_text(self):
        metrics = self.store.get_metrics()
        state = self.runtime.snapshot()
        raw_line = (
            f"真实画面：临时开启中，剩余 {state['raw_video_seconds_left']} 秒"
            if state["raw_video_allowed"]
            else "真实画面：默认关闭，开启前需大模型隐私复核"
        )
        return (
            f"安心状态：{self.comfort_text(metrics)}\n"
            f"{self.family_summary(metrics)}\n"
            f"看护模式：{state['care_mode']}（状态可见，画面克制）\n"
            f"{raw_line}\n"
            f"摄像头：{'正常' if state['camera_ok'] else '无画面'} ({state['camera_message']})\n"
            f"自动跟随：{'开启' if state['follow_enabled'] else '暂停'}\n"
            f"云台状态：{state['ptz_mode']}\n"
            f"摔倒检测模式：{state['fall_mode']}\n"
            f"摔倒状态机：{state['fall_state']}\n"
            f"视觉候选/可信目标：{state.get('raw_pose_count', 0)} / {state.get('target_count', 0)}\n"
            f"今日看到人时长：{float(metrics.get('seen_seconds', 0) or 0) / 60:.1f} 分钟\n"
            f"今日活动时长：{float(metrics.get('active_seconds', 0) or 0) / 60:.1f} 分钟\n"
            f"摔倒疑似次数：{int(metrics.get('suspect_fall_count', 0) or 0)}\n"
            f"确诊告警次数：{int(metrics.get('confirmed_fall_count', 0) or 0)}\n"
            f"{self.vision_worker.lock_status_text()}"
        )

    def system_brief_text(self, metrics=None):
        metrics = metrics or self.store.get_metrics()
        state = self.runtime.snapshot()
        raw_text = (
            f"临时开启 {state['raw_video_seconds_left']} 秒"
            if state.get("raw_video_allowed")
            else "默认关闭"
        )
        fall_state = {
            "NORMAL": "平稳",
            "CANDIDATE": "观察中",
            "SUSPECT": "疑似风险",
            "VALIDATING": "复核中",
            "CONFIRMED": "已告警",
            "REJECTED": "已拦截",
            "VALIDATION_FAILED": "复核失败",
        }.get(state.get("fall_state"), state.get("fall_state", "未知"))
        return "\n".join(
            [
                f"安心状态：{self.comfort_text(metrics)}",
                f"摄像头：{'正常' if state.get('camera_ok') else '无画面'}",
                f"自动跟随：{'开启' if state.get('follow_enabled') else '暂停'}",
                f"摔倒检测：{state.get('fall_mode', '保守')} / {fall_state}",
                f"可信目标：{state.get('target_count', 0)}",
                f"真实画面：{raw_text}",
            ]
        )

    def get_video_frame(self, source):
        if source == "raw":
            if not self.runtime.raw_video_allowed():
                skeleton = self.frame_hub.get_skeleton()
                if skeleton is not None:
                    return skeleton
                return self.frame_hub.privacy_frame("真实画面默认关闭，请先通过隐私复核")
            raw = self.frame_hub.get_raw()
            if raw is not None:
                return self._with_raw_view_overlay(raw)
        if source == "skeleton":
            skeleton = self.frame_hub.get_skeleton()
            if skeleton is not None:
                return skeleton
        return self.frame_hub.blank_frame()

    def _with_raw_view_overlay(self, frame):
        view = frame.copy()
        h, w = view.shape[:2]
        seconds_left = self.runtime.raw_seconds_left()
        overlay = view.copy()
        cv2.rectangle(overlay, (0, 0), (w, 52), (8, 18, 28), -1)
        cv2.rectangle(overlay, (0, h - 34), (w, h), (8, 18, 28), -1)
        view = cv2.addWeighted(overlay, 0.68, view, 0.32, 0)
        view = draw_chinese_text(view, "临时安全确认：隐私复核通过", (14, 7), size=18, color=(255, 255, 0))
        view = draw_chinese_text(view, f"{seconds_left} 秒后自动关闭｜请勿录屏、截图、转发", (14, 29), size=15, color=(245, 245, 245))
        view = draw_chinese_text(view, "真实画面仅用于确认安全，默认使用脱敏看护", (14, h - 27), size=13, color=(245, 245, 245))
        return view

    def handle_command(self, command, source="feishu"):
        command = (command or "").strip()
        mapping = {
            "lock": lambda: self.vision_worker.lock_current(),
            "lock_elder": lambda: self.vision_worker.lock_current("老人"),
            "unlock": self.vision_worker.unlock,
            "pause_follow": lambda: self.ptz_service.set_follow_enabled(False),
            "resume_follow": lambda: self.ptz_service.set_follow_enabled(True),
            "center": self.ptz_service.center,
            "left": lambda: self.ptz_service.move("left"),
            "right": lambda: self.ptz_service.move("right"),
            "up": lambda: self.ptz_service.move("up"),
            "down": lambda: self.ptz_service.move("down"),
            "mode_conservative": lambda: self.vision_worker.set_fall_mode("conservative"),
            "mode_sensitive": lambda: self.vision_worker.set_fall_mode("sensitive"),
            "report": self._send_report,
            "family_safe": lambda: self._family_action("已确认安全"),
            "family_false_alarm": lambda: self._family_action("误报"),
            "open_raw_view": self.open_raw_view,
            "close_raw_view": self.close_raw_view,
        }
        if command not in mapping:
            return False, "未知指令。"
        ok, reply = mapping[command]()
        return ok, reply

    def open_raw_view(self):
        frame = self.frame_hub.get_raw()
        if frame is None:
            self.store.record_event("raw_view_blocked", "真实画面开启失败：当前没有可复核画面。", "warning")
            return False, "当前没有可复核画面，暂时不能开启真实画面。请稍后再试。"

        result = self.brain.privacy_check(frame)
        safe = bool(result and result.get("safe_to_show"))
        reason = (result or {}).get("reason", "云端大脑未返回明确结论。")
        risk_level = (result or {}).get("risk_level", "unknown")
        block_type = (result or {}).get("block_type", "unknown")
        confidence = float((result or {}).get("confidence", 0.0) or 0.0)
        evidence = (result or {}).get("evidence", [])
        if isinstance(evidence, str):
            evidence = [evidence]
        if not isinstance(evidence, list):
            evidence = []
        if not safe:
            if block_type == "service_unavailable":
                title = "真实画面未开启：隐私复核服务不可用，已按保护策略拒绝。"
            elif risk_level == "privacy_risk" or block_type == "privacy_risk":
                title = "真实画面未开启：画面存在隐私风险。"
            elif risk_level == "uncertain" or block_type == "uncertain":
                title = "真实画面未开启：模型不确定，已按保护策略拒绝。"
            else:
                title = "真实画面未开启：隐私复核未通过。"
            evidence_text = "；".join(str(item) for item in evidence[:3] if str(item).strip())
            detail = f"{title}原因：{reason}"
            if evidence_text:
                detail += f"依据：{evidence_text}"
            detail += f" 风险等级：{risk_level}，置信度：{confidence:.2f}"
            self.store.record_event(
                "raw_view_privacy_blocked",
                detail,
                "warning",
                {
                    "risk_level": risk_level,
                    "reason": reason,
                    "confidence": confidence,
                    "evidence": evidence[:3],
                    "block_type": block_type,
                },
            )
            return False, (
                "真实画面未开启。\n"
                f"{title}\n"
                f"具体原因：{reason}\n"
                f"风险等级：{risk_level}，置信度：{confidence:.2f}\n"
                "为保护父母隐私，请先使用脱敏画面、电话或语音确认。"
            )

        self.runtime.allow_raw_video(self.RAW_VIEW_SECONDS)
        self.store.record_event(
            "raw_view_opened",
            f"大模型确认无明显隐私泄露后，家属临时开启真实画面 {self.RAW_VIEW_SECONDS // 60} 分钟。",
            "info",
            {"seconds": self.RAW_VIEW_SECONDS, "privacy_check": result},
        )
        return True, (
            f"大模型已确认当前画面无明显隐私泄露，真实画面临时开启 {self.RAW_VIEW_SECONDS // 60} 分钟。\n"
            "请只用于确认安全，到时会自动关闭；默认看护仍以状态和脱敏画面为主。\n"
            "隐私提示：请避免录屏、截图、转发或让无关人员观看。"
        )

    def close_raw_view(self):
        self.runtime.close_raw_video()
        self.store.record_event("raw_view_closed", "真实画面已关闭，恢复边界看护。", "info")
        return True, "真实画面已关闭。当前仅展示安心状态和脱敏画面。"

    def _send_report(self):
        self.report_service.send_report()
        return True, "图文健康日报已生成。"

    def _family_action(self, action):
        self.store.record_family_action(action)
        return True, f"已记录家属处置：{action}。"

    def privacy_status_text(self):
        state = self.runtime.snapshot()
        if state["raw_video_allowed"]:
            raw = f"真实画面临时开启中，剩余 {state['raw_video_seconds_left']} 秒。"
        else:
            raw = "真实画面默认关闭，开启前必须通过大模型隐私复核。"
        return (
            "隐私与安心边界\n"
            f"- 看护模式：{state['care_mode']}\n"
            "- 家属默认看到安心状态、活动概览和脱敏骨架。\n"
            f"- {raw}\n"
            "- 摔倒告警优先发送文字结论和脱敏证据，减少不必要打扰。"
        )

    def reassurance_text(self):
        state = self.runtime.snapshot()
        metrics = self.store.get_metrics()
        url = state.get("monitor_url") or "http://RDK_IP:5000"
        if self.comfort_text(metrics) == "整体平稳":
            advice = "当前暂无必要查看真实画面；如仍不放心，可先打开脱敏看护页。"
        else:
            advice = "建议先电话问候；如果联系不上，可申请临时查看真实画面，系统会先做大模型隐私复核。"
        return (
            f"{self.family_summary(metrics)}\n\n"
            f"{advice}\n"
            f"看护页：{url}\n"
            "可用指令：临时查看真实画面、关闭真实画面、查看隐私状态。"
        )

    def current_activity_text(self):
        state = self.runtime.snapshot()
        metrics = self.store.get_metrics()
        target_count = int(state.get("target_count", 0) or 0)
        last_seen = metrics.get("last_seen_time") or state.get("last_seen_time") or "今天暂未看到目标"
        fall_state = state.get("fall_state", "NORMAL")
        active_track = state.get("active_track_id") or "无"
        lock_line = (
            f"当前跟随轨迹：{active_track}，{state.get('follow_reason') or '暂无跟随原因'}。"
            if active_track != "无"
            else f"当前跟随轨迹：无，{state.get('follow_reason') or '暂无可信目标'}。"
        )

        if fall_state in {"SUSPECT", "VALIDATING"}:
            activity = "系统正在复核一个可能需要关心的姿态，建议先通过电话或语音确认。"
        elif fall_state == "CONFIRMED":
            activity = "系统已经确认高风险提醒，请优先确认父母是否安全。"
        elif target_count <= 0:
            activity = "根据脱敏骨架判断：当前暂未看到可信人体目标，设备仍在线守护。"
        elif getattr(self.vision_worker, "is_moving", False):
            activity = "根据脱敏骨架判断：当前能看到可信人体目标，骨架位置有变化，像是在走动、调整姿势或进行轻微活动。"
        else:
            activity = "根据脱敏骨架判断：当前能看到可信人体目标，姿态比较稳定，像是在停留、静坐或缓慢活动。"

        return (
            f"{activity}\n"
            f"最近看到目标：{last_seen}\n"
            f"{lock_line}\n"
            "说明：这里基于脱敏骨架、人体框和活动统计判断，不主动查看或发送真实画面。"
        )

    def visual_question_answer(self, question):
        """Use the cloud brain to understand the current scene, but only expose sanitized evidence."""
        raw = self.frame_hub.get_raw()
        if raw is None:
            return {
                "answer": "当前摄像头暂时没有可分析画面。我会继续在线守护；你也可以稍后再问一次。",
                "used_vision": False,
                "need_image": False,
            }

        state = self.runtime.snapshot()
        metrics = self.store.get_metrics()
        context = (
            f"本次家属的问题是：{question}\n"
            "你必须只回答这个问题，不要扩展到天气、地点、产品说明、隐私策略、健康建议或监控入口。"
            "你可以分析这张实时摄像头帧来判断人物正在做什么，"
            "但最终回复必须保护隐私：不要描述可识别面部细节、屏幕文字、身体隐私部位、裸露/换衣/如厕等敏感细节；"
            "如果画面存在隐私风险，只能用克制说法，例如“当前不适合展开描述，建议用电话确认”。"
            "如果问题是“他/他们在做什么”，请围绕当前问题做更完整的看护分析："
            "可以描述人数、站坐姿态、是否移动、是否像在交流/协作、所在环境类型、是否有明显危险姿态。"
            "不要主动描述天气、气温、城市或无关环境。"
            "如果看不清或无法判断动作，直接说当前无法准确判断，不要换话题回答。"
            "回复保持 3 到 5 句话，尽量自然具体。"
            "不要说你在查看或发送真实画面；飞书附件只会展示脱敏骨架 GIF。"
            f"当前本地状态：可信人体 {state.get('target_count', 0)} 个，"
            f"当前跟随轨迹 {state.get('active_track_id') or '无'}，"
            f"锁定对象 {state.get('locked_name') or '未锁定'}，"
            f"最近看到目标 {metrics.get('last_seen_time') or state.get('last_seen_time') or '今天暂未看到目标'}。"
            "必须返回 need_image=true，因为回复会附带脱敏骨架证据。"
        )
        result = self.brain.ask(question, raw, system_note=context)
        if not result or not result.get("answer"):
            return {
                "answer": self.current_activity_text(),
                "used_vision": False,
                "need_image": True,
            }
        return {
            "answer": result.get("answer", "").strip(),
            "used_vision": True,
            "need_image": True,
        }

    def self_check(self):
        state = self.runtime.snapshot()
        serial_ok = self.ptz_service.serial_ok()
        lines = ["智哨系统自检"]
        lines.append(f"{'通过' if state['running'] else '注意'} - 主程序：{'运行中' if state['running'] else '未启动'}")
        lines.append(f"{'通过' if state['camera_ok'] else '注意'} - 摄像头：{state['camera_message']}")
        lines.append(f"{'通过' if serial_ok else '注意'} - 云台串口：{ptz.port} {'已连接' if serial_ok else '未连接'}")
        lines.append(f"通过 - 本地看板：{state.get('monitor_url') or '未生成'}")
        lines.append("")
        lines.append(self.status_text())
        return "\n".join(lines)

    def manual(self):
        url = self.runtime.snapshot().get("monitor_url") or "http://RDK_IP:5000"
        return (
            "智哨智能看护系统说明书\n\n"
            f"网页看板：{url}\n"
            "默认只显示脱敏骨架和状态，真实画面默认关闭。\n\n"
            "一、查看类指令\n"
            "说明书：发送这份完整使用说明。\n"
            "帮助 / 指令：发送精简指令菜单。\n"
            "实时监控 / 监控链接：返回网页看板入口。\n"
            "查看状态 / 设备状态 / 系统状态：查看运行状态、看护结论、摄像头、云台、模式和今日数据。\n"
            "查看隐私状态：查看真实画面是否开启、剩余时间和最近一次隐私复核原因。\n"
            "最近事件：查看今天最近的告警、隐私复核、家属处置等记录。\n"
            "日报：立即生成并发送今日健康日报。\n"
            "系统自检：检查主程序、摄像头、云台串口、网页看板等是否正常。\n\n"
            "二、隐私画面指令\n"
            "我想确认一下 / 临时查看真实画面：申请临时打开真实画面；必须先通过本地大模型隐私复核，通过后限时开启。\n"
            "关闭真实画面：立即关闭真实画面，恢复默认脱敏看护。\n"
            "说明：复核不通过时会显示具体原因，例如服务不可用、模型不确定或画面存在隐私风险。\n\n"
            "三、人物锁定与云台指令\n"
            "锁定当前人物 / 锁定当前目标：把当前画面中的可信人体作为跟随对象。\n"
            "锁定老人：等同于锁定当前人物，用于家属更容易记住。\n"
            "取消锁定：取消固定人物，恢复普通目标跟随。\n"
            "查看锁定状态 / 锁定状态：查看当前锁定对象、轨迹 ID、衣着匹配分和是否正在跟随锁定对象。\n"
            "暂停跟随：云台保持当前位置，不自动追踪。\n"
            "恢复跟随：重新开启自动跟随和无人巡航。\n"
            "云台回中：让云台回到中间位置。\n"
            "左转 / 右转 / 上调 / 下调：手动微调云台方向。\n\n"
            "四、摔倒检测与处置指令\n"
            "保守模式：降低误报，适合日常长期看护。\n"
            "灵敏模式：提高触发速度，适合比赛演示或高风险场景。\n"
            "已确认安全：家属确认现场安全，记录到事件和日报中。\n"
            "误报：家属确认本次告警为误报，系统记录并用于日报统计。\n\n"
            "五、视觉问答\n"
            "可以直接问：他在干什么、现在安全吗、今天活动怎么样。\n"
            "系统默认基于脱敏骨架、状态数据和必要的本地视觉复核回答，不主动发送真实画面。"
        )

    def quick_help(self):
        return (
            "智哨指令菜单\n\n"
            "查看：说明书、实时监控、查看状态、查看隐私状态、最近事件、日报、系统自检\n"
            "隐私：我想确认一下、临时查看真实画面、关闭真实画面\n"
            "锁定：锁定当前人物、锁定老人、取消锁定、查看锁定状态\n"
            "云台：暂停跟随、恢复跟随、云台回中、左转、右转、上调、下调\n"
            "摔倒：保守模式、灵敏模式、已确认安全、误报\n"
            "问答：他在干什么、现在安全吗、今天活动怎么样\n\n"
            "想看每条指令具体功能，请发送：说明书"
        )

    def recent_events_text(self, limit=6):
        events = self.store.list_events(limit=limit, date=self.store.today())
        if not events:
            return "今天还没有记录到看护事件。"
        lines = ["最近看护事件："]
        for event in events:
            lines.append(f"{event.get('ts', '')} {event.get('type', '')}: {event.get('message', '')}")
        return "\n".join(lines)

    def ask_brain(self, question):
        frame = self.frame_hub.get_skeleton()
        state = self.runtime.snapshot()
        privacy_context = (
            f"本次家属的问题是：{question}\n"
            "只回答这个问题，不要主动扩展天气、地点、产品说明、隐私策略、健康建议或监控入口。"
            "注意：你收到的图片是脱敏骨架画面，不是真实摄像头画面。"
            f"当前真实画面{'临时开启' if state.get('raw_video_allowed') else '默认关闭'}。"
            "回答时必须基于脱敏骨架和本地状态判断，不要声称自己看到了真实画面。"
            "如果无法从脱敏骨架判断用户所问内容，直接说当前无法准确判断，不要改答其他话题。"
            "回复保持 3 到 5 句话，可以分析人数、姿态、动作变化、互动关系和安全状态，但不要加入用户没问的天气或产品说明。"
        )
        result = self.brain.ask(question, frame, system_note=privacy_context)
        if not result:
            return {"answer": "云端大脑暂时连接不上，但本地看护、摔倒检测和云台跟随仍在运行。", "need_image": False}
        return result

    def make_reply_gif(self):
        import imageio

        frames = self.frame_hub.get_reply_frames()
        if not frames:
            return None
        gif_path = os.path.join(BASE_DIR, "logs", "temp_reply.gif")
        rgb_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames]
        imageio.mimsave(gif_path, rgb_frames, format="GIF", fps=10, loop=0)
        return gif_path
