import threading
import time
from collections import deque

import cv2
import numpy as np

from settings import CAMERA_HEIGHT, CAMERA_WIDTH
from services.text_overlay import draw_chinese_text


class FrameHub:
    """Thread-safe in-memory frame exchange for camera, vision, and web."""

    def __init__(self, buffer_size=30):
        self.lock = threading.Lock()
        self.raw_frame = None
        self.skeleton_frame = None
        self.reply_frames = deque(maxlen=buffer_size)
        self.raw_timestamp = 0.0
        self.skeleton_timestamp = 0.0

    def update_raw(self, frame):
        with self.lock:
            self.raw_frame = frame.copy()
            self.raw_timestamp = time.time()

    def update_skeleton(self, frame):
        with self.lock:
            self.skeleton_frame = frame.copy()
            self.reply_frames.append(frame.copy())
            self.skeleton_timestamp = time.time()

    def get_raw(self):
        with self.lock:
            return None if self.raw_frame is None else self.raw_frame.copy()

    def get_skeleton(self):
        with self.lock:
            return None if self.skeleton_frame is None else self.skeleton_frame.copy()

    def raw_age(self):
        with self.lock:
            return 999.0 if not self.raw_timestamp else max(0.0, time.time() - self.raw_timestamp)

    def skeleton_age(self):
        with self.lock:
            return 999.0 if not self.skeleton_timestamp else max(0.0, time.time() - self.skeleton_timestamp)

    def get_reply_frames(self):
        with self.lock:
            return [frame.copy() for frame in self.reply_frames]

    def blank_frame(self, text="智哨正在等待摄像头画面..."):
        canvas = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
        canvas[:] = (18, 24, 32)
        return draw_chinese_text(canvas, text, (36, CAMERA_HEIGHT // 2), size=26, color=(180, 220, 255))

    def privacy_frame(self, text="真实画面未开启"):
        canvas = np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
        canvas[:] = (14, 20, 26)
        lines = [
            "智哨隐私守护中",
            text,
            "默认展示：安心状态 + 脱敏骨架画面",
        ]
        y = CAMERA_HEIGHT // 2 - 54
        for line in lines:
            canvas = draw_chinese_text(canvas, line, (36, y), size=24, color=(190, 230, 255))
            y += 46
        return canvas


class RuntimeState:
    """Small shared state object for services that need fast status reads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.camera_ok = False
        self.camera_message = "未启动"
        self.vlm_ok = False
        self.feishu_ok = False
        self.follow_enabled = True
        self.ptz_mode = "跟随/待命"
        self.fall_mode = "保守"
        self.fall_state = "NORMAL"
        self.locked_name = None
        self.locked_track_id = None
        self.lock_state = "未锁定"
        self.cloth_score = 0.0
        self.active_track_id = None
        self.ptz_follow_track_id = None
        self.follow_reason = "暂无目标"
        self.following_locked = False
        self.target_count = 0
        self.raw_pose_count = 0
        self.pose_rejects = {}
        self.last_seen_time = ""
        self.monitor_url = ""
        self.care_mode = "边界看护"
        self.raw_video_allowed_until = 0.0
        self.raw_video_reason = ""

    def update(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def allow_raw_video(self, seconds=180, reason="家属临时确认安全"):
        until = time.time() + max(5, int(seconds))
        with self.lock:
            self.raw_video_allowed_until = until
            self.raw_video_reason = reason
        return until

    def close_raw_video(self):
        with self.lock:
            self.raw_video_allowed_until = 0.0
            self.raw_video_reason = ""

    def raw_video_allowed(self):
        with self.lock:
            return time.time() < self.raw_video_allowed_until

    def raw_seconds_left(self):
        with self.lock:
            return max(0, int(self.raw_video_allowed_until - time.time()))

    def snapshot(self):
        with self.lock:
            raw_left = max(0, int(self.raw_video_allowed_until - time.time()))
            return {
                "running": self.running,
                "camera_ok": self.camera_ok,
                "camera_message": self.camera_message,
                "vlm_ok": self.vlm_ok,
                "feishu_ok": self.feishu_ok,
                "follow_enabled": self.follow_enabled,
                "ptz_mode": self.ptz_mode,
                "fall_mode": self.fall_mode,
                "fall_state": self.fall_state,
                "locked_name": self.locked_name,
                "locked_track_id": self.locked_track_id,
                "lock_state": self.lock_state,
                "cloth_score": self.cloth_score,
                "active_track_id": self.active_track_id,
                "ptz_follow_track_id": self.ptz_follow_track_id,
                "follow_reason": self.follow_reason,
                "following_locked": self.following_locked,
                "target_count": self.target_count,
                "raw_pose_count": self.raw_pose_count,
                "pose_rejects": self.pose_rejects,
                "last_seen_time": self.last_seen_time,
                "monitor_url": self.monitor_url,
                "care_mode": self.care_mode,
                "raw_video_allowed": raw_left > 0,
                "raw_video_seconds_left": raw_left,
                "raw_video_reason": self.raw_video_reason,
            }
