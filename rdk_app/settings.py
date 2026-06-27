import os
from pathlib import Path

# =========================================================================
# 智哨 ZhiShao V3 基础配置
# =========================================================================
PRODUCT_NAME = "智哨 ZhiShao 智能云台看护系统"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    env_path = Path(BASE_DIR) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(name, default=""):
    return os.environ.get(name, default)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


# =========================================================================
# 摄像头与云台
# =========================================================================
CAMERA_INDEX = _env_int("ZHISHAO_CAMERA_INDEX", 0)
CAMERA_WIDTH = _env_int("ZHISHAO_CAMERA_WIDTH", 640)
CAMERA_HEIGHT = _env_int("ZHISHAO_CAMERA_HEIGHT", 480)

PTZ_PORT = _env("ZHISHAO_PTZ_PORT", "/dev/ttyS1")
PTZ_BAUDRATE = _env_int("ZHISHAO_PTZ_BAUDRATE", 9600)

PTZ_DEADZONE_X = _env_int("ZHISHAO_PTZ_DEADZONE_X", 30)
PTZ_DEADZONE_Y = _env_int("ZHISHAO_PTZ_DEADZONE_Y", 30)
PTZ_KP_X = _env_float("ZHISHAO_PTZ_KP_X", 0.15)
PTZ_KP_Y = _env_float("ZHISHAO_PTZ_KP_Y", 0.15)


# =========================================================================
# 云端大脑服务
# =========================================================================
VLM_SERVER_IP = _env("ZHISHAO_VLM_SERVER_IP", "192.168.43.100")
VLM_SERVER_PORT = _env_int("ZHISHAO_VLM_SERVER_PORT", 9000)
VLM_BASE_URL = _env("ZHISHAO_VLM_BASE_URL", f"http://{VLM_SERVER_IP}:{VLM_SERVER_PORT}")

BRAIN_URL_ANALYZE = _env("ZHISHAO_BRAIN_URL_ANALYZE", f"{VLM_BASE_URL}/analyze")
BRAIN_URL_ASK = _env("ZHISHAO_BRAIN_URL_ASK", f"{VLM_BASE_URL}/ask")
BRAIN_URL_SUMMARIZE = _env("ZHISHAO_BRAIN_URL_SUMMARIZE", f"{VLM_BASE_URL}/summarize")
BRAIN_URL_PRIVACY_CHECK = _env("ZHISHAO_BRAIN_URL_PRIVACY_CHECK", f"{VLM_BASE_URL}/privacy_check")



# =========================================================================
# 看护地点
# 公网 IP 定位会受手机热点、运营商出口影响，产品演示默认使用固定看护地点。
# =========================================================================
CARE_CITY = _env("ZHISHAO_CARE_CITY", "马鞍山")
CARE_LOCATION = _env("ZHISHAO_CARE_LOCATION", "中国 安徽 马鞍山")
USE_IP_GEOLOCATION = _env_bool("ZHISHAO_USE_IP_GEOLOCATION", False)


# =========================================================================
# 飞书通信配置
# 真实值请写入本目录 .env 或系统环境变量，不要写进源码。
# =========================================================================
FEISHU_WEBHOOK = _env("FEISHU_WEBHOOK")
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")


# =========================================================================
# 算法阈值与自动化配置
# =========================================================================
FPS_BUFFER_SIZE = _env_int("ZHISHAO_FPS_BUFFER_SIZE", 30)
ALERT_COOLDOWN = _env_int("ZHISHAO_ALERT_COOLDOWN", 15)
STATIONARY_TIME_LIMIT = _env_int("ZHISHAO_STATIONARY_TIME_LIMIT", 30)

REPORT_HOUR = _env_int("ZHISHAO_REPORT_HOUR", 20)
REPORT_MINUTE = _env_int("ZHISHAO_REPORT_MINUTE", 30)

POSE_DETECTION_SCORE_THRESHOLD = _env_float("ZHISHAO_POSE_SCORE_THRESHOLD", 0.45)
POSE_KEYPOINT_CONF_THRESHOLD = _env_float("ZHISHAO_KEYPOINT_CONF_THRESHOLD", 0.35)
POSE_FALL_KEYPOINT_CONF_THRESHOLD = _env_float("ZHISHAO_FALL_KEYPOINT_CONF_THRESHOLD", 0.45)
POSE_MIN_VALID_KEYPOINTS = _env_int("ZHISHAO_POSE_MIN_VALID_KEYPOINTS", 6)
POSE_MIN_TARGET_AREA_RATIO = _env_float("ZHISHAO_POSE_MIN_TARGET_AREA_RATIO", 0.012)
POSE_MAX_TARGET_AREA_RATIO = _env_float("ZHISHAO_POSE_MAX_TARGET_AREA_RATIO", 0.82)
FALL_CONSECUTIVE_FRAMES = _env_int("ZHISHAO_FALL_CONSECUTIVE_FRAMES", 8)
FALL_CONFIRM_SECONDS = _env_float("ZHISHAO_FALL_CONFIRM_SECONDS", 1.8)
FALL_CLEAR_FRAMES = _env_int("ZHISHAO_FALL_CLEAR_FRAMES", 5)
FALL_COOLDOWN_SECONDS = _env_int("ZHISHAO_FALL_COOLDOWN_SECONDS", 18)
CAMERA_REOPEN_SECONDS = _env_float("ZHISHAO_CAMERA_REOPEN_SECONDS", 2.0)


# =========================================================================
# 历史兼容配置：当前人物锁定默认不再使用人脸识别
# =========================================================================
FACE_MODEL_DIR = os.path.join(BASE_DIR, "models")
FACE_DETECT_MODEL = os.path.join(FACE_MODEL_DIR, "face_detection_yunet_2023mar.onnx")
FACE_RECOGNIZE_MODEL = os.path.join(FACE_MODEL_DIR, "face_recognition_sface_2021dec.onnx")
FACE_PROFILE_DIR = os.path.join(BASE_DIR, "profiles")
FACE_PROFILE_PATH = os.path.join(FACE_PROFILE_DIR, "person_profiles.json")

FACE_MATCH_THRESHOLD = _env_float("ZHISHAO_FACE_MATCH_THRESHOLD", 0.55)
FACE_RECOGNITION_INTERVAL = _env_int("ZHISHAO_FACE_RECOGNITION_INTERVAL", 5)
FACE_ENROLL_MIN_SAMPLES = _env_int("ZHISHAO_FACE_ENROLL_MIN_SAMPLES", 10)
FACE_ENROLL_MAX_SAMPLES = _env_int("ZHISHAO_FACE_ENROLL_MAX_SAMPLES", 20)
FACE_TRACK_HOLD_SECONDS = _env_float("ZHISHAO_FACE_TRACK_HOLD_SECONDS", 5.0)
