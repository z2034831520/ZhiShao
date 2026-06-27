# RDK 导入与 Windows VLM 服务分析

更新时间：2026-06-27

## 当前导入状态

### Windows 侧

```text
_import_windows/vlm_service_cascade.py
```

来源：

```text
F:\codex_project\ZhiShao\vlm_service_cascade.py
```

作用判断：这是一个 Flask 服务，默认监听 `0.0.0.0:9000`，提供：

- `/ask`
- `/analyze`
- `/summarize`
- `/privacy_check`
- `/health`

它调用 DashScope / Qwen-VL，依赖环境变量：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_URL`
- `QWEN_VL_MODEL`

### RDK 侧

```text
_import_rdk/ZhiShao_V2/
```

主要结构：

```text
main.py
settings.py
brain/brain_client.py
core/
notify/
services/
tests/
.env.example
```

作用判断：这是 RDK X5 上运行的主项目，负责摄像头、云台、姿态/摔倒检测、Web 看护页面、飞书事件和日报服务。

## 两端关系判断

RDK 项目不是要直接替换 Windows 文件；它通过 `brain/brain_client.py` 调用 Windows 侧的“大脑/VLM 服务”。

RDK 配置中相关字段位于：

```text
settings.py
.env.example
```

RDK 期望 Windows 侧服务地址类似：

```text
http://<Windows_PC_IP>:9000/ask
http://<Windows_PC_IP>:9000/analyze
http://<Windows_PC_IP>:9000/summarize
http://<Windows_PC_IP>:9000/privacy_check
```

Windows 导入的 `vlm_service_cascade.py` 正好提供这些接口，因此它应作为“Windows 脑服务”保留，而不是塞进 RDK 主程序内部。

## 当前统一项目结构

当前已经整理成：

```text
rdk_app/             # 来自 _import_rdk/ZhiShao_V2 的 RDK 主程序
windows_brain/       # 来自 _import_windows/vlm_service_cascade.py 的 Windows VLM 服务
docs/
work/
outputs/
```

其中：

```text
rdk_app/main.py
rdk_app/settings.py
rdk_app/brain/
rdk_app/core/
rdk_app/services/
rdk_app/notify/
rdk_app/tests/
windows_brain/vlm_service_cascade.py
```

## 不建议纳入 Git 的内容

以下文件/目录是运行态、本地配置、敏感配置或大文件，不建议提交：

```text
.env
__pycache__/
logs/
*.db
*.bin
*.png
*.gif
.cursor/
```

说明：`yolov8n-pose.bin` 可能是 RDK 模型文件，部署时可能需要，但不建议直接纳入普通 Git。后续可以改为文档记录下载/复制方式，或使用 Git LFS/网盘/NAS 管理。

## 目前发现的注意点

1. `rdk_app/settings.py` 的已确认乱码文本已修复；`_import_rdk/ZhiShao_V2/settings.py` 继续作为原始导入基线保留，不直接覆盖。
2. RDK `.env.example` 已按当前实现统一为 Windows `windows_brain/vlm_service_cascade.py` 调用 DashScope/Qwen-VL；如果后续要支持本地 Ollama，需要再做成可配置后端。
3. RDK 主程序依赖 Linux/RDK 环境、摄像头、串口云台和 OpenCV，Windows 侧不适合完整运行主程序，只适合做静态检查和 Windows 脑服务开发。
4. 当前 Git 工作区只保留 `.env.example`，没有提交 `.env`、模型文件、日志或图片等运行产物。

## 下一步建议

1. 继续把 `_import_rdk/` 和 `_import_windows/` 作为导入基线保留。
2. 后续功能修改优先在 `rdk_app/` 与 `windows_brain/` 中完成。
3. 启动说明已初步记录：
   - Windows 启动 `windows_brain/vlm_service_cascade.py`
   - RDK 设置 `.env` 指向 Windows IP
   - RDK 启动 `rdk_app/main.py`
4. 在 RDK 上验证后，再考虑低风险优化。
