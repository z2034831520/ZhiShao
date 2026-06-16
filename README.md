# ZhiShao RDK X5 Project

这是为 ZhiShao / RDK X5 项目准备的 Codex 工作区。当前工作区用于归档、分析、低风险整理和后续同步验证，不直接覆盖 RDK 或 Windows 原始项目目录。

## 当前项目组成

当前项目由两部分组成：

```text
_import_rdk/ZhiShao_V2/              RDK X5 主程序导入区
_import_windows/vlm_service_cascade.py  Windows VLM 服务导入文件
rdk_app/                             RDK 主程序开发区
windows_brain/                       Windows VLM 服务开发区
```

### RDK 主程序

原始导入位置：

```text
_import_rdk/ZhiShao_V2
```

开发位置：

```text
rdk_app/
```

作用：

- 在 RDK X5 上运行主程序。
- 负责摄像头画面采集、姿态检测、摔倒检测、云台控制、Web 看护页、飞书交互和日报服务。
- 通过 `brain/brain_client.py` 调用 Windows 侧 VLM 服务。

### Windows VLM 服务

原始导入位置：

```text
_import_windows/vlm_service_cascade.py
```

开发位置：

```text
windows_brain/vlm_service_cascade.py
```

来源：

```text
F:\codex_project\ZhiShao\vlm_service_cascade.py
```

作用：

- 在 Windows PC 上运行 Flask 服务。
- 默认提供 `/ask`、`/analyze`、`/summarize`、`/privacy_check`、`/health`。
- 调用 DashScope / Qwen-VL，为 RDK 主程序提供大模型分析能力。

## 目录说明

```text
_import_windows/  Windows 侧已有文件导入区，保留原始导入文件
_import_rdk/      RDK X5 项目导入区，保留从开发板拉取的项目基线
rdk_app/          RDK 主程序开发区，后续功能修改优先在这里完成
windows_brain/    Windows VLM 服务开发区，后续脑服务修改优先在这里完成
docs/             项目说明、架构记录、接口契约、同步流程
scripts/          后续放同步、部署、验证脚本
templates/        可复用模板
work/             临时分析和草稿
outputs/          用户交付物
```

## 两端关系

RDK 主程序不是 Windows VLM 服务的替代版本。两者是协作关系：

```text
RDK 摄像头/姿态检测/飞书/Web 看护页
  -> _import_rdk/ZhiShao_V2/brain/brain_client.py
  -> Windows PC 9000 端口 VLM 服务
  -> DashScope / Qwen-VL
  -> 分析结果返回 RDK
```

更详细的数据流见：

```text
docs/ARCHITECTURE.md
```

Windows VLM 服务接口契约见：

```text
docs/API_CONTRACT.md
```

## 推荐工作流程

1. 在当前 Codex 工作区完成分析、文档整理和低风险优化。
2. 不移动、不覆盖 `_import_rdk/` 和 `_import_windows/` 导入目录。
3. 功能开发优先修改 `rdk_app/` 与 `windows_brain/`。
4. 修改完成后先查看 Git diff。
5. 同步到 RDK 测试目录 `/home/sunrise/ZhiShao_V2_codex_test`。
6. 在 RDK 测试目录验证通过后，再决定是否替换正式目录 `/home/sunrise/ZhiShao_V2`。

开发区说明见：

```text
docs/DEVELOPMENT_SETUP.md
```

## 注意事项

- 不提交 `.env`、日志、缓存、数据库、模型文件和生成图片。
- 修改部署脚本、服务启动方式、模型路径、设备路径、端口号前需要先说明影响。
- RDK 硬件相关验证必须在 RDK X5 上完成。
