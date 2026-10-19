# 文本：提取、翻译、排版、回写

文本是最容易"看起来做完"的一层。这里的每一步都要能复算。

---

## 1. 找文本真源：沿引用找，不要扫可打印字节

引擎里的字符串通常有两类：

| 类型 | 是否要翻译 | 怎么找 |
|---|---|---|
| 被指令/字段引用的字符串 | ✅ 要 | 沿操作码或序列化字段找指针/索引 |
| 常量池、哈希键、资源路径、着色器名 | ❌ 不要 | 出现在非文本表结构中 |

扫可打印字节会把资源路径、变量名、调试串全扫进来，翻完必然崩。

做法：

1. 定位文本指令（对话、菜单、选项、道具描述各有不同操作码）；
2. 记录**指针所在偏移**和**字符串所在偏移**，两者都要；
3. 只导出被引用且长度合理的串；
4. 人工抽 20 条与游戏内文本对照，确认没漏、没多。

`refs.jsonl` 至少包含：

```json
{"id":"3f2a…","file":"000016/field/016/0000.dat","text_offset":69080,
 "pointer_offsets":[69076],"kinds":["dialogue"]}
```

`pointer_offsets` 是回写的唯一依据——**同一句在多处引用时，每一处都要改**。

---

## 2. 稳定 ID

```
id = sha256(源字符串字节)[:16]
```

- 用**源字节**，不用解码后的 Unicode；编码不同字节不同。
- 位置无关：重打包、换文件、乱序合并都不影响。
- 复用自动合并：同一句在多文件出现，只占一行。

改提取规则（去空白、改解码、改截断）会改 ID。变更前做兼容对照：

```sh
# 新旧转储各取 1000 条，比较 id 交集
python3 - <<'PY'
import json
a={json.loads(l)['id'] for l in open('old.jsonl',encoding='utf-8')}
b={json.loads(l)['id'] for l in open('new.jsonl',encoding='utf-8')}
print('old',len(a),'new',len(b),'common',len(a&b))
PY
```

交集明显小于总数，说明规则变了，必须保留旧 ID 映射。

---

## 3. 文本表结构

```json
{"id":"3f2a9c1d4e5b6a70","jp":"原文","zh_cn":"译文",
 "file":"000016/field/016/0000.dat","offset":69080,"kinds":["dialogue"]}
```

- `jp` **不可变**（改它等于换 ID）。
- `zh_cn` 空字符串表示未翻译，不要填占位符。
- `kinds` 决定排版策略（对话 / 选项 / 名称 / 动画卡 / UI）。

---

## 4. 分批翻译

- 每批约 100 条，按源文件与偏移切分，保证同场景连续；
- 批次只写 `{id, zh_cn}`；
- 合并脚本默认**不覆盖**已有译文，替换必须显式 `--overwrite`；
- 批次可乱序合并，合并后按 `file + offset` 排序再校对。

用 `hh.py` 导入：

```sh
python3 scripts/hh.py text import batch-001.tsv --format tsv --merge
python3 scripts/hh.py text check
python3 scripts/hh.py text stats
```

---

## 5. 翻译准则（语义层）

必须：

- 先读上下文（按 `file + text_offset` 排序），再动笔；
- 保留全部控制码与占位符；
- 保留分支与称谓差异；
- 术语以 `glossary.csv` 为准；
- 修正写 `id / zh_cn / reason`，不直接改主表。

禁止：

- 把 `しか…ない` 译成肯定；
- 把 `じゃないか` 译成否定陈述；
- 把普通读音硬贴到中文正文；
- 为"通顺"删掉颜色/分支/控件码；
- 编造原文没有的机制、数字、专名。

高频陷阱见 [05-quality.md](05-quality.md) 的语义表。

---

## 6. 排版：独立的一遍

换行不是翻译的一部分，是**独立阶段**。

规则：

- 只对会走文本框排版的类型插换行（对话、回想、选项说明）；
- **动画/逐字显示的文本不插换行**，否则改变动画布局；
- 标点不出现在行首（行首禁则）；
- 控制码不参与宽度计算；
- 全角计 2、半角计 1；
- 行宽上限写进 `project.json` 的 `gates.max_line_width`。

```sh
python3 scripts/hh.py text check --max-width 24
```

顺序必须是：**排版 → 补字**。反过来会漏字（换行改变了字符集合）。

---

## 7. 回写：短串覆盖与长串搬家

### 7.1 短串：整槽清零再写

新串 ≤ 原串时，不要只覆盖前几个字节：

```python
slot = len(old_bytes) + 1          # 含原 NUL
data[o:o+slot] = new + b"\0" * (slot - len(new))
```

原因：部分渲染器按**存储字符数**读取，不按 NUL 停止。不清零会露出旧字尾部。

### 7.2 长串：搬到末尾并回填所有指针

```python
new_offset = len(data)
data += new + b"\0"
for p in ref["pointer_offsets"]:
    struct.pack_into("<I", data, p, new_offset)
# 文件末尾按 16 字节对齐
```

要点：

- 先记录 `new_offset`，写完再回填；
- 每个 `pointer_offsets` 都改，不能只改第一个；
- 对齐按目标容器要求（常见 4/16 字节）；
- 回填后用自己的解析器重读，确认指针落在字符串起始。

### 7.3 增量修订的额外保护

对已有产物做定点替换时，先验证旧字节：

```python
expect = old_text.encode(encoding)     # 用旧译文反向编码
assert data[o:o+len(expect)] == expect, f"旧字节不符 @{o}"
```

不符立即中止——说明基线不是你以为的那一版。

---

## 8. 验证

```sh
# 结构：可编码、控制码、ruby、id
python3 scripts/hh.py text check --strict-ids

# 覆盖与分文件统计
python3 scripts/hh.py text stats

# 读回抽检：从产物中解出 20 条，与文本表比对
```

编码验证（以 CP932 为例）：

```python
s = ''.join(glyph_map.get(c, c) for c in zh)
s.encode('cp932')     # 失败即缺字或字符不可映射
```

结论措辞：

- "控制码 0 错误、可编码 0 失败" = L1；
- "已读 1,452 条，修正 138 条" = L2；
- "开场到第一场战斗无崩溃" = L3。

三者不可互相替代。
