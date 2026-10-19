# 仓库、变更集与发布

目标：别人拿到仓库，能用同一张原盘重建出同一份产物。

---

## 1. 仓库里放什么

| 放 | 不放 |
|---|---|
| 脚本、文档、术语表、译文 | 原版镜像、未修改的游戏资源 |
| 改动过的资源（变更集） | 解包缓存（`work/`） |
| 逐文件哈希清单 | 第三方工具二进制 |
| 发布说明与已知问题 | 需要授权的密钥/字体 |

原则：**仓库只保证"可重建"，不保证"可直接玩"。**

---

## 2. 目录结构

```
docs/               流程、格式、踩坑、验收
data/translation/   text.jsonl、glossary.csv、glyph-map.json
data/inventory/     解包树清单（manifest.jsonl + summary.json）
data/overlay/       变更集（files/ + manifest.json）
data/review/        审计结果、校对进度、state.json
data/evidence/      截图、配置、取证
scripts/            pipeline / audit / validate
reports/            每次构建与校验的报告
releases/           发布说明
work/               本地工作区，不入库
```

---

## 3. 变更集：只放改过的东西

```sh
python3 scripts/hh.py overlay ./orig/extracted ./work/build --out data/overlay
python3 scripts/hh.py verify ./orig/extracted --overlay data/overlay
```

`manifest.json` 字段：

```json
{
  "schema": 1,
  "count": 375,
  "total_bytes": 71900512,
  "removed": [],
  "files": [
    {"path": "pack/PRELOAD/kanzi.bin", "op": "modify",
     "size": 123456, "sha256": "…", "source_sha256": "…"}
  ]
}
```

- `source_sha256` 是**构建基线**的哈希；重建前用它确认原盘版本正确。
- `removed` 只记录不应用；删除资源要单独走一次显式操作。
- 变更集是"改动文件"，不是原版资源，可以入库。

---

## 4. 版本与产物

| 概念 | 建议 |
|---|---|
| 工程版本 | `v0.x`，对应内部迭代序号 |
| 内容版本 | 正式发布用 `v1.0.0` |
| 预发布 | `-pre` 或标注"资源预备版" |
| 产物命名 | `<游戏>_CN_v<版本>.iso` / `.zip`（补丁） |

每个版本至少记录：

- 基于哪个源版本（镜像号 / 可执行文件哈希）；
- 产物 SHA-256；
- 变更计数（文本 / 字库 / 图片 / 资源）；
- 验证层级与覆盖路径。

`prepared_only: true` 的构建不是发布。

---

## 5. 提交信息

```
<area>: <what changed>

Why: <root cause / requirement>
Verify: <command + result>
```

`area`：`text` `font` `image` `build` `docs` `tooling`

示例：

```
font: allocate 299 missing glyphs on a third page

Why: original ruby.bin has 219 kana/latin entries and zero Han; retained
ruby text needs 299 more characters.
Verify: annotation-font-build.json reports 518 rows / 3 pages; original
219 cells preserved; roundtrip 0 mismatches.
```

---

## 6. 发布说明模板

```markdown
# vX.Y.Z — <主题>

基于：<镜像号 / 版本>（可执行文件 SHA-256: …）
产物：<文件名>（SHA-256: …）

## 本版变更
- 文本：N 条（新增 / 修正）
- 字库：…
- 图片：…
- 资源：N 个文件 / N MB

## 已验证
- L1：控制码 0 错误；变更集 375 文件校验通过
- L2：已读 N / M，修正 K 条
- L3：PPSSPP 开场到第一场战斗；实机 <路径>

## 未完成 / 已知问题
- ……
- 未覆盖：……

## 安装
1. 自备 <区域> 原盘
2. ……
```

禁止写："完美汉化""全部完成""彻底修复"。

---

## 7. 可复现性检查

新机器上只做三件事，能重建出同样哈希的产物：

1. 自备原盘，校验镜像号/可执行文件哈希；
2. 套用变更集（或按脚本重建）；
3. 跑 `hh.py verify` 与构建报告比对。

做不到，说明仓库缺了东西（脚本、映射、配置、对齐参数）。**缺任何一项都不算可复现。**

---

## 8. 交接清单

- [ ] `AGENT.md` 的"当前状态快照"是最新的
- [ ] `project.json` 的平台/引擎/网格参数与实测一致
- [ ] 变更集 `manifest.json` 的 `source_sha256` 与当前基线一致
- [ ] 报告目录里有最近一次构建报告
- [ ] 已知问题与未完成项写在 `ROADMAP.md`
- [ ] 新人按 README 能在 30 分钟内跑通最小闭环
