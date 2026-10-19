# hanhua-workflow

主机游戏汉化的**流程标准 + 校验工具**，封装成可被 AI 代理直接调用的 skill。

> 核心原则：**没验证过就是没验证过。**
> 这里只有一套经过完整实测的流程（PSP / Fate/Extra），其余平台一律留占位，只写"要验证什么"，不写"大概是怎样"。

---

## 它解决什么问题

汉化工程最容易烂在三件事上：改坏了不知道、改完了说不清、换个人接不上。

这套东西把流程钉成三根柱子：

1. **固定阶段** S0–S9（源准备 → 解包 → 转储 → 翻译 → 排版 → 字库 → 图片 → 重建 → 写回 → 增量修订），阶段与平台无关；
2. **可复算的校验**：清单哈希、变更集、文本结构、字库容量、发布门槛，全部输出数字而不是"看起来没问题"；
3. **分层诚实汇报**：L1 结构 / L2 语义 / L3 运行时，通过一层只说一层。

---

## 平台支持：按主机划分，不按引擎

决定"怎么拆、怎么装回去"的是载体约束，不是游戏用了什么引擎。所以平台文档按主机组织。

| 平台 | 状态 | 说明 |
|---|---|---|
| **PSP** | **S4 可交付** | 唯一验证过的平台。基于 Fate/Extra：CRI CPK + PAK/CMP + 自研字节码 |
| PS1 / PS2 / PSV | S0 占位 | 无样本 |
| GB / GBC / GBA / NDS / 3DS | S0 占位 | 无样本 |
| SFC / N64 / NGC / Wii / Switch | S0 占位 | 无样本 |

状态刻度：`S0 占位 → S1 单点 → S2 可解析 → S3 可复现 → S4 可交付`。

**S0 的文档里没有任何流程步骤和参数**，只有解除占位所需的条件和待验证问题清单。想解除占位，需要一个真实项目走完最小闭环并留下证据（inventory + overlay verify + L3 运行记录）。

引擎/中间件（CRI、IECP 等）只作为平台文档内的一个字段记录，不单独开专题——同一引擎在不同主机上的产物结构并不相同。

---

## 快速开始

```sh
# 1. 装成 skill（软链，改源文件即生效）
ln -sfn "$PWD" ~/.workbuddy/skills/hanhua-workflow

# 2. 初始化一个汉化工程
python3 scripts/hh.py init ./my-project --title "某游戏汉化" --platform psp

# 3. 解包树清单
python3 scripts/hh.py inventory work/extracted --out data/inventory

# 4. 变更集与校验
python3 scripts/hh.py overlay orig/extracted work/build --out data/overlay
python3 scripts/hh.py verify orig/extracted --overlay data/overlay

# 5. 文本结构检查 / 字库容量 / 分层报告 / 发布门槛
python3 scripts/hh.py text check --strict-ids
python3 scripts/hh.py glyphs --grid body
python3 scripts/hh.py report
python3 scripts/hh.py gate --level release
```

`hh.py` 只依赖 Python 标准库（3.9+），所有输出写独立目录，不覆盖源资源。

---

## 工具能力

| 子命令 | 作用 | 关键约束 |
|---|---|---|
| `init` | 生成工程骨架（AGENT/ROADMAP/CHANGELOG/术语表/验收清单/project.json） | 非 PSP 平台会提示"只能走通用阶段" |
| `inventory` | 路径 + 大小 + SHA-256 + 树聚合哈希 | 用于证明"我拿到的就是这一份" |
| `overlay` | 只含改动文件的变更集 | 输出目录不得位于源树内；超量中止 |
| `verify` | 校验变更集与源树对应关系 | 源哈希变了就中止 |
| `text check` | 控制码一致性、ruby 闭合、id 哈希、术语候选、行宽 | **只查结构，不判断译文好坏** |
| `text import` | TSV/CSV/JSONL 合并导入 | 按 id 去重，保留既有字段 |
| `glyphs` | 字符集覆盖与字库容量 | **cols/pages 必须实测**，无默认值 |
| `report` | L1/L2/L3 分层进度报告 | 覆盖率≠正确率，报告里写明 |
| `gate` | 发布门槛 | 缺变更集或 L3 记录直接拦下 |
| `doctor` | 工程体检 | 平台未经证实时给 WARN |

---

## 目录结构

```
SKILL.md                     技能入口：决策树 → 流水线 → 工具 → 纪律
references/
  00-discipline.md           证据等级、复现、变更隔离、诚实汇报
  01-pipeline.md             S0–S9 阶段表、硬约束、最小闭环、报告字段
  02-text-layout.md          文本真源、控制码、短串清零/长串搬家、行宽
  03-font.md                 网格三参数、补字优先级、别名冻结、渲染
  04-images-ui.md            纹理容器、矩形、调色板、别名分发、回环
  05-quality.md              L1/L2/L3 分层验证、lane 分片
  06-release-repo.md         变更集、可重建、发布说明
  case-fate-extra.md         唯一完整案例（PSP）的规模与踩坑
  platforms/README.md        平台状态表与使用规则
  platforms/psp.md           唯一已验证平台（S4）
  platforms/<其他>.md        12 个 S0 占位
scripts/hh.py                校验工具 CLI
scripts/validate_skill.py    仓库自检：结构 + 占位文档不得含未验证流程
assets/templates/            hh init 落地的工程模板
```

---

## 仓库自检

```sh
python3 scripts/validate_skill.py
```

检查三件事：

1. `SKILL.md` 的 frontmatter 完整；
2. **S0 占位文档里没有流程痕迹**——出现「标准流程」小节、可执行命令块、具体脚本调用或 `0x` 操作码即报错；
3. README 的平台表与 `platforms/` 目录一致。

CI（`.github/workflows/validate.yml`）在每次 push 时跑结构检查、语法检查与 CLI 冒烟（含"`glyphs` 无实测网格必须拒绝"的反向断言）。

---

## 贡献规则

想给某个平台补流程，必须同时满足：

1. 一个真实项目完成 S0–S8 最小闭环；
2. `data/inventory/summary.json`（真实条目数 + tree_sha256）；
3. `data/overlay/manifest.json` 且 `hh.py verify` 通过；
4. 一条 L3 运行时记录（哪个模拟器/实机、走到哪个场景）。

缺证据的 PR 会被要求降级为占位。**写"应该是这样"比留空更有害**——它会误导下一个接手的人。

---

## 边界

- 仓库**不含**任何游戏 ROM、镜像、原版资源或译文原文，只有流程、脚本与模板；
- 不分发第三方解包/打包工具，只建议用于交叉验证；
- `hh.py` 不实现具体游戏的提取与重建，那部分由各项目自行实现（因为每个游戏的容器组合都不同）。

## License

MIT，见 [LICENSE](LICENSE)。
