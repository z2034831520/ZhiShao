import os
import sys
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# 🚀 斩断乱麻：只使用 Python 标准库和基础矩阵库，彻底免疫外部依赖
from hobot_dnn import pyeasy_dnn as dnn
import numpy as np
import cv2

logger = logging.getLogger("Ultralytics_YOLO")

# =========================================================================
# 🦾 核心内嵌自研引擎：YOLOv8-Pose 矩阵硬件解码级数学公式实现
# =========================================================================

def local_resize_image(img, target_w, target_h, resize_type=1):
    if resize_type == 0:
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    else:
        r = min(target_w / img.shape[1], target_h / img.shape[0])
        new_w, new_h = int(img.shape[1] * r), int(img.shape[0] * r)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8) 
        x_off = (target_w - new_w) // 2
        y_off = (target_h - new_h) // 2
        canvas[y_off:y_off+new_h, x_off:x_off+new_w] = resized
        return canvas

def local_bgr_to_nv12_planes(img):
    yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV_I420)
    h, w = img.shape[:2]
    num_pixels = h * w
    yuv_flat = yuv.reshape(-1)
    Y = yuv_flat[:num_pixels]
    uv = yuv_flat[num_pixels:]
    return Y, uv

def local_filter_classification(cls_output, conf_thres_raw):
    max_scores = np.max(cls_output, axis=-1)
    cls_ids = np.argmax(cls_output, axis=-1)
    valid_indices = np.where(max_scores > conf_thres_raw)[0]
    scores = 1.0 / (1.0 + np.exp(-max_scores[valid_indices]))
    return scores, cls_ids[valid_indices], valid_indices

def local_decode_boxes(box_output, valid_indices, grid_size, stride, weights_static):
    # 💡 直接接收拍扁后的 (N, 64) 矩阵，放心安全索引
    box_output = box_output[valid_indices].reshape(-1, 4, 16)
    
    box_max = np.max(box_output, axis=-1, keepdims=True)
    exp_box = np.exp(box_output - box_max)
    box_output = exp_box / np.sum(exp_box, axis=-1, keepdims=True)
    
    dist = np.sum(box_output * weights_static, axis=-1)
    
    y, x = np.meshgrid(np.arange(grid_size), np.arange(grid_size), indexing='ij')
    anchors = (np.stack((x, y), axis=-1).reshape(-1, 2) + 0.5)[valid_indices]
    
    x1 = (anchors[:, 0] - dist[:, 0]) * stride
    y1 = (anchors[:, 1] - dist[:, 1]) * stride
    x2 = (anchors[:, 0] + dist[:, 2]) * stride
    y2 = (anchors[:, 1] + dist[:, 3]) * stride
    return np.stack([x1, y1, x2, y2], axis=-1)

def local_decode_kpts(kpt_output, valid_indices, grid_size, stride):
    # 💡 接收拍扁后的 (N, 51) 矩阵，彻底解决 axis 0 size 1 越界问题！
    kpt_output = kpt_output[valid_indices].reshape(-1, 17, 3)
    
    kpts_xy = kpt_output[:, :, :2]
    y, x = np.meshgrid(np.arange(grid_size), np.arange(grid_size), indexing='ij')
    anchors = (np.stack((x, y), axis=-1).reshape(-1, 2) + 0.5)[valid_indices]
    
    kpts_xy = (kpts_xy * 2.0 + anchors[:, None, :2] - 0.5) * stride
    kpts_score = 1.0 / (1.0 + np.exp(-kpt_output[:, :, 2:3]))
    return kpts_xy, kpts_score

def local_nms(boxes, scores, iou_threshold):
    if len(boxes) == 0: return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(ovr <= iou_threshold)[0]
        order = order[inds + 1]
    return keep

def local_scale_coords_back(boxes, ori_w, ori_h, input_w, input_h, resize_type=1):
    res = boxes.copy()
    if resize_type == 0:
        res[:, [0, 2]] *= (ori_w / input_w)
        res[:, [1, 3]] *= (ori_h / input_h)
    else:
        gain = min(input_w / ori_w, input_h / ori_h)
        pad_x = (input_w - ori_w * gain) / 2
        pad_y = (input_h - ori_h * gain) / 2
        res[:, [0, 2]] = (res[:, [0, 2]] - pad_x) / gain
        res[:, [1, 3]] = (res[:, [1, 3]] - pad_y) / gain
    return res

def local_scale_kpts_back(kpts_xy, ori_w, ori_h, input_w, input_h, resize_type=1):
    res_xy = kpts_xy.copy()
    if resize_type == 0:
        res_xy[:, :, 0] *= (ori_w / input_w)
        res_xy[:, :, 1] *= (ori_h / input_h)
    else:
        gain = min(input_w / ori_w, input_h / ori_h)
        pad_x = (input_w - ori_w * gain) / 2
        pad_y = (input_h - ori_h * gain) / 2
        res_xy[:, :, 0] = (res_xy[:, :, 0] - pad_x) / gain
        res_xy[:, :, 1] = (res_xy[:, :, 1] - pad_y) / gain
    return res_xy

# =========================================================================
# 🦾 业务类结构封装：保持与 main 调用的接口高度统一
# =========================================================================

@dataclass
class UltralyticsYOLOPoseConfig:
    model_path: str
    classes_num: int = 1
    score_thres: float = 0.25
    nms_thres: float = 0.65
    reg: int = 16
    nkpt: int = 17
    resize_type: int = 1
    strides: List[int] = field(default_factory=lambda: [8, 16, 32])

class UltralyticsYOLOPose:
    def __init__(self, config: UltralyticsYOLOPoseConfig):
        self.cfg = config
        self.conf_thres_raw = -np.log(1.0 / self.cfg.score_thres - 1.0)
        self.weights_static = np.arange(self.cfg.reg, dtype=np.float32)[None, None, :]

        t0 = time.time()
        self.models = dnn.load(self.cfg.model_path)
        print(f"🚀 [自研后处理] 原生 BPU 模型驱动装载完毕，耗时: {(time.time() - t0)*1000:.1f}ms")

        self.model_obj = self.models[0]
        input_shape = self.model_obj.inputs[0].properties.shape
        self.input_h, self.input_w = input_shape[2], input_shape[3]

    def pre_process(self, img: np.ndarray, resize_type: Optional[int] = None) -> np.ndarray:
        resize_type = self.cfg.resize_type if resize_type is None else resize_type
        resized = local_resize_image(img, self.input_w, self.input_h, resize_type)
        y, uv = local_bgr_to_nv12_planes(resized)
        return np.concatenate([y, uv]).astype(np.uint8)

    def forward(self, packed_nv12_img: np.ndarray):
        return self.model_obj.forward(packed_nv12_img)

    def post_process(self, outputs, ori_img_w: int, ori_img_h: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        boxes_all, scores_all, kpts_all = [], [], []

        for level_index, stride in enumerate(self.cfg.strides):
            base_idx = level_index * 3
            
            # 💡 THE CRITICAL FIX: 把 4D 魔方强制拍扁为 (N, 通道数) 的 2D 列表，安全喂给后面的解析器
            cls_output = outputs[base_idx].buffer.reshape(-1, self.cfg.classes_num)
            box_output = outputs[base_idx + 1].buffer.reshape(-1, 4 * self.cfg.reg)
            kpt_output = outputs[base_idx + 2].buffer.reshape(-1, self.cfg.nkpt * 3)

            scores, _cls_ids, valid_indices = local_filter_classification(cls_output, self.conf_thres_raw)
            if valid_indices.size == 0: continue

            grid_size = self.input_h // stride
            boxes = local_decode_boxes(box_output, valid_indices, grid_size, stride, self.weights_static)
            kpts_xy, kpts_score = local_decode_kpts(kpt_output, valid_indices, grid_size, stride)

            boxes_all.append(boxes)
            scores_all.append(scores)
            kpts_all.append(np.concatenate([kpts_xy, kpts_score], axis=-1))

        if not boxes_all:
            return (np.empty((0, 4)), np.empty((0,)), np.empty((0, self.cfg.nkpt, 3)))

        boxes = np.concatenate(boxes_all, axis=0).astype(np.float32)
        scores = np.concatenate(scores_all, axis=0).astype(np.float32)
        kpts = np.concatenate(kpts_all, axis=0).astype(np.float32)

        keep = local_nms(boxes, scores, self.cfg.nms_thres)
        if not keep:
            return (np.empty((0, 4)), np.empty((0,)), np.empty((0, self.cfg.nkpt, 3)))

        boxes, scores, kpts = boxes[keep], scores[keep], kpts[keep]
        
        boxes = local_scale_coords_back(boxes, ori_img_w, ori_img_h, self.input_w, self.input_h, self.cfg.resize_type)
        kpts_xy_scaled = local_scale_kpts_back(kpts[:, :, :2], ori_img_w, ori_img_h, self.input_w, self.input_h, self.cfg.resize_type)
        kpts[:, :, :2] = kpts_xy_scaled

        return boxes, scores, kpts

    def predict(self, img: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ori_img_h, ori_img_w = img.shape[:2]
        packed_nv12 = self.pre_process(img)
        outputs = self.forward(packed_nv12)
        return self.post_process(outputs, ori_img_w, ori_img_h)
