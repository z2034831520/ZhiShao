# Windows VLM 服务接口契约

本文记录 `windows_brain/vlm_service_cascade.py` 当前提供给 RDK 主程序调用的 HTTP 接口。该服务默认运行在 Windows PC 的 `0.0.0.0:9000`，RDK 通过 `brain/brain_client.py` 调用。

## 通用约定

- 服务类型：Flask HTTP 服务。
- 默认端口：`9000`。
- 上游模型：DashScope / Qwen-VL。
- 图片字段使用 base64 编码时，当前约定为 JPEG base64 字符串。
- 失败时优先返回结构化 JSON，RDK 端再按保护策略兜底。

## POST /ask

用途：处理用户自然语言问答，可按需要携带当前画面。

请求 Content-Type：

```text
application/json
```

请求字段：

```json
{
  "question": "用户原始问题",
  "prompt": "RDK 端组装后的完整提示词",
  "image": "可选，JPEG base64 字符串"
}
```

成功返回字段：

```json
{
  "answer": "给用户的回答文本",
  "need_image": false
}
```

失败兜底：

- 如果 `prompt` 为空，返回 HTTP 400，并返回 `answer` 与 `need_image`。
- 如果模型返回无法解析为 JSON 的文本，服务会把原始文本清理后作为 `answer` 返回。
- 如果服务内部异常，返回 HTTP 500，并返回 `answer` 与 `need_image=false`。
- RDK 端请求失败时，天气类问题会尝试本地天气兜底；其他问题返回 `None`，由上层决定如何回复。

## POST /analyze

用途：对 RDK 侧疑似高风险事件图片进行 VLM 复核，例如摔倒、滑倒或异常姿态。

请求 Content-Type：

```text
multipart/form-data
```

请求字段：

```text
image  JPEG 图片文件
```

成功返回字段：

```json
{
  "location": "场景或区域描述",
  "risk_level": "normal 或 critical",
  "description": "现场研判描述"
}
```

失败兜底：

- 如果缺少 `image` 文件，返回 HTTP 400，并返回默认 `location`、`risk_level=normal`、`description`。
- 如果模型返回无法解析为 JSON，服务返回 `risk_level=critical` 和模型原始描述，倾向保护性处理。
- 如果服务内部异常，返回 HTTP 500，并返回 `risk_level=critical`。
- RDK 端请求失败时返回 `None`，由摔倒检测或告警流程决定后续动作。

## POST /summarize

用途：根据 RDK 活动日志生成简短日报或关怀总结。

请求 Content-Type：

```text
application/json
```

请求字段：

```json
{
  "log_content": "当天活动日志文本"
}
```

成功返回字段：

```json
{
  "summary": "日报总结文本"
}
```

失败兜底：

- 如果 `log_content` 缺失，服务使用默认的空活动记录文本。
- 如果 DashScope / Qwen-VL 暂无返回，服务返回默认提示文本。
- RDK 端请求失败时返回空字符串。

## POST /privacy_check

用途：判断当前真实摄像头画面是否适合短时间开放给家属查看。

请求 Content-Type：

```text
application/json
```

请求字段：

```json
{
  "image": "JPEG base64 字符串"
}
```

成功返回字段：

```json
{
  "safe_to_show": false,
  "risk_level": "safe/privacy_risk/uncertain/unknown/blocked",
  "reason": "通过或拒绝的具体原因",
  "confidence": 0.0,
  "evidence": ["最多若干条画面依据"],
  "block_type": "none/privacy_risk/uncertain/no_image/service_unavailable/parse_error"
}
```

失败兜底：

- 如果缺少 `image`，返回 HTTP 400，并返回 `safe_to_show=false`、`block_type=no_image`。
- 如果模型不可用，返回 `safe_to_show=false`、`block_type=service_unavailable`。
- 如果模型 JSON 解析失败，返回 `safe_to_show=false`、`block_type=parse_error`。
- RDK 端如果连接失败、返回字段缺失或处理异常，按保护策略拒绝开放真实画面。

## GET /health

用途：检查 Windows VLM 服务是否启动，以及 DashScope API Key 是否已配置。

请求字段：无。

成功返回字段：

```json
{
  "ok": true,
  "service": "ZhiShao Brain",
  "model": "当前模型名",
  "dashscope_configured": true,
  "endpoints": ["/ask", "/analyze", "/summarize", "/privacy_check"]
}
```

失败兜底：

- 如果服务未启动，RDK 或 Windows 侧健康检查会连接失败。
- 如果 `dashscope_configured=false`，表示服务进程可用，但模型调用配置不完整。
