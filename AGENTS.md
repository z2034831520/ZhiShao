# ZhiShao RDK X5 Project Rules

## 环境说明
- Windows PC 是 Codex 主开发环境。
- RDK X5 是 Linux 运行、部署和硬件验证环境。
- RDK 正式项目路径：`/home/sunrise/ZhiShao_V2`
- 当前 Windows Codex 工作区：`E:\GitHub\ZhiShao`
- Windows 原始文件来源：`F:\codex_project\ZhiShao\vlm_service_cascade.py`

## 当前状态
- Windows 侧文件已导入 `_import_windows/`。
- RDK 侧项目文件已导入 `_import_rdk/ZhiShao_V2/`。
- `rdk_app/` 是 RDK 主程序开发区，来自 `_import_rdk/ZhiShao_V2/`。
- `windows_brain/` 是 Windows VLM 服务开发区，来自 `_import_windows/vlm_service_cascade.py`。
- 如需后续重新从 RDK 拉取 `/home/sunrise/ZhiShao_V2`，应先拉到 `work/` 下的新临时目录对比，不直接覆盖 `_import_rdk/` 或开发区。

## 工作规则
- 修改前必须先阅读 README、目录结构、关键 Python 文件、启动脚本和配置文件。
- 不直接覆盖 RDK 或 Windows 原始项目目录。
- 先在当前 Codex 工作区完成合并、分析、修改和 Git 提交。
- 优先做最小改动，不做无关重构。
- 不删除用户已有文件，除非用户明确要求。
- 不提交缓存、日志、模型文件、临时文件和构建产物。
- 修改部署脚本、服务启动方式、模型路径、设备路径、端口号前必须先说明影响。
- 需要在 RDK X5 上运行命令时，先给出命令和风险，再执行或等待用户确认。

## 同步规则
- Codex 修改完成后，先用 Git 查看 diff。
- 确认后再同步到 RDK X5 测试目录。
- RDK X5 上验证运行结果后，再决定是否替换正式目录。
