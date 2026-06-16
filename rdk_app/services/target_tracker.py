import time

import numpy as np

from settings import CAMERA_WIDTH


class TargetTracker:
    """Stable target IDs, lock selection, and appearance-assisted re-id."""

    def __init__(self):
        self.tracks = {}
        self.next_id = 1
        self.max_age = 8.0
        self.match_threshold = CAMERA_WIDTH * 0.55
        self.locked_name = None
        self.locked_track_id = None
        self.last_locked_snapshot = None
        self.last_locked_seen = 0.0
        self.lock_state = "未锁定"
        self.cloth_score = 0.0
        self.active_target = None
        self.ptz_follow_target = None
        self.follow_reason = "暂无目标"

    def _appearance_similarity(self, left, right):
        if left is None or right is None:
            return 0.0
        return float(np.dot(left, right))

    def _snapshot(self, target):
        return {
            "track_id": target.get("track_id"),
            "cx": float(target["cx"]),
            "cy": float(target["cy"]),
            "area": max(float(target.get("area", 1.0)), 1.0),
            "box": target["box"],
            "appearance": target.get("appearance"),
            "last_seen": time.time(),
        }

    def _iou(self, left, right):
        lx1, ly1, lx2, ly2 = [float(v) for v in left]
        rx1, ry1, rx2, ry2 = [float(v) for v in right]
        ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
        ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        left_area = max(1.0, (lx2 - lx1) * (ly2 - ly1))
        right_area = max(1.0, (rx2 - rx1) * (ry2 - ry1))
        return float(inter / max(1.0, left_area + right_area - inter))

    def _cost(self, track, target):
        dist = np.sqrt((target["cx"] - track["cx"]) ** 2 + (target["cy"] - track["cy"]) ** 2)
        area_ratio = abs(np.log(max(float(target["area"]), 1.0) / max(float(track["area"]), 1.0)))
        appearance = self._appearance_similarity(track.get("appearance"), target.get("appearance"))
        appearance_penalty = (1.0 - appearance) * 90.0 if track.get("appearance") is not None and target.get("appearance") is not None else 0.0
        overlap_bonus = self._iou(track.get("box"), target.get("box")) * 180.0
        return dist + 70.0 * area_ratio + appearance_penalty - overlap_bonus

    def assign_tracks(self, targets):
        now = time.time()
        self.tracks = {tid: t for tid, t in self.tracks.items() if now - t.get("last_seen", 0) <= self.max_age}
        active_id = self.active_target.get("track_id") if self.active_target else None
        if len(targets) == 1 and active_id in self.tracks:
            target = targets[0]
            cost = self._cost(self.tracks[active_id], target)
            overlap = self._iou(self.tracks[active_id].get("box"), target.get("box"))
            appearance = self._appearance_similarity(self.tracks[active_id].get("appearance"), target.get("appearance"))
            if self.locked_track_id == active_id:
                same_locked = cost < CAMERA_WIDTH * 0.55 and (overlap > 0.08 or appearance >= 0.80)
            else:
                same_locked = True
            if same_locked and (cost < CAMERA_WIDTH * 0.85 or overlap > 0.08):
                target["track_id"] = active_id
                self.tracks = {active_id: self._snapshot(target)}
                return targets
        unmatched = set(self.tracks.keys())
        for target in sorted(targets, key=lambda t: t["area"], reverse=True):
            best_id = None
            best_cost = None
            for track_id in unmatched:
                cost = self._cost(self.tracks[track_id], target)
                if best_cost is None or cost < best_cost:
                    best_id = track_id
                    best_cost = cost
            if (
                self.locked_name
                and best_id == self.locked_track_id
                and not self._is_same_locked_candidate(target)
            ):
                best_id = None
            if best_id is not None and best_cost is not None and best_cost < self.match_threshold:
                target["track_id"] = best_id
                unmatched.remove(best_id)
            elif best_id is not None and len(targets) == 1 and len(self.tracks) == 1 and not self.locked_name:
                target["track_id"] = best_id
                unmatched.remove(best_id)
            else:
                target["track_id"] = self.next_id
                self.next_id += 1
            self.tracks[target["track_id"]] = self._snapshot(target)
        return targets

    def choose(self, targets, risk_targets=None):
        targets = self.assign_tracks(targets)
        risk_targets = risk_targets or []
        if risk_targets:
            active = max(risk_targets, key=lambda t: t["area"])
            self.active_target = active
            self.ptz_follow_target = active
            self.follow_reason = "摔倒风险优先：安全复核高于人物锁定"
            return active, self.follow_reason

        if not targets:
            self.active_target = None
            self.ptz_follow_target = None
            if self.locked_name:
                self.lock_state = "锁定目标丢失"
                self.follow_reason = "未跟随：锁定目标暂时不在可信人体列表中"
            else:
                self.follow_reason = "未跟随：画面中暂无可信人体"
            return None, self.follow_reason

        if not self.locked_name:
            active_id = self.active_target.get("track_id") if self.active_target else None
            for target in targets:
                if active_id is not None and target.get("track_id") == active_id:
                    self.active_target = target
                    self.ptz_follow_target = target
                    self.lock_state = "未锁定"
                    self.follow_reason = f"未锁定：延续上一帧可信人体轨迹 ID={active_id}"
                    return target, self.follow_reason
            active = max(targets, key=lambda t: t["area"])
            self.active_target = active
            self.ptz_follow_target = active
            self.lock_state = "未锁定"
            self.follow_reason = "未锁定：默认跟随画面中最大的可信人体"
            return active, self.follow_reason

        for target in targets:
            if target.get("track_id") == self.locked_track_id:
                self.cloth_score = self._appearance_similarity(
                    self.last_locked_snapshot.get("appearance") if self.last_locked_snapshot else None,
                    target.get("appearance"),
                )
                self.last_locked_snapshot = self._snapshot(target)
                self.last_locked_seen = time.time()
                self.lock_state = "身体轨迹锁定"
                self.active_target = target
                self.ptz_follow_target = target
                self.follow_reason = f"正在跟随锁定对象：轨迹 ID={self.locked_track_id}"
                return target, self.follow_reason

        if self.last_locked_snapshot:
            candidates = [target for target in targets if self._is_same_locked_candidate(target)]
            if len(candidates) == 1:
                candidate = candidates[0]
                self.locked_track_id = candidate.get("track_id")
                self.cloth_score = self._appearance_similarity(self.last_locked_snapshot.get("appearance"), candidate.get("appearance"))
                self.last_locked_snapshot = self._snapshot(candidate)
                self.last_locked_seen = time.time()
                self.lock_state = "短时重识别锁定"
                self.active_target = candidate
                self.ptz_follow_target = candidate
                self.follow_reason = f"锁定对象短时回到画面，已重新接回轨迹 ID={self.locked_track_id}"
                return candidate, self.follow_reason

        self.active_target = None
        self.ptz_follow_target = None
        self.lock_state = "锁定目标丢失"
        self.follow_reason = "未跟随：锁定对象丢失，系统不会盲目切到陌生人"
        return None, self.follow_reason

    def _is_same_locked_candidate(self, candidate):
        if not self.last_locked_snapshot:
            return False
        elapsed = time.time() - self.last_locked_seen
        if elapsed > 2.0:
            return False
        dist = np.sqrt(
            (candidate["cx"] - self.last_locked_snapshot["cx"]) ** 2
            + (candidate["cy"] - self.last_locked_snapshot["cy"]) ** 2
        )
        area_ratio = abs(np.log(max(float(candidate["area"]), 1.0) / max(float(self.last_locked_snapshot["area"]), 1.0)))
        cloth = self._appearance_similarity(self.last_locked_snapshot.get("appearance"), candidate.get("appearance"))
        overlap = self._iou(self.last_locked_snapshot.get("box"), candidate.get("box"))
        if overlap >= 0.18 and dist < CAMERA_WIDTH * 0.28 and cloth >= 0.65:
            return True
        return bool(cloth >= 0.86 and dist < CAMERA_WIDTH * 0.24 and area_ratio < 0.35)

    def lock_current(self, name="当前人物"):
        if not self.active_target:
            return False, "当前画面还没有可锁定的人物。"
        self.locked_name = name
        self.locked_track_id = self.active_target.get("track_id")
        self.last_locked_snapshot = self._snapshot(self.active_target)
        self.last_locked_seen = time.time()
        self.lock_state = "身体轨迹锁定"
        self.cloth_score = 1.0
        self.ptz_follow_target = self.active_target
        return True, f"已锁定当前人物轨迹 ID={self.locked_track_id}。"

    def unlock(self):
        self.locked_name = None
        self.locked_track_id = None
        self.last_locked_snapshot = None
        self.last_locked_seen = 0.0
        self.lock_state = "未锁定"
        self.cloth_score = 0.0
        self.ptz_follow_target = self.active_target
        self.follow_reason = "已取消锁定：恢复普通目标跟随"
        return True, "已取消人物锁定，恢复普通目标跟随。"

    def status(self):
        active_id = self.active_target.get("track_id") if self.active_target else None
        ptz_id = self.ptz_follow_target.get("track_id") if self.ptz_follow_target else None
        return {
            "locked_name": self.locked_name,
            "locked_track_id": self.locked_track_id,
            "lock_state": self.lock_state,
            "cloth_score": self.cloth_score,
            "active_track_id": active_id,
            "ptz_follow_track_id": ptz_id,
            "follow_reason": self.follow_reason,
            "following_locked": bool(self.locked_track_id is not None and ptz_id == self.locked_track_id),
        }
