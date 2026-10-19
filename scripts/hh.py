#!/usr/bin/env python3
"""hh.py — 汉化工程通用工具（hanhua-workflow skill 的一部分）

只依赖标准库。设计目标是"默认不破坏 + 失败要早 + 报告即证据"：
  * 所有输出写独立目录，不覆盖源资源；
  * 每个校验都能给出可复算的数字；
  * 任何不确定的地方报 warning，不假装通过。

子命令：
  init       初始化汉化工程骨架（文档 / 数据目录 / 模板 / project.json）
  inventory  对解包树做清单（路径 + 大小 + SHA-256 + 树聚合哈希）
  overlay    对比原树与改后树，生成"只含改动文件"的变更集
  verify     校验变更集与原树的对应关系、哈希是否一致
  text       文本表检查 / 统计 / 导入
  glyphs     统计译文所需字符、与现有字库比对、算容量
  report     生成进度报告（L1/L2/L3 分层，不夸大）
  gate       发布门槛（结构 + 变更集 + 文本）
  doctor     工程体检（目录、配置、数据文件）

用法示例：
  python3 hh.py init ./my-project --title "某游戏汉化" --platform psp --engine cri-cpk
  python3 hh.py inventory ./work/extracted --out data/inventory
  python3 hh.py overlay ./orig/extracted ./work/build --out data/overlay
  python3 hh.py verify ./orig/extracted --overlay data/overlay
  python3 hh.py text check
  python3 hh.py report
"""

import argparse
import csv
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_ROOT / "assets" / "templates"

DEFAULT_EXCLUDES = [
    ".git", ".DS_Store", "__pycache__", "node_modules", ".idea", ".vscode",
    "work", "*.log", "*.tmp",
]

# 平台清单：只有 psp 经过实测（Fate/Extra）。其余为主机占位平台，只走通用阶段。
VERIFIED_PLATFORMS = {"psp"}
STUB_PLATFORMS = {
    "ps1", "ps2", "psv", "gb", "gbc", "gb-gbc", "gba", "nds", "3ds",
    "sfc", "snes", "n64", "gc", "ngc", "wii", "switch", "unknown",
}

# 控制码 / 占位符。PSP 部分（#C.. / #SVT[..] / #RUBS..#REND）是实测形式；
# 其余分支（{[var]}、<tag>、%s、\N[1]）属防御性覆盖，未在真实项目验证过，
# 作用是避免排版/统计时把它们当正文误处理。扩平台时按实测形式增补，不要凭猜测删改。
TOKEN_RE = re.compile(
    r"#(?:RUB[SE]|REND)"
    r"|#[A-Z]{2,}[0-9A-Z]*(?:\[[^\]]*\])?"
    r"|\\[A-Za-z]+\[[^\]]*\]"
    r"|\\[A-Za-z]+"
    r"|%[0-9]*[sd]"
    r"|\{[0-9A-Za-z_]+\}"
    r"|<[A-Za-z/][^>]*>"
)

RUBY_OPEN = "#RUBS"
RUBY_MID = "#RUBE"
RUBY_END = "#REND"

KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def eprint(*args):
    print(*args, file=sys.stderr)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_text(text):
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def rel_posix(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def is_excluded(rel_path, patterns):
    parts = rel_path.split("/")
    for pat in patterns:
        for part in parts:
            if fnmatch.fnmatch(part, pat):
                return True
        if fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def walk_tree(root, exclude_patterns=None):
    root = Path(root)
    patterns = list(DEFAULT_EXCLUDES) + list(exclude_patterns or [])
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not is_excluded(
            (Path(dirpath) / d).relative_to(root).as_posix(), patterns))
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if is_excluded(rel, patterns):
                continue
            yield rel, full


def text_width(s):
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl(path):
    rows = []
    p = Path(path)
    if not p.exists():
        return rows
    with open(p, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((lineno, json.loads(line)))
            except json.JSONDecodeError as exc:
                rows.append((lineno, {"__parse_error__": str(exc)}))
    return rows


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def project_config(root="."):
    return load_json(Path(root) / "project.json", {})


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def cmd_init(args):
    target = Path(args.dir).resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        eprint(f"[x] 目录非空：{target}\n    加 --force 才会覆盖模板文件（不会删除已有数据）。")
        return 2

    dirs = [
        "docs", "reports", "releases", "work",
        "data/inventory", "data/overlay", "data/review",
        "data/translation", "data/evidence",
    ]
    for d in dirs:
        (target / d).mkdir(parents=True, exist_ok=True)

    subs = {
        "{{TITLE}}": args.title,
        "{{PLATFORM}}": args.platform,
        "{{ENGINE}}": args.engine,
        "{{DATE}}": date.today().isoformat(),
        "{{SOURCE_ROOT}}": args.source_root or "<只读源目录，填绝对路径>",
    }

    def render(text):
        for k, v in subs.items():
            text = text.replace(k, str(v))
        return text

    copied = []
    if TEMPLATES.exists():
        mapping = {
            "AGENT.md": "AGENT.md",
            "ROADMAP.md": "ROADMAP.md",
            "CHANGELOG.md": "CHANGELOG.md",
            "qa-checklist.md": "docs/qa-checklist.md",
            "progress-report.md": "docs/progress-report.md",
            "glossary.csv": "data/translation/glossary.csv",
            "project.json": "project.json",
        }
        for src_name, dst_rel in mapping.items():
            src = TEMPLATES / src_name
            dst = target / dst_rel
            if not src.exists():
                continue
            if dst.exists() and not args.force:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(render(src.read_text(encoding="utf-8")), encoding="utf-8")
            copied.append(dst_rel)

    text_file = target / "data" / "translation" / "text.jsonl"
    if not text_file.exists():
        text_file.write_text("", encoding="utf-8")

    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "work/\ndist/\n*.iso\n*.nsp\n*.xci\n*.pkg\n__pycache__/\n.DS_Store\n",
            encoding="utf-8",
        )

    print(f"[+] 已初始化：{target}")
    print(f"    模板：{', '.join(copied) if copied else '（无）'}")
    print(f"    平台：{args.platform}")
    if args.platform not in VERIFIED_PLATFORMS:
        print("    [!] 该平台文档为 S0 占位：没有验证过的平台流程。")
        print("        只能执行 references/01-pipeline.md 的通用阶段；平台细节现场取证，")
        print("        并在项目内记录证据类型（E1–E5）。不要套用 PSP 的参数。")
    print("    下一步：")
    print("      1. 编辑 project.json，填写 source.root 与平台参数")
    print("      2. 把原盘/原资源解包到 work/extracted（只读副本）")
    print("      3. python3 hh.py inventory work/extracted --out data/inventory")
    print("      4. 读 references/01-pipeline.md，做最小闭环")
    return 0


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------

def cmd_inventory(args):
    src = Path(args.src)
    if not src.is_dir():
        eprint(f"[x] 不是目录：{src}")
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    records = []
    tree_h = hashlib.sha256()
    total = 0
    for rel, full in walk_tree(src, args.exclude):
        size = full.stat().st_size
        digest = sha256_file(full)
        records.append({"path": rel, "size": size, "sha256": digest})
        tree_h.update(f"{rel}\0{digest}\n".encode("utf-8"))
        total += size

    manifest = out / "manifest.jsonl"
    with open(manifest, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = {
        "schema": 1,
        "root": str(src.resolve()),
        "root_name": src.resolve().name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(records),
        "total_bytes": total,
        "tree_sha256": tree_h.hexdigest(),
    }
    write_json(out / "summary.json", summary)

    print(f"[+] 清单完成：{len(records)} 个文件 / {total / 1048576:.1f} MiB")
    print(f"    tree_sha256 = {summary['tree_sha256']}")
    print(f"    输出：{manifest}")
    return 0


# --------------------------------------------------------------------------
# overlay
# --------------------------------------------------------------------------

def collect_tree(root, excludes):
    table = {}
    for rel, full in walk_tree(root, excludes):
        if full.stat().st_size == 0 and rel.endswith(".keep"):
            continue
        table[rel] = full
    return table


def cmd_overlay(args):
    src = Path(args.src).resolve()
    work = Path(args.work).resolve()
    out = Path(args.out).resolve()

    if not src.is_dir() or not work.is_dir():
        eprint("[x] --src 与 --work 都必须是目录")
        return 2
    if out == src or src in out.parents:
        eprint("[x] 输出目录不能位于源树内部")
        return 2
    if out.exists() and any(out.iterdir()) and not args.force:
        eprint(f"[x] 输出目录非空：{out}\n    加 --force 覆盖（会先清理 files/）")
        return 2

    src_tree = collect_tree(src, args.exclude)
    work_tree = collect_tree(work, args.exclude)

    added, modified = [], []
    for rel, full in work_tree.items():
        if rel not in src_tree:
            added.append(rel)
        else:
            if full.stat().st_size != src_tree[rel].stat().st_size or \
                    sha256_file(full) != sha256_file(src_tree[rel]):
                modified.append(rel)
    removed = sorted(set(src_tree) - set(work_tree))

    files_dir = out / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    total_bytes = 0
    payload = sorted(added + modified)
    if args.limit and len(payload) > args.limit:
        eprint(f"[!] 变更文件 {len(payload)} 个，超过 --limit {args.limit}，已中止。")
        eprint("    先确认 work/ 里没有混入无关产物（例如解包缓存）。")
        return 3

    for rel in payload:
        full = work_tree[rel]
        dst = files_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full, dst)
        size = dst.stat().st_size
        total_bytes += size
        entries.append({
            "path": rel,
            "op": "add" if rel in added else "modify",
            "size": size,
            "sha256": sha256_file(dst),
            "source_sha256": sha256_file(src_tree[rel]) if rel in src_tree else None,
        })

    manifest = {
        "schema": 1,
        "source_root": str(src),
        "work_root": str(work),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "total_bytes": total_bytes,
        "added": len(added),
        "modified": len(modified),
        "removed": removed,
        "files": entries,
    }

    if args.dry_run:
        print(f"[dry-run] 新增 {len(added)} / 修改 {len(modified)} / 删除 {len(removed)}")
        for e in entries[:20]:
            print(f"  {e['op']:6} {e['path']}  {e['size']} B")
        if len(entries) > 20:
            print(f"  ... 其余 {len(entries) - 20} 个")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "manifest.json", manifest)
    print(f"[+] 变更集：{len(entries)} 个文件 / {total_bytes / 1048576:.2f} MiB")
    print(f"    新增 {len(added)} · 修改 {len(modified)} · 删除 {len(removed)}")
    print(f"    输出：{out / 'manifest.json'}")
    if removed:
        print(f"    [!] 有 {len(removed)} 个文件在 work 中缺失，已记录但未应用删除")
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(args):
    src = Path(args.src).resolve()
    overlay = Path(args.overlay).resolve()
    manifest_path = overlay / "manifest.json"
    manifest = load_json(manifest_path)
    if not manifest:
        eprint(f"[x] 找不到变更集清单：{manifest_path}")
        return 2

    errors, warnings, checked = [], [], 0
    for entry in manifest.get("files", []):
        rel = entry["path"]
        payload = overlay / "files" / rel
        if not payload.exists():
            errors.append(f"负载缺失：{rel}")
            continue
        actual = sha256_file(payload)
        if actual != entry["sha256"]:
            errors.append(f"负载哈希不符：{rel}")
            continue
        source = src / rel
        if entry.get("source_sha256"):
            if not source.exists():
                errors.append(f"源文件缺失：{rel}")
                continue
            real_src = sha256_file(source)
            if real_src != entry["source_sha256"]:
                errors.append(
                    f"源哈希已变：{rel}\n      记录 {entry['source_sha256'][:16]}… 实际 {real_src[:16]}…")
                continue
        checked += 1

    for rel in manifest.get("removed", []):
        if not (src / rel).exists():
            warnings.append(f"清单记录的删除项在源中也不存在：{rel}")

    print(f"校验 {checked} 个文件，错误 {len(errors)}，警告 {len(warnings)}")
    for e in errors[:30]:
        print(f"  [x] {e}")
    if len(errors) > 30:
        print(f"  ... 其余 {len(errors) - 30} 个错误")
    for w in warnings[:10]:
        print(f"  [!] {w}")
    if errors:
        print("\n结论：结构校验未通过。先修变更集，不要继续构建。")
        return 1
    print("\n结论：变更集与源树一致（L1 结构层）。这不代表译文正确。")
    return 0


# --------------------------------------------------------------------------
# text check / stats / import
# --------------------------------------------------------------------------

def resolve_text_path(args):
    if getattr(args, "text", None):
        return Path(args.text)
    cfg = project_config(".")
    rel = (cfg.get("text") or {}).get("file", "data/translation/text.jsonl")
    return Path(rel)


def token_kinds(text):
    kinds = []
    for m in TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok.startswith(RUBY_OPEN):
            kinds.append("RUBS")
        elif tok.startswith(RUBY_MID):
            kinds.append("RUBE")
        elif tok.startswith(RUBY_END):
            kinds.append("REND")
        else:
            kinds.append(tok)
    return kinds


def load_glossary(path):
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    with open(p, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            jp = (row.get("jp") or "").strip()
            zh = (row.get("zh") or "").strip()
            if jp and zh:
                rows.append({"jp": jp, "zh": zh, "note": (row.get("note") or "").strip()})
    return rows


def check_text(text_path, cfg, glossary_path, max_width=None, strict_ids=False,
               allow_kana=False, glossary_limit=20):
    errors, warnings = [], []
    rows = read_jsonl(text_path)
    if not rows:
        return errors, warnings, {"total": 0, "non_empty": 0, "empty": 0}

    max_width = max_width or (cfg.get("gates") or {}).get("max_line_width", 0) or 0
    id_algo = (cfg.get("text") or {}).get("id_algo", "sha256-16")
    fields = (cfg.get("text") or {}).get("fields") or {}
    f_id = fields.get("id", "id")
    f_src = fields.get("source", "jp")
    f_dst = fields.get("target", "zh_cn")

    glossary = load_glossary(glossary_path)
    seen = {}
    non_empty = 0
    identical = 0
    glossary_hits = 0

    for lineno, row in rows:
        if "__parse_error__" in row:
            errors.append(f"L{lineno} JSON 解析失败：{row['__parse_error__']}")
            continue
        rid = str(row.get(f_id, "")).strip()
        src = row.get(f_src) or ""
        dst = row.get(f_dst) or ""
        if not rid:
            errors.append(f"L{lineno} 缺少 id")
            continue
        if rid in seen:
            errors.append(f"L{lineno} id 重复：{rid}（首次出现在 L{seen[rid]}）")
        else:
            seen[rid] = lineno

        if strict_ids and src and id_algo == "sha256-16":
            expect = sha256_text(src)[:16]
            if rid != expect:
                errors.append(f"L{lineno} id 与原文哈希不符：{rid} != {expect}（改原文会让批次失联）")

        if not str(dst).strip():
            continue
        non_empty += 1

        if str(dst).strip() == str(src).strip() and KANA_RE.search(str(src)):
            identical += 1
            warnings.append(f"L{lineno} 译文与原文相同，疑似未翻译：{rid}")

        src_tokens = token_kinds(str(src))
        dst_tokens = token_kinds(str(dst))
        if src_tokens or dst_tokens:
            missing = [t for t in src_tokens if src_tokens.count(t) > dst_tokens.count(t)]
            extra = [t for t in dst_tokens if dst_tokens.count(t) > src_tokens.count(t)]
            if missing or extra:
                detail = []
                if missing:
                    detail.append("缺 " + ",".join(sorted(set(missing))[:6]))
                if extra:
                    detail.append("多 " + ",".join(sorted(set(extra))[:6]))
                errors.append(f"L{lineno} 控制码不一致：{rid}（{'；'.join(detail)}）")

        depth = 0
        ruby_bad = None
        for kind in dst_tokens:
            if kind == "RUBS":
                depth += 1
            elif kind in ("RUBE", "REND"):
                if depth < 1:
                    ruby_bad = f"{kind} 提前出现"
                    break
                if kind == "REND":
                    depth -= 1
        if ruby_bad:
            errors.append(f"L{lineno} ruby 结构错误：{rid}（{ruby_bad}）")
        elif depth != 0:
            errors.append(f"L{lineno} ruby 结构未闭合：{rid}（缺 #REND）")

        if max_width:
            clean = TOKEN_RE.sub("", str(dst))
            for seg in clean.split("\n"):
                if text_width(seg) > max_width:
                    warnings.append(
                        f"L{lineno} 行宽 {text_width(seg)} > {max_width}：{rid}")
                    break

        if not allow_kana and KANA_RE.search(str(dst)):
            warnings.append(f"L{lineno} 译文含日文假名：{rid}")

        if glossary and glossary_hits < glossary_limit:
            for term in glossary:
                if term["jp"] in str(src) and term["zh"] not in str(dst):
                    warnings.append(
                        f"L{lineno} 术语候选：'{term['jp']}' 应作 '{term['zh']}'（{rid}）")
                    glossary_hits += 1
                    if glossary_hits >= glossary_limit:
                        break

    stats = {
        "total": len(rows),
        "non_empty": non_empty,
        "empty": len(rows) - non_empty,
        "identical_to_source": identical,
        "unique_ids": len(seen),
        "coverage": round(non_empty / max(1, len(rows)), 6),
        "control_code_errors": sum(1 for e in errors if "控制码" in e),
        "ruby_errors": sum(1 for e in errors if "ruby" in e),
    }
    return errors, warnings, stats


def cmd_text_check(args):
    text_path = resolve_text_path(args)
    if not text_path.exists():
        eprint(f"[x] 文本表不存在：{text_path}")
        return 2
    cfg = project_config(args.project_root)
    glossary = args.glossary or (
        cfg.get("text", {}).get("glossary", "data/translation/glossary.csv"))
    errors, warnings = [], []
    cfg_strict = (cfg.get("gates") or {}).get("strict_ids", False)
    errors, warnings, stats = check_text(
        text_path, cfg, glossary,
        max_width=args.max_width,
        strict_ids=args.strict_ids or cfg_strict,
        allow_kana=args.allow_kana,
    )

    if args.json:
        print(json.dumps(
            {"stats": stats, "errors": errors, "warnings": warnings},
            ensure_ascii=False, indent=2))
    else:
        print(f"文本表：{text_path}")
        print(f"  条目 {stats['total']} · 非空 {stats['non_empty']} · 空 {stats['empty']}"
              f" · 覆盖率 {stats['coverage'] * 100:.2f}%")
        print(f"  错误 {len(errors)} · 警告 {len(warnings)}")
        for e in errors[:40]:
            print(f"  [x] {e}")
        if len(errors) > 40:
            print(f"  ... 其余 {len(errors) - 40} 个错误")
        for w in warnings[:20]:
            print(f"  [!] {w}")
        if len(warnings) > 20:
            print(f"  ... 其余 {len(warnings) - 20} 个警告")

    if errors:
        print("\n结论：结构层未通过。控制码/ruby 结构错误会直接改变运行时行为。")
        return 1
    print("\n结论：结构层通过（可编码、控制码与 ruby 结构一致）。语义层未验证。")
    return 0


def cmd_text_stats(args):
    text_path = resolve_text_path(args)
    rows = read_jsonl(text_path)
    cfg = project_config(args.project_root)
    f_dst = ((cfg.get("text") or {}).get("fields") or {}).get("target", "zh_cn")
    f_src = ((cfg.get("text") or {}).get("fields") or {}).get("source", "jp")
    per_file = {}
    total_chars = 0
    for _, row in rows:
        zh = str(row.get(f_dst) or "")
        total_chars += len(zh)
        key = (row.get("file") or "(未标注)")
        bucket = per_file.setdefault(key, {"total": 0, "done": 0})
        bucket["total"] += 1
        if zh.strip():
            bucket["done"] += 1
    out = {
        "total": len(rows),
        "non_empty": sum(1 for _, r in rows if str(r.get(f_dst) or "").strip()),
        "total_chars": total_chars,
        "source_chars": sum(len(str(r.get(f_src) or "")) for _, r in rows),
        "files": per_file,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"条目 {out['total']} · 非空 {out['non_empty']} · 译文字符 {out['total_chars']}")
        for name, b in sorted(per_file.items(), key=lambda kv: -kv[1]["total"])[:15]:
            pctv = 100 * b["done"] / max(1, b["total"])
            print(f"  {pctv:6.1f}%  {b['done']}/{b['total']}  {name}")
    return 0


def cmd_text_import(args):
    src = Path(args.input)
    if not src.exists():
        eprint(f"[x] 输入不存在：{src}")
        return 2
    out = Path(args.out) if args.out else resolve_text_path(args)
    records = []
    fmt = args.format
    if fmt == "auto":
        fmt = {".jsonl": "jsonl", ".json": "jsonl", ".tsv": "tsv", ".csv": "csv"}.get(
            src.suffix.lower(), "tsv")

    if fmt == "jsonl":
        for _, row in read_jsonl(src):
            records.append(row)
    else:
        delim = "\t" if fmt == "tsv" else ","
        with open(src, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter=delim)
            rows = list(reader)
        if not rows:
            eprint("[x] 输入为空")
            return 2
        header = [c.strip().lower() for c in rows[0]]
        has_header = any(h in ("jp", "source", "原文", "zh", "target", "译文") for h in header)
        if has_header:
            def idx(names, default):
                for n in names:
                    if n in header:
                        return header.index(n)
                return default
            i_src = idx(("jp", "source", "原文"), 0)
            i_dst = idx(("zh", "zh_cn", "target", "译文"), 1)
            body = rows[1:]
        else:
            i_src, i_dst, body = 0, 1, rows
        for r in body:
            if len(r) <= max(i_src, i_dst):
                continue
            records.append({"jp": r[i_src], "zh_cn": r[i_dst]})

    existing = {}
    if out.exists() and args.merge:
        for _, row in read_jsonl(out):
            if row.get("id"):
                existing[row["id"]] = row

    written, skipped = 0, 0
    lines = []
    seen = set()
    for rec in records:
        jp = rec.get("jp") or rec.get("source") or ""
        zh = rec.get("zh_cn") or rec.get("zh") or rec.get("target") or ""
        if not str(jp).strip():
            skipped += 1
            continue
        rid = rec.get("id") or sha256_text(str(jp))[:16]
        if rid in seen:
            skipped += 1
            continue
        seen.add(rid)
        base = existing.get(rid, {})
        row = dict(base)
        row.update({"id": rid, "jp": jp, "zh_cn": zh})
        for k, v in rec.items():
            if k not in ("id", "jp", "zh_cn", "source", "target", "zh"):
                row.setdefault(k, v)
        lines.append(json.dumps(row, ensure_ascii=False))
        written += 1

    if args.merge and existing:
        for rid, row in existing.items():
            if rid not in seen:
                lines.append(json.dumps(row, ensure_ascii=False))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"[+] 写入 {written} 条（跳过 {skipped}）→ {out}")
    if args.merge:
        print("    已合并既有条目（按 id 去重）")
    return 0


# --------------------------------------------------------------------------
# glyphs
# --------------------------------------------------------------------------

def cmd_glyphs(args):
    text_path = resolve_text_path(args)
    cfg = project_config(args.project_root)
    f_dst = ((cfg.get("text") or {}).get("fields") or {}).get("target", "zh_cn")

    # 网格参数必须来自实测：优先命令行，其次 project.json 的 font.grids。
    # 绝不给默认值——不同平台、同一游戏的不同字库，参数都不同。
    grids = (cfg.get("font") or {}).get("grids") or []
    grid = None
    if args.grid:
        for g in grids:
            if str(g.get("name")) == args.grid:
                grid = g
                break
        if grid is None:
            eprint(f"[x] project.json 里没有名为 {args.grid} 的 grid。")
            return 2
    elif grids:
        grid = grids[0]

    cols = args.cols or (grid or {}).get("cols")
    pages = args.pages or (grid or {}).get("pages")
    if not cols or not pages:
        eprint("[x] 缺网格参数：cols 与 pages 必须实测得到。")
        eprint("    做法：在 project.json 的 font.grids 里填实测值，或用 --cols/--pages 显式传入。")
        eprint("    本工具不提供默认值，因为不同平台/不同字库的网格各不相同。")
        return 2
    cols, pages = int(cols), int(pages)

    chars = {}
    for _, row in read_jsonl(text_path):
        for ch in str(row.get(f_dst) or ""):
            if ch.isspace() or ch in "\u200b\ufeff":
                continue
            if TOKEN_RE.fullmatch(ch):
                continue
            chars[ch] = chars.get(ch, 0) + 1

    have = set()
    if args.have:
        data = load_json(args.have, [])
        if isinstance(data, dict):
            data = list(data.keys())
        have = set(str(c) for c in data)
    missing = sorted(set(chars) - have) if have else sorted(chars)

    per_page = cols * cols
    capacity = per_page * pages
    need = len(chars)
    detail = {
        "unique_chars": need,
        "have": len(have) if have else None,
        "missing": len(missing),
        "grid": {"name": (grid or {}).get("name"), "cols": cols, "per_page": per_page,
                 "pages": pages, "capacity": capacity},
        "overflow": need > capacity,
        "top": [[c, n] for c, n in sorted(chars.items(), key=lambda kv: -kv[1])[:40]],
        "missing_sample": missing[:200],
    }
    if args.json:
        print(json.dumps(detail, ensure_ascii=False, indent=2))
    else:
        label = (grid or {}).get("name") or "未命名"
        print(f"网格 {label}：{cols}×{cols} / {per_page} 字每页 / {pages} 页")
        print(f"译文唯一字符 {need}；字库容量 {capacity}")
        if have:
            print(f"现有字库 {len(have)} 字，缺 {len(missing)} 字")
        if detail["overflow"]:
            print("[x] 超出容量：需要压缩或扩容，不要直接写库")
            return 1
        print("结论：容量足够（字符集统计）。仍需验证字位分配与渲染。")
    return 0


# --------------------------------------------------------------------------
# report / gate / doctor
# --------------------------------------------------------------------------

def cmd_report(args):
    cfg = project_config(args.project_root)
    text_path = resolve_text_path(args)
    errors, warnings, stats = check_text(
        text_path, cfg,
        (cfg.get("text") or {}).get("glossary", "data/translation/glossary.csv"),
        max_width=None,
        strict_ids=(cfg.get("gates") or {}).get("strict_ids", False),
    )
    overlay = load_json("data/overlay/manifest.json", {})
    inventory = load_json("data/inventory/summary.json", {})
    state = load_json("data/review/state.json", {})

    l2 = state.get("L2", {})
    l3 = state.get("L3", {})
    lanes = state.get("lanes", [])

    lines = []
    lines.append(f"# 进度报告 · {cfg.get('title', '未命名项目')}")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- 文本条目：{stats['total']}，非空 {stats['non_empty']}，"
                 f"覆盖率 {stats['coverage'] * 100:.2f}%")
    lines.append(f"- 结构错误：{len([e for e in errors if '控制码' in e or 'ruby' in e or 'id' in e])}")
    lines.append(f"- 变更集：{overlay.get('count', 0)} 个文件 / "
                 f"{overlay.get('total_bytes', 0) / 1048576:.2f} MiB")
    lines.append(f"- 解包清单：{inventory.get('file_count', 0)} 个文件 / "
                 f"{inventory.get('total_bytes', 0) / 1048576:.1f} MiB")
    lines.append("")
    lines.append("## 分层状态")
    lines.append("")
    lines.append("| 层 | 状态 | 证据 | 未覆盖 |")
    lines.append("|---|---|---|---|")
    l1_ok = not [e for e in errors if "控制码" in e or "ruby" in e]
    lines.append(f"| L1 结构 | {'通过' if l1_ok else '未通过'} | "
                 f"文本表 {stats['total']} 条、变更集 {overlay.get('count', 0)} 文件 | "
                 f"{'—' if l1_ok else '见错误清单'} |")
    l2_targets = l2.get("targets") or sum(l.get("targets", 0) for l in lanes)
    l2_read = l2.get("read") or sum(l.get("read", 0) for l in lanes)
    lines.append(f"| L2 语义 | {'进行中' if l2_read else '未开始'} | "
                 f"已读 {l2_read} / {l2_targets or '—'} | "
                 f"未读 {max(0, (l2_targets or 0) - l2_read)} |")
    paths = l3.get("paths") or []
    lines.append(f"| L3 运行时 | {'已抽检' if paths else '未验证'} | "
                 f"{('、'.join(paths[:4]) + ('…' if len(paths) > 4 else '')) if paths else '未启动模拟器/实机'} | "
                 f"{l3.get('note', '未覆盖分支')} |")
    lines.append("")
    if lanes:
        lines.append("## 校对 lane")
        lines.append("")
        lines.append("| lane | 目标 | 已读 | 修正 |")
        lines.append("|---|---:|---:|---:|")
        for lane in lanes:
            lines.append(f"| {lane.get('name', '?')} | {lane.get('targets', 0)} | "
                         f"{lane.get('read', 0)} | {lane.get('fixed', 0)} |")
        lines.append("")
    if warnings:
        lines.append(f"## 待处理警告（前 15 条，共 {len(warnings)}）")
        lines.append("")
        for w in warnings[:15]:
            lines.append(f"- {w}")
        lines.append("")
    lines.append("## 声明边界")
    lines.append("")
    lines.append("- 覆盖率统计的是非空译文，不代表语义正确。")
    lines.append("- L1 通过不代表游戏可运行；L2 读过一部分不代表全量正确。")
    lines.append("- 本报告由 `hh.py report` 生成，数字来自工程内数据文件。")
    lines.append("")

    content = "\n".join(lines)
    out = Path(args.out) if args.out else Path("reports") / f"progress-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(content[:1500])
    print(f"\n[+] 报告已写入：{out}")
    return 0


def cmd_doctor(args):
    checks = []

    def add(name, ok, detail="", level="fail"):
        checks.append({"name": name, "ok": ok, "detail": detail, "level": level})

    root = Path(args.project_root)
    cfg_path = root / "project.json"
    add("project.json", cfg_path.exists(), str(cfg_path))
    cfg = load_json(cfg_path, {})
    plat = str(cfg.get("platform") or "").strip()
    add("平台已填写", bool(plat) and plat != "<平台>", plat or "未填写")
    if plat and plat != "<平台>":
        if plat.lower() in VERIFIED_PLATFORMS:
            add("平台已验证", True, "已验证（S4，见 platforms/psp.md）")
        elif plat.lower() in STUB_PLATFORMS:
            add("平台已验证", False, "S0 占位：无平台流程可依，只能走通用阶段", "warn")
        else:
            add("平台已验证", False, "未登记平台：先在 platforms/ 建 stub，再就地取证", "warn")
    text_path = resolve_text_path(args) if not args.text else Path(args.text)
    add("文本表", text_path.exists(), str(text_path))
    add("术语表", Path("data/translation/glossary.csv").exists(), "data/translation/glossary.csv", "warn")
    add("解包清单", Path("data/inventory/summary.json").exists(), "data/inventory/summary.json", "warn")
    add("变更集", Path("data/overlay/manifest.json").exists(), "data/overlay/manifest.json", "warn")
    add("AGENT.md", (root / "AGENT.md").exists(), "作业手册", "warn")
    add("报告目录", (root / "reports").exists(), "reports/", "warn")

    failed = [c for c in checks if not c["ok"] and c["level"] == "fail"]
    print(f"{'项目':<16} {'状态':<6} 说明")
    for c in checks:
        mark = "OK" if c["ok"] else ("WARN" if c["level"] == "warn" else "FAIL")
        print(f"{c['name']:<16} {mark:<6} {c['detail']}")
    print(f"\n结论：{'结构就绪' if not failed else '存在阻塞项 ' + str(len(failed))}")
    return 1 if failed else 0


def cmd_gate(args):
    results = []
    cfg = project_config(args.project_root)
    text_path = resolve_text_path(args)
    errors, warnings, stats = check_text(
        text_path, cfg,
        (cfg.get("text") or {}).get("glossary", "data/translation/glossary.csv"),
        max_width=(cfg.get("gates") or {}).get("max_line_width"),
        strict_ids=(cfg.get("gates") or {}).get("strict_ids", False),
    )
    results.append(("文本结构（控制码/ruby/id）", not errors, f"错误 {len(errors)}"))

    overlay_path = Path("data/overlay/manifest.json")
    if overlay_path.exists():
        manifest = load_json(overlay_path, {})
        bad = 0
        for entry in manifest.get("files", []):
            payload = Path("data/overlay/files") / entry["path"]
            if not payload.exists() or sha256_file(payload) != entry["sha256"]:
                bad += 1
        results.append(("变更集负载完整", bad == 0, f"{manifest.get('count', 0)} 个文件，损坏 {bad}"))
    else:
        results.append(("变更集", False, "缺 data/overlay/manifest.json"))

    total = stats["total"]
    coverage = stats["coverage"] if total else 0
    results.append(("译文覆盖率 ≥ 99%", coverage >= 0.99, f"{coverage * 100:.2f}%"))

    reports = sorted(Path("reports").glob("progress-*.md")) if Path("reports").exists() else []
    results.append(("进度报告存在", bool(reports), str(reports[-1]) if reports else "未生成"))

    state = load_json("data/review/state.json", {})
    l3 = (state.get("L3") or {}).get("paths") or []
    results.append(("运行时抽检已记录", bool(l3), f"{len(l3)} 条路径" if l3 else "未记录 L3"))

    print(f"{'门槛':<28} {'结果':<6} 说明")
    for name, ok, detail in results:
        print(f"{name:<28} {'PASS' if ok else 'FAIL':<6} {detail}")
    failed = [r for r in results if not r[1]]
    print()
    if failed:
        print(f"结论：{len(failed)} 项未过，不可发布。")
        if args.level == "release":
            print("发布说明必须写明未完成项，不得写「完美汉化」。")
        return 1
    print("结论：门槛通过。发布说明仍需写明未覆盖范围。")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="hh.py",
        description="汉化工程通用工具：初始化 / 盘点 / 变更集 / 校验 / 文本检查 / 报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="初始化汉化工程骨架")
    s.add_argument("dir")
    s.add_argument("--title", required=True)
    s.add_argument("--platform", default="unknown",
                   help="主机平台：psp（唯一已验证）/ ps1 / ps2 / psv / gb-gbc / gba / nds / 3ds / "
                        "sfc / n64 / gc / wii / switch（后者均为 S0 占位）")
    s.add_argument("--engine", default="unknown")
    s.add_argument("--source-root", default="")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("inventory", help="生成解包树清单")
    s.add_argument("src")
    s.add_argument("--out", default="data/inventory")
    s.add_argument("--exclude", action="append", default=[])
    s.set_defaults(func=cmd_inventory)

    s = sub.add_parser("overlay", help="生成只含改动文件的变更集")
    s.add_argument("src", help="原始解包树（只读）")
    s.add_argument("work", help="改动后的树")
    s.add_argument("--out", default="data/overlay")
    s.add_argument("--exclude", action="append", default=[])
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--limit", type=int, default=0, help="变更文件数上限，0 为不限制")
    s.set_defaults(func=cmd_overlay)

    s = sub.add_parser("verify", help="校验变更集")
    s.add_argument("src")
    s.add_argument("--overlay", default="data/overlay")
    s.set_defaults(func=cmd_verify)

    t = sub.add_parser("text", help="文本表操作")
    tsub = t.add_subparsers(dest="text_command", required=True)
    for name, func, helptext in (
        ("check", cmd_text_check, "结构检查（控制码 / ruby / 术语候选 / 行宽）"),
        ("stats", cmd_text_stats, "覆盖率与分文件统计"),
        ("import", cmd_text_import, "从 TSV/CSV/JSONL 导入译文"),
    ):
        ts = tsub.add_parser(name, help=helptext)
        ts.add_argument("--text", default=None)
        ts.add_argument("--project-root", default=".")
        ts.set_defaults(func=func)
        if name == "check":
            ts.add_argument("--glossary", default=None)
            ts.add_argument("--max-width", type=int, default=None)
            ts.add_argument("--strict-ids", action="store_true")
            ts.add_argument("--allow-kana", action="store_true")
            ts.add_argument("--json", action="store_true")
        if name == "stats":
            ts.add_argument("--json", action="store_true")
        if name == "import":
            ts.add_argument("input")
            ts.add_argument("--out", default=None)
            ts.add_argument("--format", choices=["auto", "tsv", "csv", "jsonl"], default="auto")
            ts.add_argument("--merge", action="store_true")

    g = sub.add_parser("glyphs", help="字符集与字库容量核算（网格参数必须实测）")
    g.add_argument("--text", default=None)
    g.add_argument("--project-root", default=".")
    g.add_argument("--have", default=None, help="现有字库字符集 JSON（数组或字典）")
    g.add_argument("--grid", default=None, help="按 project.json 里 font.grids 的 name 选一套")
    g.add_argument("--cols", type=int, default=None, help="每行格数（= 单页边长的格数），必填或从 project.json 读")
    g.add_argument("--pages", type=int, default=None, help="页数，必填或从 project.json 读")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_glyphs)

    s = sub.add_parser("report", help="生成分层进度报告")
    s.add_argument("--text", default=None)
    s.add_argument("--project-root", default=".")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("gate", help="发布门槛检查")
    s.add_argument("--text", default=None)
    s.add_argument("--project-root", default=".")
    s.add_argument("--level", choices=["pre", "release"], default="release")
    s.set_defaults(func=cmd_gate)

    s = sub.add_parser("doctor", help="工程体检")
    s.add_argument("--text", default=None)
    s.add_argument("--project-root", default=".")
    s.set_defaults(func=cmd_doctor)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        eprint("\n[!] 已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
