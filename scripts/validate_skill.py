#!/usr/bin/env python3
"""validate_skill.py — 仓库结构与"证据边界"检查

防止两件事：
  1. 占位平台文档里混进未验证的流程/参数（S0 文档必须保持空白）；
  2. README 的平台表与 platforms/ 目录不一致。

只依赖标准库。退出码 0 = 通过，1 = 有问题。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# S0 文档里禁止出现的"流程痕迹"
FORBIDDEN_IN_STUB = [
    (re.compile(r"^##\s*\d+\.\s*标准流程", re.M), "出现「标准流程」小节"),
    (re.compile(r"```sh", re.M), "出现可执行命令块"),
    (re.compile(r"python3\s+\S*\.py"), "出现具体脚本调用"),
    (re.compile(r"0x[0-9A-Fa-f]{4,}"), "出现具体操作码/偏移"),
]
REQUIRED_IN_STUB = ["待验证", "S0"] or []
STATUS_RE = re.compile(r"状态[：:]\s*(S[0-4])|状态[^\n]*\b(S[0-4])\b")


def fail(msg):
    print(f"  [x] {msg}")
    return 1


def check_skill_md():
    print("SKILL.md")
    p = ROOT / "SKILL.md"
    if not p.exists():
        return fail("缺失")
    text = p.read_text(encoding="utf-8")
    bad = 0
    if not text.startswith("---"):
        bad += fail("缺少 YAML frontmatter")
    for key in ("name:", "description:"):
        if key not in text.split("---")[1]:
            bad += fail(f"frontmatter 缺 {key}")
    return bad


def check_platforms():
    print("references/platforms/")
    pdir = ROOT / "references" / "platforms"
    bad = 0
    psp = pdir / "psp.md"
    if not psp.exists():
        return fail("缺少唯一已验证平台 psp.md")

    stubs = sorted(f for f in pdir.glob("*.md") if f.name not in ("README.md", "psp.md"))
    if len(stubs) < 5:
        bad += fail(f"占位平台只有 {len(stubs)} 个，疑似被误删")

    for f in stubs:
        text = f.read_text(encoding="utf-8")
        head = text[:800]
        if "stub" not in head and "占位" not in head:
            bad += fail(f"{f.name}: 头部未标注占位")
        for pattern, desc in FORBIDDEN_IN_STUB:
            if pattern.search(text):
                bad += fail(f"{f.name}: S0 文档{desc}（未验证内容不得写入）")
        for word in ("待验证",):
            if word not in text:
                bad += fail(f"{f.name}: 缺少「{word}」清单")
    print(f"  占位文档 {len(stubs)} 个")
    return bad


def check_readme_table():
    print("README 平台表")
    p = ROOT / "README.md"
    if not p.exists():
        return fail("缺失 README.md")
    text = p.read_text(encoding="utf-8")
    bad = 0
    pdir = ROOT / "references" / "platforms"
    stubs = [f.stem for f in pdir.glob("*.md") if f.stem not in ("README", "psp")]
    # README 里以平台名出现即可，命名对应允许多种写法
    aliases = {"gb-gbc": ["GB / GBC", "GB-GBC", "GB/GBC"], "gc": ["NGC", "GameCube"],
               "switch": ["Switch"], "3ds": ["3DS"]}
    low = text.lower()
    for s in stubs:
        names = aliases.get(s, [s.upper()])
        if not any(n.lower() in low for n in names):
            bad += fail(f"README 未提到占位平台 {s}")
    if "PSP" not in text:
        bad += fail("README 未提到 PSP")
    return bad


def main():
    total = check_skill_md() + check_platforms() + check_readme_table()
    print()
    if total:
        print(f"结论：{total} 处问题。证据边界被破坏，不要合并。")
        return 1
    print("结论：结构与证据边界检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
