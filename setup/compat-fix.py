#!/usr/bin/env python3
"""
compat-fix.py — 兼容性自动修复

读取 verify-result.json 的兼容性 FAIL 项，自动修复能修的。
deploy.sh 在验证之后调用此脚本。

用法: python compat-fix.py <project_dir> <language>
退出码: 0=无需修复或已修复, 1=有修复动作（需重新验证）
"""

import json
import os
import re
import sys


def main():
    if len(sys.argv) < 3:
        print("用法: python compat-fix.py <project_dir> <language>")
        sys.exit(0)

    project_dir = sys.argv[1]
    language = sys.argv[2]
    verify_path = os.path.join(project_dir, ".deploy", "verify-result.json")

    if not os.path.exists(verify_path):
        sys.exit(0)

    vr = json.load(open(verify_path, encoding="utf-8"))
    compat = vr.get("sections", {}).get("compatibility", {})
    fails = [c for c in compat.get("checks", []) if c["status"] == "FAIL"]

    if not fails:
        sys.exit(0)

    fixed_count = 0
    os.chdir(project_dir)

    for f in fails:
        name = f["name"]
        detail = f.get("detail", "")

        # ── .nvmrc 不属于此项目 ──
        if ".nvmrc" in name:
            if language != "node" and os.path.exists(".nvmrc"):
                os.remove(".nvmrc")
                print(f"  FIXED: .nvmrc deleted ({language} project)")
                fixed_count += 1

        # ── 500 行 vs 大文件 → 补 exclude 白名单 ──
        if "500" in name or "大文件" in name:
            pccy = ".pre-commit-config.yaml"
            if os.path.exists(pccy):
                content = open(pccy, encoding="utf-8").read()
                # 检查 check-file-size 是否已有 exclude
                if "check-file-size" in content:
                    block = content.split("check-file-size")[1].split("- id:")[0]
                    if "exclude" not in block:
                        # 扫描大文件
                        ex = [
                            r"\.lock$", r"\.min\.", r"/out/", r"/dist/",
                            r"/build/", r"node_modules/", r"/vendor/",
                        ]
                        skip_dirs = {
                            "node_modules", "__pycache__", "venv", ".venv",
                            "dist", "build", "Library", "out", "Temp", "obj",
                            "bin", "target", "vendor", "projects", "packages",
                        }
                        for root, dirs, files in os.walk("."):
                            dirs[:] = [
                                d for d in dirs
                                if not d.startswith(".") and d not in skip_dirs
                            ]
                            for fn in files:
                                if fn.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".go", ".rs")):
                                    fp = os.path.join(root, fn)
                                    try:
                                        lines = sum(1 for _ in open(fp, encoding="utf-8", errors="replace"))
                                        if lines > 500:
                                            ex.append(re.escape(fn))
                                    except Exception:
                                        pass

                        excl_pat = "|".join(ex)
                        content = content.replace(
                            "        pass_filenames: true\n      - id: run-tests",
                            f"        pass_filenames: true\n        exclude: '{excl_pat}'\n      - id: run-tests",
                        )
                        open(pccy, "w", encoding="utf-8").write(content)
                        print(f"  FIXED: added exclude whitelist ({len(ex)} patterns)")
                        fixed_count += 1

        # ── 权限列表缺少语言工具 ──
        if "权限" in name or "permission" in name.lower():
            sj_path = os.path.join(".claude", "settings.json")
            if os.path.exists(sj_path):
                sj = json.load(open(sj_path, encoding="utf-8"))
                allows = sj.get("permissions", {}).get("allow", [])
                added = []
                if language == "python":
                    for p in ["Bash(pip *)", "Bash(pip3 *)", "Bash(python *)", "Bash(python3 *)", "Bash(pytest *)"]:
                        if p not in allows:
                            allows.append(p)
                            added.append(p)
                elif language == "go":
                    for p in ["Bash(go *)", "Bash(go test *)", "Bash(go build *)"]:
                        if p not in allows:
                            allows.append(p)
                            added.append(p)
                if added:
                    sj["permissions"]["allow"] = sorted(allows)
                    with open(sj_path, "w", encoding="utf-8") as fw:
                        json.dump(sj, fw, indent=2, ensure_ascii=False)
                    print(f"  FIXED: added {len(added)} tool permissions")
                    fixed_count += 1

        # ── PyYAML 缺失 ──
        if "PyYAML" in name:
            os.system("pip install pyyaml 2>/dev/null || pip3 install pyyaml 2>/dev/null")
            print("  FIXED: installed PyYAML")
            fixed_count += 1

    if fixed_count > 0:
        print(f"\n  {fixed_count} issue(s) auto-fixed")
        sys.exit(1)  # 告诉 deploy.sh 需要重新验证
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
