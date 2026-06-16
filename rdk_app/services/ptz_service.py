import time

import numpy as np

from settings import CAMERA_HEIGHT, CAMERA_WIDTH
from core.ptz_controller import ptz


class PTZService:
    """PTZ manual control, target following, and gentle search."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.follow_enabled = True
        self.last_seen = time.time()
        self.last_calc = time.time()
        self.last_cmd = 0.0
        self.search_start = None
        self.manual_hold_until = 0.0
        self.kf_enabled = False
        self.x = np.zeros((4, 1), dtype=np.float32)
        self.p = np.eye(4, dtype=np.float32) * 10
        self.f = np.eye(4, dtype=np.float32)
        self.h = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
        self.q = np.eye(4, dtype=np.float32) * 0.05
        self.r = np.eye(2, dtype=np.float32) * 2

    def set_follow_enabled(self, enabled):
        self.follow_enabled = bool(enabled)
        self.runtime.update(follow_enabled=self.follow_enabled, ptz_mode="跟随/待命" if enabled else "暂停")
        return True, "已恢复自动跟随与巡航。" if enabled else "已暂停自动跟随，云台保持当前位置。"

    def center(self):
        self.manual_hold_until = time.time() + 1.2
        if not ptz.center():
            return False, "云台回中失败：串口不可用或指令未发送成功。"
        self.kf_enabled = False
        self.runtime.update(ptz_mode="手动回中")
        return True, "云台已回到中位，自动跟随短暂停顿。"

    def _current_pan(self):
        return ptz.current_pan if ptz.current_pan >= 0 else 90

    def _current_tilt(self):
        return ptz.current_tilt if ptz.current_tilt >= 0 else 90

    def move(self, direction, step=15):
        self.manual_hold_until = time.time() + 1.2
        if not ptz.ensure_connected():
            return False, "云台串口不可用：请检查 /dev/ttyS1、供电和底板连接。"
        ok = False
        if direction == "left":
            ok = ptz.set_pan(self._current_pan() - step)
            label = "左转"
        elif direction == "right":
            ok = ptz.set_pan(self._current_pan() + step)
            label = "右转"
        elif direction == "up":
            ok = ptz.set_tilt(self._current_tilt() - 12)
            label = "上调"
        elif direction == "down":
            ok = ptz.set_tilt(self._current_tilt() + 12)
            label = "下调"
        else:
            return False, "未知云台方向。"
        if not ok:
            return False, f"云台{label}失败：指令未发送成功，请检查串口连接。"
        self.kf_enabled = False
        self.runtime.update(ptz_mode="手动微调")
        return True, f"云台已{label}。当前角度：水平 {self._current_pan()}°，俯仰 {self._current_tilt()}°。"

    def _init_kf(self, cx, cy):
        self.x = np.array([[cx], [cy], [0], [0]], dtype=np.float32)
        self.p = np.eye(4, dtype=np.float32) * 10
        self.kf_enabled = True

    def _predict(self, dt):
        if not self.kf_enabled:
            return
        self.f[0, 2] = dt
        self.f[1, 3] = dt
        self.x = self.f @ self.x
        self.p = self.f @ self.p @ self.f.T + self.q

    def _update(self, cx, cy):
        z = np.array([[cx], [cy]], dtype=np.float32)
        s = self.h @ self.p @ self.h.T + self.r
        k = self.p @ self.h.T @ np.linalg.inv(s)
        self.x = self.x + k @ (z - self.h @ self.x)
        self.p = self.p - k @ self.h @ self.p

    def follow(self, target):
        if not self.follow_enabled:
            return
        now = time.time()
        if now < self.manual_hold_until:
            self.runtime.update(ptz_mode="手动微调保持")
            return
        dt = max(now - self.last_calc, 0.001)
        self.last_calc = now
        self.last_seen = now
        self.search_start = None
        if not self.kf_enabled:
            self._init_kf(target["cx"], target["cy"])
        else:
            self._predict(dt)
            self._update(target["cx"], target["cy"])
        error_x = float(self.x[0, 0]) - CAMERA_WIDTH / 2
        error_y = float(self.x[1, 0]) - CAMERA_HEIGHT / 2
        if now - self.last_cmd < 0.12:
            return
        moved = False
        if abs(error_x) > CAMERA_WIDTH * 0.12:
            kp = 0.014 * (1.0 + abs(error_x) / (CAMERA_WIDTH / 2))
            moved = ptz.set_pan(ptz.current_pan - error_x * kp) or moved
        if abs(error_y) > CAMERA_HEIGHT * 0.12:
            moved = ptz.set_tilt(ptz.current_tilt + error_y * 0.010) or moved
        if moved:
            self.last_cmd = now
            self.runtime.update(ptz_mode="自动跟随")

    def on_no_target(self):
        if not self.follow_enabled:
            return
        now = time.time()
        if now < self.manual_hold_until:
            self.runtime.update(ptz_mode="手动微调保持")
            return
        if self.kf_enabled and now - self.last_seen <= 2.0:
            dt = max(now - self.last_calc, 0.001)
            self.last_calc = now
            self._predict(dt)
            if now - self.last_cmd > 0.15:
                error_x = float(self.x[0, 0]) - CAMERA_WIDTH / 2
                error_y = float(self.x[1, 0]) - CAMERA_HEIGHT / 2
                moved = False
                if abs(error_x) > CAMERA_WIDTH * 0.08:
                    moved = ptz.set_pan(ptz.current_pan - error_x * 0.010) or moved
                if abs(error_y) > CAMERA_HEIGHT * 0.08:
                    moved = ptz.set_tilt(ptz.current_tilt + error_y * 0.008) or moved
                if moved:
                    self.last_cmd = now
            self.runtime.update(ptz_mode="短时外推")
            return
        self.gentle_search()

    def gentle_search(self):
        now = time.time()
        if now < self.manual_hold_until:
            self.runtime.update(ptz_mode="手动微调保持")
            return
        if self.search_start is None:
            self.search_start = now
            self.kf_enabled = False
        if now - self.last_cmd < 0.35:
            return
        elapsed = now - self.search_start
        pan = 90 + 32 * np.sin(0.45 * elapsed)
        tilt = 90 + 10 * np.sin(0.25 * elapsed)
        moved = ptz.set_pan(pan)
        moved = ptz.set_tilt(tilt) or moved
        if moved:
            self.last_cmd = now
            self.runtime.update(ptz_mode="温和巡航")

    def serial_ok(self):
        return bool(ptz.is_open())
