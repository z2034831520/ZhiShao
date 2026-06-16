import os
import threading
import time

import cv2
import numpy as np

from settings import BASE_DIR, CAMERA_HEIGHT, CAMERA_INDEX, CAMERA_WIDTH, FPS_BUFFER_SIZE
from services.fall_detector import FallDetector
from services.pose_validator import PoseValidator
from services.target_tracker import TargetTracker
from services.text_overlay import draw_chinese_text


class VisionWorker:
    """Camera reader + BPU pose inference + target/fall/PTZ pipeline."""

    FALL_STATE_LABELS = {
        "NORMAL": "状态平稳",
        "CANDIDATE": "姿态观察",
        "SUSPECT": "疑似摔倒",
        "VALIDATING": "云端复核中",
        "CONFIRMED": "已确认告警",
        "REJECTED": "已拦截误报",
        "VALIDATION_FAILED": "复核失败",
    }

    SKELETON_EDGES = [
        (0, 1), (0, 2), (1, 3), (2, 4),
        (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
        (5, 11), (6, 12), (11, 12),
        (11, 13), (13, 15), (12, 14), (14, 16),
    ]

    def __init__(self, frame_hub, runtime, store, ptz_service, brain, alert_callback):
        self.frame_hub = frame_hub
        self.runtime = runtime
        self.store = store
        self.ptz_service = ptz_service
        self.validator = PoseValidator()
        self.tracker = TargetTracker()
        self.fall_detector = FallDetector(store, brain, alert_callback)
        self.cap = None
        self.running = False
        self.raw_lock = threading.Lock()
        self.latest_raw = None
        self.last_metrics_time = time.time()
        self.last_camera_attempt = 0.0
        self.last_seen_center = (CAMERA_WIDTH // 2, CAMERA_HEIGHT // 2)
        self.is_moving = False
        self.smooth_tracks = {}
        self.smooth_alpha = 0.35
        self._load_model()

    def _load_model(self):
        from core.yolo_pose_decoder import UltralyticsYOLOPose, UltralyticsYOLOPoseConfig

        model_path = os.path.join(BASE_DIR, "yolov8n-pose.bin")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"找不到 BPU 模型文件：{model_path}")
        config = UltralyticsYOLOPoseConfig(model_path=model_path, classes_num=1, score_thres=0.35, nms_thres=0.65)
        self.bpu_model = UltralyticsYOLOPose(config)

    def set_fall_mode(self, mode):
        self.validator.set_mode(mode)
        ok, reply = self.fall_detector.set_mode(mode)
        self.runtime.update(fall_mode=self.fall_detector.mode_label())
        return ok, reply

    def lock_current(self, name="当前人物"):
        ok, reply = self.tracker.lock_current(name)
        self._publish_lock_state()
        return ok, reply

    def unlock(self):
        ok, reply = self.tracker.unlock()
        self._publish_lock_state()
        return ok, reply

    def lock_status_text(self):
        status = self.tracker.status()
        return (
            f"锁定对象: {status.get('locked_name') or '未锁定'}\n"
            f"锁定轨迹ID: {status.get('locked_track_id') or '无'}\n"
            f"当前跟随轨迹ID: {status.get('active_track_id') or '无'}\n"
            f"云台跟随轨迹ID: {status.get('ptz_follow_track_id') or '无'}\n"
            f"是否正在跟随锁定对象: {'是' if status.get('following_locked') else '否'}\n"
            f"锁定状态: {status.get('lock_state')}\n"
            f"跟随原因: {status.get('follow_reason')}\n"
            f"衣着匹配分数: {status.get('cloth_score', 0):.2f}\n"
            f"锁定方式: 骨架轨迹 + 身体框 + 衣着颜色，不使用人脸识别"
        )

    def _publish_lock_state(self):
        status = self.tracker.status()
        self.runtime.update(
            locked_name=status["locked_name"],
            locked_track_id=status["locked_track_id"],
            lock_state=status["lock_state"],
            cloth_score=status["cloth_score"],
            active_track_id=status["active_track_id"],
            ptz_follow_track_id=status["ptz_follow_track_id"],
            follow_reason=status["follow_reason"],
            following_locked=status["following_locked"],
        )

    def _open_camera(self):
        self.last_camera_attempt = time.time()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok = bool(self.cap.isOpened())
        self.runtime.update(camera_ok=ok, camera_message=f"已打开索引 {CAMERA_INDEX}" if ok else f"无法打开索引 {CAMERA_INDEX}")
        print(f"{'📷' if ok else '⚠️'} [摄像头] {self.runtime.snapshot()['camera_message']}")
        return ok

    def start(self):
        self.running = True
        self.runtime.update(running=True)
        self._open_camera()
        threading.Thread(target=self._camera_loop, daemon=True).start()
        threading.Thread(target=self._vision_loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.runtime.update(running=False)
        if self.cap is not None:
            self.cap.release()

    def _camera_loop(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                if time.time() - self.last_camera_attempt >= 2.0:
                    self._open_camera()
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if ret and frame is not None:
                self.frame_hub.update_raw(frame)
                with self.raw_lock:
                    self.latest_raw = frame.copy()
                self.runtime.update(camera_ok=True, camera_message="画面正常")
            else:
                self.runtime.update(camera_ok=False, camera_message="读取失败，正在重连")
                if time.time() - self.last_camera_attempt >= 2.0:
                    self._open_camera()
                time.sleep(0.05)
            time.sleep(0.005)

    def _vision_loop(self):
        blank = self.frame_hub.blank_frame()
        while self.running:
            with self.raw_lock:
                frame = None if self.latest_raw is None else self.latest_raw.copy()
            if frame is None:
                self.frame_hub.update_skeleton(blank)
                self.ptz_service.on_no_target()
                time.sleep(0.05)
                continue
            try:
                boxes, scores, kpts_list = self.bpu_model.predict(frame)
                targets = self.validator.validate(frame, boxes, scores, kpts_list)
                risk_targets = self.fall_detector.quick_risk_targets(targets)
                active, _reason = self.tracker.choose(targets, risk_targets)
                self._smooth_targets(targets)
                follow_target = self.tracker.ptz_follow_target
                skeleton = self._draw_skeleton(frame, targets, active, follow_target, risk_targets)
                self.frame_hub.update_skeleton(skeleton)
                if follow_target:
                    self.ptz_service.follow(follow_target)
                    self._update_motion(follow_target)
                else:
                    self.ptz_service.on_no_target()
                if active:
                    self.fall_detector.update(active, frame, skeleton)
                self._publish_state(targets)
                self._record_metrics(bool(active or follow_target), len(targets))
            except Exception as exc:
                self.store.record_event("vision_error", "视觉线程异常。", "warning", {"error": str(exc)})
                time.sleep(0.1)

    def _smooth_targets(self, targets):
        now = time.time()
        live_ids = set()
        for target in targets:
            track_id = target.get("track_id")
            if track_id is None:
                continue
            live_ids.add(track_id)
            box = np.array(target["box"], dtype=np.float32)
            kpts = target["kpts"].astype(np.float32).copy()
            state = self.smooth_tracks.get(track_id)
            if state is None:
                self.smooth_tracks[track_id] = {"box": box, "kpts": kpts, "last": now}
                continue
            alpha = self.smooth_alpha
            state["box"] = alpha * box + (1.0 - alpha) * state["box"]
            prev_kpts = state["kpts"]
            valid = kpts[:, 2] > 0
            kpts[valid, :2] = alpha * kpts[valid, :2] + (1.0 - alpha) * prev_kpts[valid, :2]
            state["kpts"] = kpts
            state["last"] = now
            target["box"] = tuple(float(v) for v in state["box"])
            target["kpts"] = state["kpts"].copy()
            xmin, ymin, xmax, ymax = target["box"]
            target["cx"] = int((xmin + xmax) / 2)
            target["cy"] = int((ymin + ymax) / 2)
            target["w"] = float(xmax - xmin)
            target["h"] = float(ymax - ymin)
            target["area"] = float(max(1.0, target["w"] * target["h"]))
        self.smooth_tracks = {
            tid: state for tid, state in self.smooth_tracks.items()
            if tid in live_ids or now - state.get("last", 0) <= 1.5
        }

    def _draw_skeleton(self, frame, targets, active, follow_target=None, risk_targets=None):
        raw = frame.copy()
        skeleton = np.zeros_like(frame)
        locked_id = self.tracker.locked_track_id
        active_id = active.get("track_id") if active else None
        ptz_id = follow_target.get("track_id") if follow_target else None
        risk_ids = {target.get("track_id") for target in (risk_targets or [])}
        for target in targets:
            color, thickness, label = self._target_style(target, active_id, locked_id, ptz_id, risk_ids)
            xmin, ymin, xmax, ymax = [int(v) for v in target["box"]]
            cv2.rectangle(raw, (xmin, ymin), (xmax, ymax), color, thickness)
            cv2.rectangle(skeleton, (xmin, ymin), (xmax, ymax), color, thickness)
            raw = self._draw_target_label(raw, label, (xmin, ymin), color)
            skeleton = self._draw_target_label(skeleton, label, (xmin, ymin), color)
            kpts = target["kpts"]
            for kx, ky, conf in kpts:
                if kx > 0 and ky > 0 and conf > 0:
                    point_color = color if target.get("track_id") == locked_id else (0, 255, 127)
                    cv2.circle(raw, (int(kx), int(ky)), 4, point_color, -1)
                    cv2.circle(skeleton, (int(kx), int(ky)), 4, point_color, -1)
            for a, b in self.SKELETON_EDGES:
                x1, y1, c1 = kpts[a]
                x2, y2, c2 = kpts[b]
                if x1 > 0 and y1 > 0 and x2 > 0 and y2 > 0 and c1 > 0 and c2 > 0:
                    line_color = color if target.get("track_id") == locked_id else (190, 80, 255)
                    cv2.line(raw, (int(x1), int(y1)), (int(x2), int(y2)), line_color, thickness)
                    cv2.line(skeleton, (int(x1), int(y1)), (int(x2), int(y2)), line_color, thickness)
        status = self.runtime.snapshot()
        state_label = self.FALL_STATE_LABELS.get(self.fall_detector.state, self.fall_detector.state)
        overlay = f"摔倒检测：{status['fall_mode']}｜{state_label}｜{self.tracker.lock_state}｜{self.tracker.follow_reason}"
        raw = draw_chinese_text(raw, overlay, (10, 12), size=22, color=(0, 255, 255))
        if not targets:
            stats = getattr(self.validator, "last_stats", {})
            raw_count = stats.get("raw", 0)
            rejects = stats.get("rejects", {})
            reason = "，".join(f"{k}{v}" for k, v in list(rejects.items())[:2]) or "暂无候选"
            hint = f"未形成可信骨架｜候选 {raw_count}｜{reason}"
            skeleton = draw_chinese_text(skeleton, hint, (18, 18), size=17, color=(180, 220, 255))
            raw = draw_chinese_text(raw, hint, (10, 42), size=16, color=(180, 220, 255))
        self.raw_overlay = raw
        return skeleton

    def _target_style(self, target, active_id, locked_id, ptz_id=None, risk_ids=None):
        track_id = target.get("track_id")
        locked_name = self.tracker.locked_name or "锁定对象"
        risk_ids = risk_ids or set()
        if track_id in risk_ids:
            return (0, 0, 255), 4, f"风险临时复核: ID={track_id}"
        if locked_id is not None and track_id == locked_id:
            label = f"已锁定: {locked_name} ID={track_id}"
            if ptz_id == locked_id:
                label = f"已锁定并跟随: {locked_name} ID={track_id}"
            return (0, 215, 255), 4, label
        if ptz_id is not None and track_id == ptz_id:
            if locked_id is not None:
                return (0, 255, 0), 3, f"当前云台跟随: ID={track_id}"
            return (0, 255, 0), 3, f"当前跟随: ID={track_id}"
        return (140, 140, 140), 1, f"候选目标: ID={track_id}"

    def _draw_target_label(self, frame, text, top_left, color):
        x, y = top_left
        y = max(4, y - 25)
        x = max(4, x)
        width = min(frame.shape[1] - x - 4, max(140, len(text) * 14))
        cv2.rectangle(frame, (x, y), (x + width, y + 22), (8, 18, 28), -1)
        cv2.rectangle(frame, (x, y), (x + width, y + 22), color, 1)
        return draw_chinese_text(frame, text, (x + 5, y + 2), size=15, color=(245, 245, 245))

    def get_raw_monitor_frame(self):
        frame = getattr(self, "raw_overlay", None)
        if frame is not None:
            return frame.copy()
        return self.frame_hub.get_raw()

    def _update_motion(self, target):
        cx, cy = target["cx"], target["cy"]
        shift = np.sqrt((cx - self.last_seen_center[0]) ** 2 + (cy - self.last_seen_center[1]) ** 2)
        self.is_moving = shift > 8
        self.last_seen_center = (cx, cy)

    def _publish_state(self, targets):
        self._publish_lock_state()
        stats = getattr(self.validator, "last_stats", {})
        self.runtime.update(
            fall_state=self.fall_detector.state,
            fall_mode=self.fall_detector.mode_label(),
            target_count=len(targets),
            raw_pose_count=stats.get("raw", 0),
            pose_rejects=stats.get("rejects", {}),
            last_seen_time=self.store.now_text() if targets else self.runtime.snapshot().get("last_seen_time", ""),
        )

    def _record_metrics(self, detected, target_count):
        now = time.time()
        elapsed = now - self.last_metrics_time
        if elapsed < 3.0:
            return
        self.last_metrics_time = now
        increments = {"online_seconds": elapsed, "total_frames": 1}
        if detected:
            increments["seen_seconds"] = elapsed
            increments["target_seen_frames"] = 1
            if self.is_moving:
                increments["active_seconds"] = elapsed
            self.store.set_metrics(last_seen_time=self.store.now_text(), fall_mode=self.fall_detector.mode_label())
        if self.runtime.snapshot().get("ptz_mode") == "温和巡航":
            increments["search_seconds"] = elapsed
        self.store.add_metrics(**increments)
