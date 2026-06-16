# RDK App

这是 RDK X5 主程序开发区，来源于：

```text
_import_rdk/ZhiShao_V2/
```

后续 RDK 侧功能开发优先在本目录完成。原始导入目录 `_import_rdk/` 保留为基线，不直接覆盖。

## 主要入口

```text
main.py
```

主要模块：

```text
settings.py             配置加载
brain/brain_client.py   Windows VLM 服务客户端
services/               Web、飞书、视觉、摔倒检测、云台、日报、状态和存储服务
core/                   YOLO pose 解码、云台底层控制和工具
notify/                 飞书机器人封装
tests/                  单元测试
```

## 未纳入开发区的运行文件

以下文件需要在 RDK 测试环境中按需补齐，不提交到 Git：

```text
.env
logs/
__pycache__/
yolov8n-pose.bin
*.db
*.png
*.gif
```

## 验证建议

Windows Codex 工作区只适合做静态检查和非硬件单测。摄像头、串口云台、BPU 模型和飞书长连接需要在 RDK X5 上验证。

```bash
python3 -m py_compile main.py settings.py brain/brain_client.py
python3 -m unittest discover -s tests
```
