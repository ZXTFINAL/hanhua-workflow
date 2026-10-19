---
name: hanhua-workflow
description: 主机游戏汉化的标准流程与工具。用于汉化工程初始化、容器解包/重建、文本提取与回填、排版、字库补字与容量核算、UI 图片替换、镜像写回、变更集校验与分层进度报告。当前只有 PSP（Fate/Extra）经过完整实测，其他主机平台为占位，遇到时只能用通用阶段现场取证。触发词：汉化、汉化补丁、日译中、提取文本、字库补字、碎字、方块字、CPK、ISO 写回、汉化进度报告。
---

# 汉化工作流程

## 概览

把汉化从"凭手感改文件"变成**可复现、可验证、可交接**的工程：

- **按主机平台组织**（PSP / GBA / SFC …），不按引擎组织——决定怎么拆、怎么装回去的是载体约束；
- 一个通用流水线（S0–S9），平台文档只替换"怎么做"；
- 一套校验工具 `scripts/hh.py`，把"改完了"变成可复算的数字；
- 一条铁律：**没验证过的就是没验证过**，不许写成流程。

---

## 先判断两件事

### 1. 目标平台

查 `references/platforms/README.md` 的状态列：

| 状态 | 该怎么办 |
|---|---|
| **S1–S4**（当前只有 PSP） | 读 `references/platforms/psp.md`，**但仍要重新做 S0–S2 识别**：同平台不同游戏，容器组合、操作码、字库网格都可能不同 |
| **S0 占位**（PS1/PS2/PSV/GB/GBA/NDS/3DS/SFC/N64/NGC/Wii/Switch） | 没有平台流程可读。只能执行 `01-pipeline.md` 的通用阶段，每一步现场取证并记录证据类型；**禁止把 PSP 的参数套过去** |

平台文档是空的时候，正确动作是**在新项目里建证据**，而不是补一份"大概是"的文档。

### 2. 当前处于哪一步

| 现状 | 入口 |
|---|---|
| 还没有工程 | `hh.py init` + `references/01-pipeline.md` |
| 容器打不开 / 不确定文本在哪 | `01-pipeline.md` 的 S1–S2 |
| 能改了，怕改坏 | `00-discipline.md` + `hh.py overlay/verify` |
| 中文显示不全、碎字、方块 | `03-font.md` + `hh.py glyphs` |
| UI 还是日文 / 花屏 | `04-images-ui.md` |
| 要发布 | `06-release-repo.md` + `hh.py gate` |

---

## 通用流水线（平台无关的骨架）

```
S0 源准备 → S1 容器解包 → S2 文本转储 → S3 翻译 → S4 排版
→ S5 字库 → S6 图片/UI → S7 重建容器 → S8 写回镜像 → S9 增量修订
```

硬约束（违反必翻车）：

1. **S2 的 id 必须稳定**：`id = sha256(源字节)[:16]`，改原文会让所有批次失联；
2. **S4 必须在 S5 之前**：换行改变字符集合与字库需求；
3. **glyph 别名只追加不重排**，要重排就全量重编码 + 全量回环；
4. **文本与引用必须同源**，用旧引用配新文本会把译文写到错误偏移；
5. **一次只改一类**：文本 / 排版 / 字库 / 图片分开提交、分开报告。

**先做最小闭环**：100 条文本 → 重建 → 写回 → 启动。管线不通，翻得越多亏得越多。

详见 `references/01-pipeline.md`。

---

## 工具：`scripts/hh.py`

零依赖（仅标准库），所有输出不覆盖源资源。

```sh
# 初始化工程：文档 + 数据目录 + 模板
python3 scripts/hh.py init ./my-project --title "某游戏汉化" --platform psp

# 解包树清单（路径 + 大小 + SHA-256 + 树聚合哈希）
python3 scripts/hh.py inventory work/extracted --out data/inventory

# 只含改动文件的变更集 + 校验
python3 scripts/hh.py overlay orig/extracted work/build --out data/overlay
python3 scripts/hh.py verify orig/extracted --overlay data/overlay

# 文本：结构检查 / 统计 / 导入
python3 scripts/hh.py text check --strict-ids
python3 scripts/hh.py text stats
python3 scripts/hh.py text import batch-001.tsv --merge

# 字库容量核算（cols/pages 必须来自实测，或写进 project.json 的 font.grids）
python3 scripts/hh.py glyphs --cols 16 --pages 16 --have glyph-set.json
python3 scripts/hh.py glyphs --grid poem     # 多套字库时按 name 选一套

# 分层进度报告（L1 结构 / L2 语义 / L3 运行时）
python3 scripts/hh.py report

# 发布门槛 + 工程体检
python3 scripts/hh.py gate --level release
python3 scripts/hh.py doctor
```

`text check` 查的是**结构**：控制码是否一致、ruby 是否闭合、id 是否与原文哈希匹配、术语是否候选、行宽是否超限。它**不判断译文好坏**，输出里会明确写这句话。

`init --platform` 传非 PSP 平台时，工具会提示"该平台为 S0 占位，只能走通用阶段"；`doctor` 也会把「平台已验证」列为 WARN 项。

---

## 四条不能破的纪律

1. **证据分级**：E1 运行时观测 > E2 反汇编 > E3 资源字节可复现 > E4 同引擎公开实现 > E5 文档/推测。**E4/E5 只能提假设，不能当结论。**
2. **一次只改一类**：每类一个脚本、一次提交、一份含输入/输出哈希的报告。
3. **分层验证**：L1 结构通过 ≠ 译文正确；L2 读过一部分 ≠ 全量正确；L3 走过一条路径 ≠ 全流程可玩。
4. **诚实进度**：没读过的不勾"已审"，只生成资源不产出产物时报告写 `prepared_only: true`，发布说明不写"完美汉化"。

详见 `references/00-discipline.md`。

---

## 资源索引

| 文件 | 内容 |
|---|---|
| `references/00-discipline.md` | 证据等级、复现、变更隔离、诚实汇报 |
| `references/01-pipeline.md` | S0–S9 阶段表、硬约束、最小闭环、构建报告字段 |
| `references/02-text-layout.md` | 文本真源、控制码、短串清零/长串搬家、行宽 |
| `references/03-font.md` | 网格三参数、补字优先级、别名冻结、渲染、容量 |
| `references/04-images-ui.md` | 纹理容器、矩形、调色板、别名分发、回环 |
| `references/05-quality.md` | L1/L2/L3 分层验证、lane 分片、校对记录 |
| `references/06-release-repo.md` | 变更集、可重建、发布说明、仓库结构 |
| `references/case-fate-extra.md` | 唯一完整案例（PSP），规模/参数/踩坑 |
| `references/platforms/README.md` | 平台状态表与使用规则 |
| `references/platforms/psp.md` | **唯一已验证平台**（S4） |
| `references/platforms/<其他>.md` | **S0 占位**，只有待验证问题清单，无流程 |
| `assets/templates/` | `hh init` 落地的工程模板（AGENT/ROADMAP/CHANGELOG/验收清单/术语表） |

模板里的数值默认留空（`gates.max_line_width = 0`、`font.grids = []`），因为**任何平台的参数都必须实测**，不能拿案例值当默认值。
