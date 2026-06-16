# Windows Brain

这是 Windows VLM 服务开发区，来源于：

```text
_import_windows/vlm_service_cascade.py
```

该服务默认提供：

```text
/ask
/analyze
/summarize
/privacy_check
/health
```

接口契约见：

```text
docs/API_CONTRACT.md
```

## 启动前配置

需要通过环境变量配置 DashScope / Qwen-VL：

```text
DASHSCOPE_API_KEY
DASHSCOPE_URL
QWEN_VL_MODEL
```

不要把真实 API Key 写入代码或提交到 Git。

## 启动

```powershell
python windows_brain\vlm_service_cascade.py
```

默认监听：

```text
0.0.0.0:9000
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:9000/health
```
