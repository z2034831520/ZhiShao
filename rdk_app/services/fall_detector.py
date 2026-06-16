import os
import threading
import time
from collections import deque

import cv2
import numpy as np

from settings import BASE_DIR, CAMERA_HEIGHT, CAMERA_WIDTH


class FallDetector:
    """Event-oriented fall detector fed only by trustworthy human targets."""

    MODES = {
        "conservative": {
            "candidate_frames": 10,
            "suspect_seconds": 2.0,
            "cooldown": 25,
            "spine": 25,
            "ratio": 1.18,
            "core_score": 0.48,
            "drop_pixels": 44,
            "low_y": 0.68,
        },
        "sensitive": {
            "candidate_frames": 6,
            "suspect_seconds": 1.2,
            "cooldown": 14,
            "spine": 32,
            "ratio": 1.05,
            "core_score": 0.40,
            "drop_pixels": 34,
            "low_y": 0.62,
        },
    }

    def __init__(self, store, brain, alert_callback):
        self.store = store
        self.brain = brain
        self.alert_callback = alert_callback
        self.mode = "conservative"
        self.state = "NORMAL"
        self.candidate_frames = 0
        self.clear_frames = 0
        self.candidate_start = 0.0
        self.last_validation = 0.0
        self.is_validating = False
        self.history = deque(maxlen=24)
        self.current_track_id = None
        self.last_reason = "姿态平稳"

    def set_mode(self, mode):
        self.mode = "sensitive" if mode in {"灵敏", "sensitive"} else "conservative"
        self._reset_motion_history()
        self.store.set_metrics(fall_mode=self.mode_label())
        return True, f"摔倒检测已切换为{self.mode_label()}模式。"

    def mode_label(self):
        return "灵敏" if self.mode == "sensitive" else "保守"

    def _conf(self):
        return self.MODES[self.mode]

    def _reset_motion_history(self):
        self.history.clear()
        self.candidate_frames = 0
        self.clear_frames = 0
        self.candidate_start = 0.0
        self.last_reason = "姿态平稳"

    def _valid_y(self, kpts, indices, score):
        return [float(kpts[i][1]) for i in indices if kpts[i][0] > 0 and kpts[i][1] > 0 and kpts[i][2] >= score]

    def _pose_features(self, target):
        if not target or not target.get("fall_eligible"):
            return None
        kpts = target["kpts"]
        cfg = self._conf()
        score = cfg["core_score"]
        required = [5, 6, 11, 12]
        if any(kpts[i][2] < score for i in required):
            return None

        head_y = self._valid_y(kpts, range(0, 5), score)
        leg_y = self._valid_y(kpts, [13, 14, 15, 16], score)
        if not head_y or not leg_y:
            return None

        sl, sr = kpts[5], kpts[6]
        hl, hr = kpts[11], kpts[12]
        shoulder_x, shoulder_y = (sl[0] + sr[0]) / 2, (sl[1] + sr[1]) / 2
        hip_x, hip_y = (hl[0] + hr[0]) / 2, (hl[1] + hr[1]) / 2
        raw_angle = abs(np.degrees(np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x)))
        spine_angle = raw_angle if raw_angle <= 90 else 180 - raw_angle

        xmin, ymin, xmax, ymax = target["box"]
        box_w, box_h = xmax - xmin, ymax - ymin
        horizontal = spine_angle < cfg["spine"] and box_w > box_h * cfg["ratio"]
        inverted = max(head_y) > hip_y + box_h * 0.12
        low_position = ymax > CAMERA_HEIGHT * cfg["low_y"] or hip_y > CAMERA_HEIGHT * (cfg["low_y"] - 0.08)

        return {
            "ts": time.time(),
            "track_id": target.get("track_id"),
            "cx": float(target["cx"]),
            "cy": float(target["cy"]),
            "hip_y": float(hip_y),
            "area": max(float(target.get("area", 1.0)), 1.0),
            "box_h": max(float(box_h), 1.0),
            "horizontal": bool(horizontal),
            "inverted": bool(inverted),
            "low_position": bool(low_position),
            "spine_angle": float(spine_angle),
            "box_ratio": float(box_w / max(box_h, 1.0)),
        }

    def _append_history(self, track_id, features):
        if track_id != self.current_track_id:
            self.current_track_id = track_id
            self._reset_motion_history()
        self.history.append(features)

    def _history_signals(self, features):
        now = features["ts"]
        recent = [item for item in self.history if now - item["ts"] <= 1.8]
        if len(recent) < 2:
            vertical_drop = 0.0
        else:
            vertical_drop = features["cy"] - recent[0]["cy"]

        cfg = self._conf()
        drop_threshold = max(cfg["drop_pixels"], features["box_h"] * 0.16)
        rapid_drop = vertical_drop > drop_threshold
        horizontal_frames = sum(1 for item in self.history if item["horizontal"])
        low_frames = sum(1 for item in self.history if item["low_position"])
        sustained_lie = horizontal_frames >= cfg["candidate_frames"] and low_frames >= max(2, cfg["candidate_frames"] // 2)
        return rapid_drop, sustained_lie, vertical_drop

    def _analyze(self, target, update_history=False):
        features = self._pose_features(target)
        if not features:
            return False, "骨架不完整", {}
        if update_history:
            self._append_history(features["track_id"], features)

        rapid_drop, sustained_lie, vertical_drop = self._history_signals(features)
        postural_risk = features["horizontal"] or features["inverted"]
        ground_event = features["horizontal"] and (features["low_position"] or rapid_drop or sustained_lie)
        inverted_event = features["inverted"] and (features["low_position"] or rapid_drop)
        triggered = bool(ground_event or inverted_event)

        if triggered:
            if features["inverted"]:
                reason = "倒置姿态并伴随低位/下降"
                fall_type = "INVERTED_FALL"
            elif rapid_drop:
                reason = f"横倒姿态并出现明显下坠 {vertical_drop:.0f}px"
                fall_type = "DROP_TO_GROUND"
            elif sustained_lie:
                reason = "横倒低位姿态持续存在"
                fall_type = "SUSTAINED_GROUND_FALL"
            else:
                reason = "横倒低位姿态"
                fall_type = "GROUND_FALL"
            self.last_reason = reason
            return True, fall_type, features

        if postural_risk:
            self.last_reason = "姿态异常但未满足倒地事件条件"
        else:
            self.last_reason = "姿态平稳"
        return False, "NORMAL", features

    def quick_risk_targets(self, targets):
        risky = []
        for target in targets:
            triggered, _fall_type, _features = self._analyze(target, update_history=False)
            if triggered:
                risky.append(target)
        return risky

    def update(self, target, raw_frame, skeleton_frame):
        triggered, fall_type, features = self._analyze(target, update_history=True)
        now = time.time()
        cfg = self._conf()

        if triggered:
            self.clear_frames = 0
            if self.state in {"CONFIRMED", "REJECTED", "VALIDATION_FAILED"} and now - self.last_validation < cfg["cooldown"]:
                return self.state
            if self.state == "VALIDATING":
                return self.state
            if self.state == "NORMAL":
                self.state = "CANDIDATE"
                self.candidate_frames = 1
                self.candidate_start = now
            elif self.state == "CANDIDATE":
                self.candidate_frames += 1

            enough_frames = self.candidate_frames >= cfg["candidate_frames"]
            enough_time = now - self.candidate_start >= cfg["suspect_seconds"]
            if self.state == "CANDIDATE" and enough_frames and enough_time:
                self._enter_suspect(target, fall_type)
                self._start_validation_if_needed(target, raw_frame, skeleton_frame, fall_type)
            elif self.state == "SUSPECT":
                self._start_validation_if_needed(target, raw_frame, skeleton_frame, fall_type)
        else:
            self.clear_frames += 1
            if self.clear_frames >= 5 and self.state in {"CANDIDATE", "SUSPECT", "REJECTED", "VALIDATION_FAILED"}:
                self.state = "NORMAL"
                self._reset_motion_history()
            elif self.clear_frames >= 10 and self.state == "CONFIRMED":
                self.state = "NORMAL"
                self._reset_motion_history()

        return self.state

    def _enter_suspect(self, target, fall_type):
        if self.state == "SUSPECT":
            return
        self.state = "SUSPECT"
        self.store.add_metrics(suspect_fall_count=1)
        self.store.record_event(
            "fall_suspect",
            f"检测到连续倒地事件：{self.last_reason}，已进入云端复核。",
            "warning",
            {"fall_type": fall_type, "track_id": target.get("track_id"), "mode": self.mode_label()},
        )

    def _start_validation_if_needed(self, target, raw_frame, skeleton_frame, fall_type):
        now = time.time()
        if self.is_validating or now - self.last_validation < self._conf()["cooldown"]:
            return
        self.is_validating = True
        self.last_validation = now
        self.state = "VALIDATING"
        roi = self._crop_roi(raw_frame, target["box"])
        evidence = skeleton_frame.copy() if skeleton_frame is not None else raw_frame.copy()
        threading.Thread(target=self._validate_async, args=(roi, evidence, fall_type), daemon=True).start()

    def _crop_roi(self, frame, box):
        h, w = frame.shape[:2]
        xmin, ymin, xmax, ymax = [int(v) for v in box]
        pad = int(CAMERA_WIDTH * 0.18)
        return frame[max(0, ymin - pad):min(h, ymax + pad), max(0, xmin - pad):min(w, xmax + pad)]

    def _validate_async(self, roi_image, skeleton_image, fall_type):
        try:
            os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
            roi_path = os.path.join(BASE_DIR, "logs", "suspect_roi.jpg")
            evidence_path = os.path.join(BASE_DIR, "logs", "critical_evidence.jpg")
            cv2.imwrite(roi_path, roi_image)
            cv2.imwrite(evidence_path, skeleton_image)
            result = self.brain.analyze_critical_event(roi_path)
            if result and result.get("risk_level") == "critical":
                description = result.get("description", "发现高风险摔倒行为。")
                location = result.get("location", "看护区域")
                self.state = "CONFIRMED"
                self.store.add_metrics(confirmed_fall_count=1)
                self.store.record_event(
                    "fall_confirmed",
                    "云端复核确认高风险摔倒。",
                    "critical",
                    {"description": description, "location": location, "fall_type": fall_type, "evidence_path": evidence_path},
                )
                self.alert_callback(description, location)
            elif result:
                self.state = "REJECTED"
                self.store.add_metrics(rejected_fall_count=1)
                self.store.record_event("fall_rejected", "疑似摔倒已由云端复核拦截。", "info", {"fall_type": fall_type})
            else:
                self.state = "VALIDATION_FAILED"
                self.store.add_metrics(validation_failed_count=1)
                self.store.record_event("validation_failed", "云端复核失败，未确认为告警。", "warning", {"fall_type": fall_type})
        except Exception as exc:
            self.state = "VALIDATION_FAILED"
            self.store.add_metrics(validation_failed_count=1)
            self.store.record_event("validation_failed", "云端复核异常，未确认为告警。", "warning", {"error": str(exc)})
        finally:
            self.is_validating = False
