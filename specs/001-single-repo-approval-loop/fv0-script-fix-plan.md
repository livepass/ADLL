# FV-0 测试脚本最小修复方案（fv0-script-fix-plan.md）— 仅方案，未实施

**Feature**: ADLL V1.1 — 单仓库任务与 AI 方案审批闭环
**Date**: 2026-10-18 | **性质**: 修复方案与自检测试**设计**文档
（非实施、非执行授权）。
**依据**: [fv0-deviation-register.md](./fv0-deviation-register.md)
（D1/D3）、`99-verdict-corrections.txt`、`99-postcheck.txt`、
`99-adr-c3-impact.md`（DIFF 3 处分类器缺口）。

## 0. 总原则

1. **原 `run-fv0.sh` 为执行证据，不修改、不重新执行**（用户裁定）。
   修复以**后继脚本** `run-fv0-v2.sh` 落地（新建文件），v1 原样保留。
2. **最小修复**：只改缺陷点与其直接依赖，不重构脚本结构、不改各格
   测试语义与预期；每处修复标注缺陷来源（D 编号或更正记录）。
3. 修复后的行为必须可由**合成自检测试（FS1，见 §6）**验证失败即停；
   自检执行**另需授权**。
4. 不降低验证标准、不删除测试格；所有修复仅消除**误判**（假 fail/漏采），
   使自动判定与人工复核结论一致。
5. 预期管理：修复后的脚本重跑结果**不得**用于覆盖或替换本次 FV-0 的
   原始证据；重跑属新的一次验证运行（若授权），独立留证。

## 1. P1 失败即停（D1；最高优先级）

**缺陷**：单格 FAIL 仅写日志后继续（L192-199 等各格同构），违反
fv0-execution-plan.md §8-2。

**最小修复**（新脚本引入格级熔断，每格判定后立即调用）：

```bash
# 新增通用熔断器（最小改动：每格结尾 F<n>_OK 判定后调用，一处逻辑多格复用）
cell_verdict() { # $1=格名(F1..F9|DIFF), $2=OK=pass|fail|skipped, $3=原因
  log "$1 = $2${3:+($3)}"
  if [ "$2" = "fail" ]; then
    log "STOP = fail-stop triggered by $1（§8-2；后续格不再执行）"
    find -P "$ROOT" -mindepth 1 | sort > "$EVID/99-inventory.txt" 2>&1
    log "CLEANUP = skipped(首轮保留 fixtures/evidence；清理须单独授权)"
    log "RUN_END_UTC = $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    exit 3   # 专用退出码 3 = fail-stop（区别于 1=ABORT 越界、0=正常收尾）
  fi
}
```

- 各格末尾的 `log "F<n> = ..."` 全部替换为 `cell_verdict "F<n>" "$F<n>_OK" "$F<n>_REASON"`。
- `DIFF` 同样经 `cell_verdict`（DIFF fail 也触发熔断）。
- `skipped` 不触发熔断（如 P2 环境不支持跳 F2、F1 未过跳 F9）。
- **REAL-REPO after 存证与 inventory 在熔断路径仍必须执行**（如上
  STOP 块内已含 inventory；after-status 亦应先于 exit——即熔断器内
  先做 `99-adll-status-after` 再收尾，保证任何退出路径都有真实仓库
  前后对照证据）。实现时熔断器内顺序：
  ①after-status + diff → ②inventory → ③summary 收尾行 → ④exit 3。
- 失败格的证据（该格输出文件）在熔断**之前**已写盘，保留完整。

**验收标准**：FS1 自检（§6）触发后，`99-summary.txt` 止于失败格 +
STOP 行；失败格之后不存在任何新格证据文件；exit code = 3。

## 2. P2 F3 多行 LFS 指针比较错误（判定更正记录）

**缺陷**：`case "$PTR" in "version https://git-lfs.github.com/spec/v1")`
以**单行字面量**匹配**多行**指针文本（三行：version/oid/size），永不
相等 → 假 fail。

**最小修复**（改为完整三行精确比较，或等价的行序比较）：

```bash
PTR="$(git -C "$F3" archive --format=tar HEAD | tar -xOf - big.bin)"
EXPECTED_PTR="$(printf 'version https://git-lfs.github.com/spec/v1\noid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\nsize 12345\n')"
# 用「去尾随换行后字符串相等」或 printf 双方写临时文件后 diff -u
if [ "$PTR" = "$EXPECTED_PTR" ] || diff <(printf '%s\n' "$PTR") <(printf '%s\n' "$EXPECTED_PTR") >/dev/null 2>&1; then
  F3_OK=pass; F3_REASON="pointer preserved verbatim (3-line match), no smudge (…)"
else
  F3_OK=fail; F3_REASON="archive content differs from expected pointer text"
fi
```

- 比较基准与 fixture 创建时写入 `big.bin` 的期望指针**同源**
 （同一 printf 生成，避免两处手工文本漂移）。
- 保留对照证据：expected/`git show`/`tar -xOf` 三段全文仍写入
  `F3-lfs-pointer.txt`（与 99-postcheck 中复核方法一致）。

**验收标准**：同内容指针判 pass；篡改任一行（如改 size）判 fail。

## 3. P3 F4 子模块空目录占位误判（判定更正记录）

**缺陷**：`tar -tf` 中 gitlink 路径存在**空目录占位条目**
`mods/child/`（size 0），`grep -q 'mods/child'` 命中占位条目 → 误判
"子模块内容已包含" → 假 fail。人工复核确认内容级不含（c.txt 计数 0）。

**最小修复**（区分「目录占位条目」与「子模块内容条目」）：

```bash
# 失败判定改为内容级：归档内出现任何 mods/child/ 之下的普通文件即 fail
CONTENT_LEAK="$(git -C "$FP" archive --format=tar HEAD | tar -tf - \
  | grep -E '^mods/child/.+' | grep -v '/$' || true)"
# 目录占位（trailing slash 条目）单独记录为发现，不算内容泄漏
DIR_PLACEHOLDER="$(git -C "$FP" archive --format=tar HEAD | tar -tf - \
  | grep -E '^mods/child/$' || true)"
if git -C "$FP" ls-tree -r HEAD | grep -q '^160000.*mods/child' \
   && git -C "$FP" archive --format=tar HEAD | tar -tf - | grep -q '^\.gitmodules$' \
   && [ -z "$CONTENT_LEAK" ]; then
  F4_OK=pass; F4_REASON="gitlink in ls-tree, .gitmodules archived, submodule content absent (dir placeholder: ${DIR_PLACEHOLDER:-none}); file:// stayed inside fixtures"
else
  F4_OK=fail; F4_REASON="archive/tree mismatch or submodule content leaked into archive (leaked: $CONTENT_LEAK)"
fi
```

- `.gitmodules` 匹配改为**精确行首锚定**（`^\.gitmodules$`），避免子串
  误命中。
- 空目录占位条目作为**行为发现**写入证据（`mods/child/` size 0），
  与 99-adr-c3-impact.md 发现 3 一致——记录而非误判。

**验收标准**：含占位无内容 → pass；在子模块内追加提交使 `mods/child/c.txt`
进入归档 → fail 且原因含 leaked 条目名。

## 4. P4 DIFF 差异分类器规则缺口（3 处）

**缺陷**（人工复核归类时发现；导致 DIFF 假 fail）：

| # | 缺口 | 后果 |
|---|---|---|
| a | 归档侧 tar **目录头条目**（如 `docs/`、`mods/`，带尾随斜杠）不在 `ls-tree -r --name-only` 中，未设归类规则 | `> docs/` 一律落入「未归类」 |
| b | gitlink 的**空目录占位**（`mods/child/`）无归类规则（同 P3 成因） | `> mods/child/` 落入「未归类」 |
| c | export-ignore 判定只对**文件自身** `check-attr`；目录属性（`secret/ export-ignore`）递归剔除子树时，子文件 `secret/key.txt` 的 check-attr 返回 `unspecified` | `secret/key.txt` 落入「未归类」 |

**最小修复**（do_diff 归类分支增补三条规则，其余不动）：

```bash
# 「> name」（archive 有 / tree 无）分支前置两条规则：
#   ① 以 '/' 结尾 → tar 目录占位/目录头条目（预期）
#   ② 去尾斜杠后与 ls-tree 中 160000 gitlink 路径一致 → submodule 空目录占位（预期）
# 「< name」（tree 有 / archive 无）分支的 export-ignore 判定升级：
#   对 name 及其各级父目录逐级 check-attr export-ignore（父目录 set 即递归剔除，预期）
ea_parent_set() { # $1=repo, $2=path → 若自身或任一父目录 export-ignore=set 则返回 0
  local p="$2"
  while [ -n "$p" ]; do
    [ "$(git -C "$1" check-attr export-ignore -- "$p" 2>/dev/null | awk -F': ' '{print $3}')" = "set" ] && return 0
    p="${p%/*}"; [ "$p" = "$2" ] && break
  done
  return 1
}
```

- 归类语义表述同步到 classified.txt：
  - `docs/ = tar 目录头条目（预期）`
  - `mods/child/ = submodule 空目录占位（预期）`
  - `secret/key.txt = export-ignore 剔除（父目录属性递归，预期）`
- **未归类仍 = 失败判定**（不放宽）；分类器只补已证实的合法形态。
- 内容级 export-subst 归类保持现状（F7diff 已有规则）。

**验收标准**：对全部既有 fixture 重跑 DIFF，unclassified_count=0；
人为放入一个无规则可解释的差异（如临时多一个普通文件）→ 仍 fail。

## 5. P5 F5 悬空符号链接检查遗漏（D3）

**缺陷**：`[ -e "$F5/$lk" ]` 对**悬空**链接（escape.link →
`../../escape.txt` 不存在）返回假 → 该链接目标字符串漏入对照记录。

**最小修复**（存在性判断改为「链接本身」语义）：

```bash
for lk in inside.link escape.link; do
  [ -L "$F5/$lk" ] || [ -e "$F5/$lk" ] || continue   # -L 判链接本身存在，不跟随
  … # 后续 cat-file/readlink 对照不变
done
```

- 或直接以 `git ls-tree HEAD` 中 mode 120000 条目为遍历来源
  （更稳：不依赖文件系统链接创建成功与否，逐条目对照）。
- 逃逸链接目标**内容**仍「未验证」（不解包、不跟随），只补记目标
  **字符串**。

**验收标准**：对照记录含两条链接的目标字符串；人为悬空的链接不再漏采。

## 6. FS1 失败即停自检测试（设计；合成、故意触发 FAIL；执行须授权）

**目的**：验证 P1 熔断器真实生效——任一格 FAIL 后立即停止，后续格
零执行。这是对 D1 修复的**回归验证**，独立于 F1～F9 矩阵。

**性质**：故意制造**合法失败**（预期判定 = fail），验证的是**停止
行为**而非 Git 行为。此失败是测试预期的一部分，不构成"验证失败"。

### 6.1 合成设计

| 项 | 内容 |
|---|---|
| 名称 | FS1-failstop |
| fixture | `fz-failstop/`：`git init` + 单文件 `ok.txt` 一次提交（复用现有 ginit/gcommit 语义） |
| 注入方式 | 在 v2 脚本矩阵中新增独立格 FS1（位于 F1 之后、F2 之前），仅在环境变量 `ADLL_FV0_SELFTEST=1` 时启用；正常验证运行不含此格 |
| 故意失败断言 | FS1 内构造**必然不等**的比较：`[ "$(git -C "$FZ" rev-parse HEAD)" = "0000…0" ]`（或等价：期望值写死为不可能的哈希）→ 判定 `FS1 = fail(selftest: deliberate mismatch)`，经 `cell_verdict` 触发熔断 |
| 为何不用真实缺陷注入 | 不修改/污染 F1～F9 语义；自检失败独立、可开关、零副作用混入 |

### 6.2 预期行为（通过标准）

1. `99-summary.txt` 含 `FS1 = fail(selftest: deliberate mismatch)` 与
   `STOP = fail-stop triggered by FS1`；
2. **F2 及其后所有格的证据文件不存在**（F1 证据存在——FS1 之前已执行；
   或按开关设计把 FS1 置于首位，则任何 F 格证据均不存在——推荐置于
   F1 之后以同时验证"已执行格保留、未执行格零产物"两面）；
3. 退出码 = 3；
4. `99-adll-status-after` + diff、`99-inventory.txt` 存在（熔断路径
   也留真实仓库对照证据）；
5. 写入全部位于执行根内（assert_in_root 常规保证）；
6. 无清理动作（fixtures 保留）。

### 6.3 失败判定（自检不通过 = P1 修复不合格）

- FS1 fail 后仍产生 F2+ 证据文件；或退出码 ≠ 3；或无 STOP 行；
  或缺 after-status/inventory。

### 6.4 执行约束（届时仍适用）

- 独立执行根/独立 evidence 目录（不与 FV-0 档案混存）；零网络、
  零安装、零 AI 调用；不触碰真实仓库写面；执行**须用户单独授权**；
  失败即停自检通过后，若需对 F1～F9 全矩阵重跑验证 P2～P5，同样
  **另行授权、独立留证**，不得覆盖 FV-0 原始档案。

## 7. 修复实施步骤（待授权后执行）

1. 新建 `run-fv0-v2.sh`（v1 原样保留为证据）；按 P1→P5 顺序最小修改；
   FS1 格以 `ADLL_FV0_SELFTEST` 开关挂入。
2. 静态自查：diff v1/v2 仅含本文档所列改动点。
3. 先执行 FS1 自检（§6）；通过后视授权情况决定是否全矩阵重跑。
4. 新运行独立留证；结论回填 research 时标注运行编号，与 FV-0 档案
   并存不覆盖。

## 8. 禁止事项（不变）

不得修改/重执行 run-fv0.sh；不得删除或覆盖 FV-0 原始证据（含全部
原始 fail 判定行）；不得降低验证标准或删格；本方案执行另需人工授权；
不进入 FV-1～7 / /speckit-tasks / /speckit-implement。
