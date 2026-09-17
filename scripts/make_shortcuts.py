"""在 Windows 桌面创建本项目的启动 / 停止快捷方式（.lnk）。

用法（在项目根目录或任意位置均可）：

    pip install pywin32
    python scripts/make_shortcuts.py

换机器 / 换了项目路径时重跑一次即可：项目根目录由本脚本位置推断
（scripts/ 的上一级），所以克隆到别处也能直接用。

生成结果：桌面上的「启动政明白.lnk」→ docker-up.bat
                        「停止政明白.lnk」→ docker-down.bat
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import win32com.client
except ImportError:  # pragma: no cover - 环境问题，直接给出可执行的修复命令
    sys.exit("缺少 pywin32，请先执行：pip install pywin32")

ROOT = Path(__file__).resolve().parents[1]

SHORTCUTS = [
    {
        "name": "启动政明白.lnk",
        "target": ROOT / "docker-up.bat",
        "desc": "GovRAG 一键启动（Docker 全栈：前端 8080 / 后端 8000）",
    },
    {
        "name": "打开政明白.lnk",
        "target": ROOT / "open-page.bat",
        "desc": "GovRAG 打开网页（先探测服务，在跑才打开 http://127.0.0.1:8080）",
    },
    {
        "name": "停止政明白.lnk",
        "target": ROOT / "docker-down.bat",
        "desc": "GovRAG 一键停止（容器删除，数据卷保留）",
    },
]


def main() -> int:
    if os.name != "nt":
        sys.exit("该脚本只适用于 Windows。")

    shell = win32com.client.Dispatch("WScript.Shell")
    # 用 Shell 的 Desktop 而不是 %USERPROFILE%\Desktop：
    # 桌面被 OneDrive 重定向时，前者才是真实路径。
    desktop = shell.SpecialFolders("Desktop")
    print(f"项目根目录 : {ROOT}")
    print(f"桌面目录   : {desktop}")

    for item in SHORTCUTS:
        target = item["target"]
        if not target.is_file():
            print(f"[ERROR] 目标脚本不存在：{target}")
            return 1

        path = os.path.join(desktop, item["name"])
        lnk = shell.CreateShortcut(path)
        lnk.TargetPath = str(target)
        lnk.WorkingDirectory = str(ROOT)
        lnk.Description = item["desc"]
        lnk.WindowStyle = 1  # 普通窗口：双击后能看到启动日志与健康检查结果
        lnk.Save()

        # 回读校验，确保写出的 .lnk 真能解析到目标
        check = shell.CreateShortcut(path)
        ok = os.path.normcase(check.TargetPath) == os.path.normcase(str(target))
        print(f"[{'OK' if ok else 'FAIL'}] {path}")
        print(f"        -> {check.TargetPath}  (cwd={check.WorkingDirectory})")
        if not ok:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
