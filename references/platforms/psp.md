# 平台：PSP（唯一已验证平台）

> **验证状态：S4（可交付）——有可运行 ISO、变更集与分层验收记录；关键结论均达 E1–E3。**
> 本文全部内容来自 Fate/Extra 一个项目的实测（见 `references/case-fate-extra.md`）。
> **它是"一个 PSP 游戏"的结论，不是"所有 PSP 游戏"的结论。** 换游戏必须重新走 S0–S2 的识别，
> 尤其不要假设容器组合、操作码、字库网格与本文相同。
>
> 本文不覆盖：PS2、PSV、PS1 及其他主机。那些平台见同目录下的占位文件。

---

## 1. 识别

| 特征 | 位置 | 说明 |
|---|---|---|
| `PSP_GAME/SYSDIR/EBOOT.BIN` | 镜像结构 | PSP 引导程序 |
| `PSP_GAME/USRDIR/*.cpk` | CRI CPK 容器 | 主资源容器 |
| `PARAM.SFO` 的 `DISC_ID` | 版本号（如 `NPJH-50247`） | 区分同游戏不同版本 |

先记录：镜像号、区域、`EBOOT.BIN` 的 SHA-256。**同名游戏的不同版本，字节布局可能不同。**

> 以上三项是 PSP 镜像的通用结构；**CPK 内部的具体条目组织、压缩方式、文本所在的字节码格式，均需逐游戏确认。**

---

## 2. 文本真源：沿操作码找指针

不要扫可打印字节。正确做法是解析场景字节码里的文本指令：

| 类型 | 典型操作码（Fate/Extra） | 说明 |
|---|---|---|
| 对话 | `0x3926` | 指向字符串的指针 |
| 回想 | `0x1530` | 同上 |
| 章节卡 / 动画文本 | `0x0126` | **不插换行**，否则改变动画布局 |
| 选项 / UI 标签 | 未逐类确认 | 不要假设与对话同一套 |

产物：

- `text.jsonl`：`id / jp / zh_cn / file / offset / kinds`
- `refs.jsonl`：`id / file / text_offset / pointer_offsets / kinds`

`pointer_offsets` 是回写唯一依据。同一 ID 可能被多处引用，**每个引用都要改**。

---

## 3. 容器与格式（Fate/Extra 实测）

### CPK

- TOC 记录 `FileID / FileOffset / FileSize / ExtractSize`；ETOC 为扩展表。
- 重建按 `AbsoluteOffset` 排序，**2,048 字节对齐**，回填 TOC 与头部 `EtocOffset / ContentSize`。
- **不要重建 ETOC**：规格未完整验证时只能原样搬运、只改偏移。

### PAK / TXB

- 头部：`count / flags / sizes / align`；带路径的变体在 payload 前有 64 字节名字区。
- 重写时保持字段顺序；只改长度表、不写名字会导致条目错位。

### CMP

- IECP LZSS 压缩。重压后必须能被自己的解压器读回。

### DAT

- 场景字节码；末尾按 16 字节对齐。

### ISO9660

- 写回要同时更新目录记录 `extent / size` 与 PVD 卷大小（`+80 / +84`）。
- 文件名大小写敏感：游戏按小写查找时，大写会导致"找不到资源"。

---

## 4. 工具

| 用途 | 说明 |
|---|---|
| 解包/打包 | 自研 Python（推荐，可复现、可审计） |
| 交叉验证 | 第三方 CPK 工具（需自行获取并遵守许可，本 skill 不分发） |
| 测试 | PPSSPP（快速回归）/ 实机（最终验收） |
| 取证 | 十六进制编辑器、反汇编器 |

原则：**第三方工具只用于交叉验证，不作为构建链的一环**——它们的版本差异会破坏可复现性。

---

## 5. 标准流程

```sh
# S1 解包
python3 scripts/pipeline/extract.py extract <镜像>/PSP_GAME/USRDIR/data.cpk --output work/extracted

# S2 转储
python3 scripts/pipeline/dump_text.py work/extracted/packages --output work/translation/text.jsonl \
  --references work/translation/refs.jsonl

# S3 翻译（批次合并）
python3 scripts/hh.py text import batch-001.tsv --merge
python3 scripts/hh.py text check --strict-ids

# S4 排版
python3 scripts/pipeline/fix_layout.py --max-width 24

# S5 补字（先排版后补字）
python3 scripts/pipeline/patch_font.py --glyph-map work/translation/glyph-map.json

# S6 压缩到运行时上限
python3 scripts/pipeline/compact_font.py --max-glyphs 4096

# S7 重建
python3 scripts/pipeline/build.py --output-cpk work/build/data.cpk

# S8 写回
python3 scripts/pipeline/embed_cpk.py --source-iso <原盘> --cpk work/build/data.cpk \
  --output-iso work/build/game_cn.iso --allow-volume-growth

# S9 校验与报告
python3 scripts/hh.py overlay work/extracted work/build --out data/overlay
python3 scripts/hh.py verify work/extracted --overlay data/overlay
```

`scripts/pipeline/*` 指项目自建的流水线脚本（`hh init` 后由项目自行实现）。本 skill 只提供 `hh.py`
（通用校验）与流程约束，不分发具体游戏的提取/重建脚本。

---

## 6. 平台陷阱（Fate/Extra 实测）

| 症状 | 根因 | 修法 |
|---|---|---|
| 中文只显示前几个字，后面拖日文残字 | 短串未清整槽 | 新串 + 全零填满原槽（含原 NUL） |
| 改一句，另一场景还是日文 | 同一 ID 多处引用只改了一处 | 遍历该 ID 的全部 `pointer_offsets` |
| 某句崩溃 | 追加后指针算错 / 未对齐 | 记录 `new_offset`、写完回填、16 字节对齐 |
| 译文写到错误位置 | 文本表与引用不同源 | 同轮生成；增量修订先比旧字节 |
| CPK 变大后黑屏 | 卷未增长 / PVD 未更新 | `--allow-volume-growth`，更新 `+80/+84` |
| 重建后偏移全错 | 只改内容没重写 TOC/ETOC | 按绝对偏移重排，2,048 对齐，回填 |
| 未变更资源被旧版顶回 | 从旧解包目录重打包 | 未变更成员从源 CPK 直接拷原始字节 |
| 诗文碎成偏旁 | 用 16×16 重建，运行时按 14×14 采样 | 各套字库用自己的格参数 |
| 某章节仍是日文 | 资源在 CPK 里有多份副本 | 按哈希找全部副本统一替换 |

---

## 7. 验收门槛

- [ ] CPK 条目数与源一致，可被自己的解析器完整读出
- [ ] 未变更成员逐字节相同
- [ ] 字库字符集覆盖，未超运行时索引上限
- [ ] 写回后文件名大小写正确
- [ ] PPSSPP：新游戏 → 第一场战斗无崩溃
- [ ] 实机：至少一条完整路径
- [ ] 变更集 `verify` 通过，报告含输入/输出哈希

> 案例数据见 `references/case-fate-extra.md`。那里的数字是该校验过的实测值，可作为规模与耗时的参照，**不要当成通用常量**。
