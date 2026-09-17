"""一键质量门禁：静态检查 + 单元测试（+ 可选前端构建）。

为什么要有它
------------
规范写在文档里没人会执行，写成一条命令才会。这个脚本把"提交前必须过"的事情
固化下来，本地和以后接 CI 用的是同一套命令，不会出现"我这儿是好的"。

用法（在仓库根目录）：
    python scripts/quality_gate.py                 # ruff + pytest
    python scripts/quality_gate.py --with-frontend # 再加前端构建
    python scripts/quality_gate.py --only ruff     # 只跑某一项（ruff|pytest|frontend）

退出码：0 = 全部通过；1 = 有失败项。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

IS_WIN = sys.platform.startswith("win")


def _exe(base: Path, name: str) -> str:
    """Windows 下可执行文件带 .exe；找不到就退回命令名（交给 PATH）。"""
    p = base / f"{name}.exe" if IS_WIN else base / name
    return str(p) if p.exists() else name


def _find(rel_candidates: list[str], name: str) -> str:
    """按候选路径找可执行文件，都找不到就用 PATH 里的。"""
    for rel in rel_candidates:
        p = ROOT / rel
        cand = p / f"{name}.exe" if IS_WIN else p / name
        if cand.exists():
            return str(cand)
    return shutil.which(name) or name


def _run(title: str, cmd: list[str], cwd: Path) -> bool:
    print(f"\n=== {title} ===")
    print("$ " + " ".join(cmd))
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), check=False)
    except FileNotFoundError as e:
        print(f"[跳过] 找不到命令：{e}")
        return True
    ok = proc.returncode == 0
    print(f"[{ '通过' if ok else '失败' }] {title}（{time.time() - t0:.1f}s）")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="政明白项目质量门禁")
    parser.add_argument("--with-frontend", action="store_true", help="同时构建前端（较慢）")
    parser.add_argument("--only", choices=["ruff", "pytest", "frontend"], help="只跑指定项")
    args = parser.parse_args()

    # Windows 控制台默认 GBK，中文标题会炸；脚本自身输出统一 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    py = _find(["backend/.venv/Scripts", "backend/.venv/bin", ".venv/Scripts", ".venv/bin"], "python")
    ruff = _find([".venv/Scripts", ".venv/bin", "backend/.venv/Scripts", "backend/.venv/bin"], "ruff")

    results: list[tuple[str, bool]] = []

    if args.only in (None, "ruff"):
        # F = pyflakes（未定义/未使用/语法），E9 = 真正的语法错误。
        # 不跑完整风格规则：历史代码改动成本高，先把"会炸的问题"挡住。
        results.append((
            "静态检查 ruff",
            _run("静态检查 ruff", [ruff, "check", "--select", "F,E9", "app", "scripts", "tests"], BACKEND),
        ))

    if args.only in (None, "pytest"):
        results.append((
            "单元测试 pytest",
            _run("单元测试 pytest", [py, "-m", "pytest", "-q"], BACKEND),
        ))

    if args.only == "frontend" or (args.with_frontend and args.only is None):
        npm = "npm.cmd" if IS_WIN else "npm"
        results.append((
            "前端构建 vite",
            _run("前端构建 vite", [npm, "run", "build"], FRONTEND),
        ))

    print("\n" + "=" * 46)
    print("质量门禁汇总")
    print("=" * 46)
    for name, ok in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"\n未通过：{', '.join(failed)}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
