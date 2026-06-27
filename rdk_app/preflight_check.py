import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import settings


BASE_DIR = Path(settings.BASE_DIR)


class CheckResult:
    def __init__(self, name, status, detail):
        self.name = name
        self.status = status
        self.detail = detail

    def to_dict(self):
        return {"name": self.name, "status": self.status, "detail": self.detail}


def ok(name, detail):
    return CheckResult(name, "ok", detail)


def warn(name, detail):
    return CheckResult(name, "warn", detail)


def fail(name, detail):
    return CheckResult(name, "fail", detail)


def import_check(module_name, required=True):
    try:
        importlib.import_module(module_name)
        return ok(f"python module: {module_name}", "import succeeded")
    except Exception as exc:
        message = f"import failed: {type(exc).__name__}: {exc}"
        if required:
            return fail(f"python module: {module_name}", message)
        return warn(f"python module: {module_name}", message)


def check_env_file():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        return ok(".env file", str(env_path))
    return fail(".env file", f"missing: {env_path}")


def check_model_file():
    model_path = BASE_DIR / "yolov8n-pose.bin"
    if not model_path.exists():
        return fail("BPU pose model", f"missing: {model_path}")
    size = model_path.stat().st_size
    if size <= 0:
        return fail("BPU pose model", f"empty file: {model_path}")
    return ok("BPU pose model", f"{model_path} ({size} bytes)")


def check_brain_config():
    urls = {
        "ask": settings.BRAIN_URL_ASK,
        "analyze": settings.BRAIN_URL_ANALYZE,
        "summarize": settings.BRAIN_URL_SUMMARIZE,
        "privacy_check": settings.BRAIN_URL_PRIVACY_CHECK,
    }
    invalid = []
    for key, value in urls.items():
        parsed = urlparse(value or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            invalid.append(f"{key}={value!r}")
    if invalid:
        return fail("Windows VLM URLs", "invalid URLs: " + ", ".join(invalid))
    return ok("Windows VLM URLs", ", ".join(f"{k}={v}" for k, v in urls.items()))


def check_brain_health(timeout):
    try:
        requests = importlib.import_module("requests")
    except Exception as exc:
        return fail("Windows VLM /health", f"requests import failed: {exc}")
    url = settings.VLM_BASE_URL.rstrip("/") + "/health"
    try:
        response = requests.get(url, timeout=timeout)
    except Exception as exc:
        return fail("Windows VLM /health", f"{url} unreachable: {type(exc).__name__}: {exc}")
    if response.status_code != 200:
        return fail("Windows VLM /health", f"{url} returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        return fail("Windows VLM /health", f"{url} returned non-JSON response: {exc}")
    if not payload.get("ok"):
        return fail("Windows VLM /health", f"{url} returned ok=false: {payload}")
    if payload.get("dashscope_configured") is False:
        return warn("Windows VLM /health", f"{url} is reachable, but DashScope API key is not configured")
    return ok("Windows VLM /health", f"{url} ok; model={payload.get('model', 'unknown')}")


def check_camera():
    try:
        cv2 = importlib.import_module("cv2")
    except Exception as exc:
        return fail("camera", f"opencv import failed: {exc}")
    cap = None
    try:
        cap = cv2.VideoCapture(settings.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.CAMERA_HEIGHT)
        if not cap.isOpened():
            return fail("camera", f"cannot open camera index {settings.CAMERA_INDEX}")
        ret, frame = cap.read()
        if not ret or frame is None:
            return fail("camera", f"camera index {settings.CAMERA_INDEX} opened but frame read failed")
        return ok("camera", f"index={settings.CAMERA_INDEX}, frame={frame.shape[1]}x{frame.shape[0]}")
    except Exception as exc:
        return fail("camera", f"{type(exc).__name__}: {exc}")
    finally:
        if cap is not None:
            cap.release()


def check_ptz_port():
    port = settings.PTZ_PORT
    if os.name == "nt" and port.startswith("/dev/"):
        return warn("PTZ port", f"{port} is a Linux device path; run this check on RDK X5")
    if not os.path.exists(port):
        return fail("PTZ port", f"missing: {port}")
    return ok("PTZ port", port)


def check_feishu_config():
    missing = [
        name
        for name in ("FEISHU_WEBHOOK", "FEISHU_APP_ID", "FEISHU_APP_SECRET")
        if not os.environ.get(name)
    ]
    if missing:
        return warn("Feishu config", "missing: " + ", ".join(missing))
    return ok("Feishu config", "webhook, app id, and app secret are configured")


def collect_results(args):
    results = [
        check_env_file(),
        check_model_file(),
        import_check("cv2"),
        import_check("numpy"),
        import_check("requests"),
        import_check("serial"),
        import_check("lark_oapi"),
        import_check("hobot_dnn"),
        check_brain_config(),
        check_feishu_config(),
    ]
    if args.skip_network:
        results.append(warn("Windows VLM /health", "skipped by --skip-network"))
    else:
        results.append(check_brain_health(args.timeout))
    if args.skip_ptz:
        results.append(warn("PTZ port", "skipped by --skip-ptz"))
    else:
        results.append(check_ptz_port())
    if args.skip_camera:
        results.append(warn("camera", "skipped by --skip-camera"))
    else:
        results.append(check_camera())
    return results


def print_text(results):
    symbols = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    for result in results:
        print(f"[{symbols[result.status]}] {result.name}: {result.detail}")
    totals = {status: sum(1 for item in results if item.status == status) for status in ("ok", "warn", "fail")}
    print(f"\nSummary: ok={totals['ok']} warn={totals['warn']} fail={totals['fail']}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Run ZhiShao RDK X5 deployment preflight checks.")
    parser.add_argument("--skip-camera", action="store_true", help="Skip opening the configured camera.")
    parser.add_argument("--skip-ptz", action="store_true", help="Skip checking the configured PTZ serial device path.")
    parser.add_argument("--skip-network", action="store_true", help="Skip Windows VLM /health request.")
    parser.add_argument("--timeout", type=float, default=3.0, help="Network timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--no-exit-code", action="store_true", help="Always exit 0 after printing results.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    results = collect_results(args)
    if args.json:
        print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))
    else:
        print_text(results)
    has_failure = any(item.status == "fail" for item in results)
    return 0 if args.no_exit_code or not has_failure else 1


if __name__ == "__main__":
    sys.exit(main())
