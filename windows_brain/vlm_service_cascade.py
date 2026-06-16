import base64
import json
import os

import requests
from flask import Flask, jsonify, request


app = Flask(__name__)

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_URL = os.environ.get(
    "DASHSCOPE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
)
QWEN_VL_MODEL = os.environ.get("QWEN_VL_MODEL", "qwen-vl-max")


def call_qwen_vl(prompt, image_b64=None, temperature=0.2):
    if not DASHSCOPE_API_KEY:
        print("DASHSCOPE_API_KEY is not configured.")
        return None
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    content_list = []
    if image_b64:
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
    content_list.append({"type": "text", "text": prompt})
    payload = {
        "model": QWEN_VL_MODEL,
        "messages": [{"role": "user", "content": content_list}],
        "temperature": temperature,
    }
    try:
        res = requests.post(DASHSCOPE_URL, headers=headers, json=payload, timeout=45)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"].strip()
        print(f"DashScope error: {res.status_code} {res.text[:300]}")
    except Exception as e:
        print(f"DashScope request failed: {e}")
    return None


def clean_json_response(content):
    if not content:
        return ""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").replace("json", "", 1).strip()
    return content


def parse_json_or_block(raw_content, fallback_reason):
    content = clean_json_response(raw_content)
    try:
        return json.loads(content)
    except Exception:
        return {
            "safe_to_show": False,
            "risk_level": "uncertain",
            "reason": fallback_reason,
            "confidence": 0.0,
            "evidence": [],
            "block_type": "parse_error",
            "raw": raw_content or "",
        }


def privacy_unavailable(reason, status_code=200):
    return jsonify({
        "safe_to_show": False,
        "risk_level": "unknown",
        "reason": reason,
        "confidence": 0.0,
        "evidence": [],
        "block_type": "service_unavailable",
    }), status_code


def normalize_privacy_result(result):
    safe = bool(result.get("safe_to_show", False))
    risk_level = str(result.get("risk_level") or ("safe" if safe else "uncertain")).strip()
    reason = str(result.get("reason") or "模型未给出明确原因。").strip()
    block_type = str(result.get("block_type") or "").strip()
    if not block_type:
        if safe:
            block_type = "none"
        elif risk_level == "privacy_risk":
            block_type = "privacy_risk"
        elif risk_level == "uncertain":
            block_type = "uncertain"
        else:
            block_type = "model_rejected"
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    evidence = result.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []
    evidence = [str(item).strip() for item in evidence if str(item).strip()][:3]
    return {
        "safe_to_show": safe,
        "risk_level": risk_level,
        "reason": reason,
        "confidence": confidence,
        "evidence": evidence,
        "block_type": block_type,
    }


@app.route("/ask", methods=["POST"])
def ask():
    try:
        data = request.json or {}
        question = data.get("question", "")
        prompt = data.get("prompt", "")
        image_base64 = data.get("image", "")
        if not prompt:
            return jsonify({"answer": "未收到问题内容。", "need_image": False}), 400

        print(f"\n[ZhiShao Brain] Ask: {question}")
        raw_content = call_qwen_vl(prompt, image_base64)
        content = clean_json_response(raw_content)
        try:
            result_data = json.loads(content)
            return jsonify({
                "answer": result_data.get("answer", "我暂时没有理解您的意思。"),
                "need_image": bool(result_data.get("need_image", False)),
            })
        except Exception:
            fallback_answer = (raw_content or "").replace("```json", "").replace("```", "").strip()
            return jsonify({"answer": fallback_answer or "大脑暂时没有返回有效回答，请稍后再试。", "need_image": False})
    except Exception as e:
        return jsonify({"answer": f"云端失败: {e}", "need_image": False}), 500


@app.route("/privacy_check", methods=["POST"])
def privacy_check():
    """Check whether a raw frame is appropriate for short family viewing."""
    try:
        data = request.json or {}
        image_base64 = data.get("image", "")
        if not image_base64:
            return jsonify({
                "safe_to_show": False,
                "risk_level": "blocked",
                "reason": "没有收到可复核画面。",
                "confidence": 1.0,
                "evidence": ["请求中没有 image 字段"],
                "block_type": "no_image",
            }), 400

        prompt = """你是“智哨看护系统”的隐私复核员。你的任务不是判断是否有人，而是判断当前真实摄像头画面能否临时开放给家属查看 3 分钟，用于确认老人安全。

请严格按下面规则判断：
1. 只有在明确看到以下情况时才判定 privacy_risk 并拒绝：浴室/洗澡、如厕、换衣、裸露或半裸、身体隐私部位明显可见、床上高度私密状态、镜子/屏幕反射导致隐私暴露。
2. 如果是普通客厅、办公室、走廊、厨房、正常卧室环境，人物正常穿着，只是在坐、站、走、弯腰、休息或轻微活动，应判定 safe。
3. 不要因为“卧室”两个字就拒绝；只有床上高度私密、衣着不当或身体隐私暴露才拒绝。
4. 不要因为画面里有人脸、普通衣服、桌椅、电脑、日常杂物就拒绝。
5. 如果画面模糊、遮挡、光线差到无法判断是否有隐私暴露，判定 uncertain。
6. 只返回严格 JSON，不要输出 Markdown，不要解释 JSON 之外的内容。

返回格式：
{
  "safe_to_show": true 或 false,
  "risk_level": "safe/privacy_risk/uncertain",
  "reason": "用一句中文说明通过或拒绝的具体原因",
  "confidence": 0.0 到 1.0,
  "evidence": ["最多列出3个画面依据"],
  "block_type": "none/privacy_risk/uncertain"
}"""
        print("\n[ZhiShao Brain] Privacy check requested.")
        raw_content = call_qwen_vl(prompt, image_base64, temperature=0.0)
        if not raw_content:
            return privacy_unavailable("隐私复核服务暂时不可用，已按保护策略拒绝开启真实画面。")
        result = parse_json_or_block(raw_content, "隐私复核结果解析失败，已按保护策略拒绝展示。")
        result = normalize_privacy_result(result)
        print(
            f"[Privacy check] safe={result['safe_to_show']} risk={result['risk_level']} "
            f"block={result['block_type']} confidence={result['confidence']:.2f} reason={result['reason']}"
        )
        return jsonify(result)
    except Exception as e:
        return privacy_unavailable(f"隐私复核服务异常：{e}", 500)


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        if "image" not in request.files:
            return jsonify({"location": "未知区域", "risk_level": "normal", "description": "无画面"}), 400
        img_bytes = request.files["image"].read()
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        prompt = """【智哨系统：现场高危行为复核】
这是边缘设备抓拍的疑似摔倒证据。请识别场景和姿态：
1. 如果发生滑倒、瘫坐、猛烈摔伤、身体失控平躺，判定 critical。
2. 如果是正常弯腰、坐在椅子/沙发/床上，判定 normal。
必须只返回 JSON：
{
  "location": "场景名",
  "risk_level": "normal/critical",
  "description": "现场研判描述"
}"""
        print("\n[ZhiShao Brain] Fall validation requested.")
        raw_content = call_qwen_vl(prompt, img_base64)
        content = clean_json_response(raw_content)
        try:
            return jsonify(json.loads(content))
        except Exception:
            return jsonify({"location": "未知区域", "risk_level": "critical", "description": raw_content or "云端无有效描述"})
    except Exception as e:
        return jsonify({"location": "未知", "risk_level": "critical", "description": f"复核异常: {e}"}), 500


@app.route("/summarize", methods=["POST"])
def summarize():
    data = request.json or {}
    log_content = data.get("log_content", "无活动记录")
    prompt = f"""作为家庭健康顾问，请分析老人今日活动日志：
{log_content}
请用温和、尊重隐私的语气，给出简短关怀建议。"""
    print("\n[ZhiShao Brain] Daily summary requested.")
    summary = call_qwen_vl(prompt)
    return jsonify({"summary": summary or "大脑暂时繁忙，建议今晚简单问候父母是否安好。"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "service": "ZhiShao Brain",
        "model": QWEN_VL_MODEL,
        "dashscope_configured": bool(DASHSCOPE_API_KEY),
        "endpoints": ["/ask", "/analyze", "/summarize", "/privacy_check"],
    })


if __name__ == "__main__":
    print("==============================================================")
    print("[ZhiShao Brain] Qwen-VL service starting on 0.0.0.0:9000")
    print("Endpoints: /ask /analyze /summarize /privacy_check /health")
    print("==============================================================")
    app.run(host="0.0.0.0", port=9000, threaded=True)
