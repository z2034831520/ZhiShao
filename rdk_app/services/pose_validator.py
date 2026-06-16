import cv2
import numpy as np

from settings import CAMERA_HEIGHT, CAMERA_WIDTH


class PoseValidator:
    """Filter BPU pose outputs into trustworthy real-person targets."""

    def __init__(self, mode="conservative"):
        self.mode = mode
        self.last_stats = {"raw": 0, "valid": 0, "rejects": {}}
        self.thresholds = {
            "conservative": {
                "det_score": 0.40,
                "kpt_score": 0.30,
                "fall_kpt_score": 0.48,
                "min_kpts": 5,
                "min_area": 0.018,
                "max_area": 0.96,
            },
            "sensitive": {
                "det_score": 0.32,
                "kpt_score": 0.25,
                "fall_kpt_score": 0.40,
                "min_kpts": 4,
                "min_area": 0.012,
                "max_area": 0.98,
            },
        }

    def set_mode(self, mode):
        self.mode = "sensitive" if mode in {"灵敏", "sensitive"} else "conservative"

    def _cfg(self):
        return self.thresholds[self.mode]

    def _clean_keypoints(self, kpts, threshold):
        cleaned = kpts.copy()
        invalid = cleaned[:, 2] < threshold
        cleaned[invalid, 0] = 0
        cleaned[invalid, 1] = 0
        cleaned[invalid, 2] = 0
        return cleaned

    def _valid_indices(self, kpts, threshold):
        return np.where((kpts[:, 0] > 0) & (kpts[:, 1] > 0) & (kpts[:, 2] >= threshold))[0]

    def _count(self, kpts, indices, threshold):
        return sum(1 for idx in indices if kpts[idx][0] > 0 and kpts[idx][1] > 0 and kpts[idx][2] >= threshold)

    def _screen_like(self, frame, box):
        xmin, ymin, xmax, ymax = [int(v) for v in box]
        h, w = frame.shape[:2]
        xmin, xmax = max(0, xmin), min(w - 1, xmax)
        ymin, ymax = max(0, ymin), min(h - 1, ymax)
        if xmax <= xmin or ymax <= ymin:
            return False
        roi = frame[ymin:ymax, xmin:xmax]
        rh, rw = roi.shape[:2]
        if rh < 80 or rw < 80:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi_area = float(rh * rw)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < roi_area * 0.36:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.03 * peri, True)
            if len(approx) != 4:
                continue
            _x, _y, cw, ch = cv2.boundingRect(approx)
            rect_area = float(cw * ch)
            aspect = cw / max(ch, 1)
            fill = area / max(rect_area, 1.0)
            if rect_area > roi_area * 0.42 and 0.55 <= aspect <= 2.5 and fill > 0.55:
                return True
        return False

    def _appearance(self, frame, box):
        xmin, ymin, xmax, ymax = [int(v) for v in box]
        h, w = frame.shape[:2]
        xmin, xmax = max(0, xmin), min(w - 1, xmax)
        ymin, ymax = max(0, ymin), min(h - 1, ymax)
        bw, bh = xmax - xmin, ymax - ymin
        if bw <= 0 or bh <= 0:
            return None
        tx1 = xmin + int(bw * 0.18)
        tx2 = xmax - int(bw * 0.18)
        ty1 = ymin + int(bh * 0.18)
        ty2 = ymin + int(bh * 0.72)
        roi = frame[max(0, ty1):min(h, ty2), max(0, tx1):min(w, tx2)]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256]).reshape(-1)
        norm = np.linalg.norm(hist)
        if norm <= 1e-6:
            return None
        return (hist / norm).astype(np.float32)

    def validate(self, frame, boxes, scores, kpts_list):
        cfg = self._cfg()
        targets = []
        rejects = {}
        frame_area = float(CAMERA_WIDTH * CAMERA_HEIGHT)

        def reject(reason):
            rejects[reason] = rejects.get(reason, 0) + 1

        for i, kpts in enumerate(kpts_list):
            score = float(scores[i]) if i < len(scores) else 0.0
            if score < cfg["det_score"] or i >= len(boxes):
                reject("检测分数低")
                continue
            xmin, ymin, xmax, ymax = [float(v) for v in boxes[i]]
            xmin, xmax = max(0.0, xmin), min(float(CAMERA_WIDTH - 1), xmax)
            ymin, ymax = max(0.0, ymin), min(float(CAMERA_HEIGHT - 1), ymax)
            bw, bh = xmax - xmin, ymax - ymin
            area = bw * bh
            if area < frame_area * cfg["min_area"] or area > frame_area * cfg["max_area"]:
                reject("人体框尺寸异常")
                continue
            cleaned = self._clean_keypoints(kpts, cfg["kpt_score"])
            valid_indices = self._valid_indices(cleaned, cfg["kpt_score"])
            if len(valid_indices) < cfg["min_kpts"]:
                reject("关键点不足")
                continue
            head = self._count(cleaned, range(0, 5), cfg["kpt_score"])
            shoulders = self._count(cleaned, [5, 6], cfg["kpt_score"])
            hips = self._count(cleaned, [11, 12], cfg["kpt_score"])
            limbs = self._count(cleaned, [7, 8, 9, 10, 13, 14, 15, 16], cfg["kpt_score"])
            upper_body = shoulders >= 1 and (head + limbs) >= 2
            full_body = shoulders >= 1 and hips >= 1 and (head + hips + limbs) >= 4
            if not (upper_body or full_body):
                reject("人体结构不完整")
                continue
            if self._screen_like(frame, (xmin, ymin, xmax, ymax)):
                reject("疑似屏幕/照片")
                continue
            valid_kpts = cleaned[valid_indices]
            kxmin, kymin = np.min(valid_kpts[:, :2], axis=0)
            kxmax, kymax = np.max(valid_kpts[:, :2], axis=0)
            if ((kxmax - kxmin) * (kymax - kymin)) / max(area, 1.0) < 0.05:
                reject("关键点分布异常")
                continue
            fall_points = self._count(cleaned, range(17), cfg["fall_kpt_score"])
            fall_core = (
                self._count(cleaned, [5, 6], cfg["fall_kpt_score"]) >= 2
                and self._count(cleaned, [11, 12], cfg["fall_kpt_score"]) >= 2
                and self._count(cleaned, range(0, 5), cfg["fall_kpt_score"]) >= 1
                and self._count(cleaned, [13, 14, 15, 16], cfg["fall_kpt_score"]) >= 1
            )
            targets.append(
                {
                    "cx": int((xmin + xmax) / 2),
                    "cy": int((ymin + ymax) / 2),
                    "w": bw,
                    "h": bh,
                    "area": area,
                    "box": (xmin, ymin, xmax, ymax),
                    "score": score,
                    "kpts": cleaned,
                    "appearance": self._appearance(frame, (xmin, ymin, xmax, ymax)),
                    "fall_eligible": bool(fall_core and fall_points >= 8),
                    "mode": self.mode,
                }
            )
        self.last_stats = {"raw": len(kpts_list), "valid": len(targets), "rejects": rejects}
        return targets
