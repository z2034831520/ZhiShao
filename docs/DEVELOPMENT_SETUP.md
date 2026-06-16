# 开发区与验证说明

本文说明当前 Codex 工作区中后续功能开发应使用的目录和验证方式。

## 开发目录

```text
rdk_app/          RDK X5 主程序开发区
windows_brain/    Windows VLM 服务开发区
```

`_import_rdk/` 和 `_import_windows/` 继续作为原始导入基线保留。后续新增功能、修复问题和整理代码时，优先修改 `rdk_app/` 与 `windows_brain/`。

## RDK 主程序开发区

`rdk_app/` 来自 `_import_rdk/ZhiShao_V2/`，但不包含以下运行产物或本地敏感文件：

```text
.env
logs/
__pycache__/
*.bin
*.db
*.png
*.gif
```

如果需要在 RDK 上运行，需要在 RDK 测试目录补齐：

- `.env`：来自测试环境，不提交到 Git。
- `yolov8n-pose.bin`：模型文件，不作为普通 Git 文件提交。
- RDK 专用运行库，例如 `hobot_dnn`。
- 摄像头、串口云台和飞书配置。

## Windows VLM 服务开发区

`windows_brain/` 来自 `_import_windows/vlm_service_cascade.py`，用于开发和验证 Windows 侧 Flask VLM 服务。

运行前需要配置：

```text
DASHSCOPE_API_KEY
DASHSCOPE_URL
QWEN_VL_MODEL
```

其中 `DASHSCOPE_API_KEY` 是敏感配置，不要写入代码或提交到 Git。

## 本地只读语法检查

在 Windows Codex 工作区可运行：

```powershell
python -c "import ast, pathlib, sys, tokenize; paths=list(pathlib.Path('rdk_app').rglob('*.py'))+list(pathlib.Path('windows_brain').rglob('*.py')); failed=[]; 
for p in paths:
    try:
        with tokenize.open(str(p)) as f:
            ast.parse(f.read(), filename=str(p))
    except Exception as e:
        failed.append((str(p), type(e).__name__, str(e)))
print(f'parsed={len(paths)-len(failed)} failed={len(failed)}')
for item in failed:
    print('FAIL', item[0], item[1], item[2])
sys.exit(1 if failed else 0)"
```

## RDK 测试目录同步

后续同步到 RDK 时，默认目标仍是测试目录：

```text
/home/sunrise/ZhiShao_V2_codex_test
```

不要直接覆盖正式目录：

```text
/home/sunrise/ZhiShao_V2
```

同步和替换正式目录的详细流程见：

```text
docs/RDK_SYNC_TODO.md
```
