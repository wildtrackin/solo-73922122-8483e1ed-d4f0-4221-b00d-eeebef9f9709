# OCR 修订 · 实体标签迁移工具

语料工程师修订 OCR 文本后，把原文上的实体标签迁移到修订文，供训练使用。
后端 FastAPI + SQLite，前端为单页网页，交付含 Docker Compose 一键启动。

## 快速启动

### Docker（推荐）

```bash
docker compose up --build
# 打开 http://localhost:8000
```

SQLite 数据库落在名为 `appdata` 的卷里（容器内 `/data/app.db`），重启不丢。

### 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt     # 运行只需 requirements.txt
uvicorn app.main:app --reload --port 8000
# 打开 http://localhost:8000
```

### 运行测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

## 使用流程

1. **输入**：粘贴原文、修订文、标签 JSON（或点"填入示例"）。
   约束：每段文本 ≤ 120 个 Unicode 码点；标签 ≤ 10 个、非空、互不重叠，
   区间为原文码点的左闭右开区间 `[start, end)`。
2. **保存并分析**：服务端按最小编辑距离（插/删/换各计 1）枚举全部最优对齐：
   - **自动迁移**：所有最优对齐都保留该标签且落点唯一；
   - **待选择**：有多个落点，或落点唯一但并非所有最优对齐都保留——
     逐项选择落点或丢弃；
   - **无法保留**：任何最优对齐都不能让原跨度字符完整连续地出现，只能丢弃。
3. **确认并生成结果**：整份选择必须被**同一个最优对齐**支持，
   否则拒绝并指出冲突标签；确认成功后才能下载
   `修订文 + 完整标签 JSON`。失败不会留下任何结果。
4. **多窗口安全**：另一窗口修改任一输入后，旧选择与在途确认都会被
   服务端拒绝（409 stale）；把输入改回原样也不会恢复，需要重新选择确认。

标签 JSON 格式（`id` 可省略，自动补 `L1..Ln`）：

```json
{"labels": [{"id": "ent1", "start": 0, "end": 4}]}
```

下载的结果 JSON：

```json
{
  "revised": "修订后文本",
  "labels": [{"id": "ent1", "start": 0, "end": 4, "text": "对应文本"}],
  "meta": {"session_id": "…", "revision": 3, "edit_distance": 2,
           "migrated": 1, "discarded": ["ent2"]}
}
```

## 重复文字示例（examples/）

| 文件 | 场景 | 现象 |
|---|---|---|
| `01_auto.json` | 句尾追加两字 | 两标签落点唯一，自动迁移 |
| `02_repeat_choice.json` | `abcabcabc → abcabc` | 中间那段 `abc` 可落在 `[0,3)` 或 `[3,6)`，需选择 |
| `03_impossible.json` | `银行 → 银号` | 原跨度字符被替换，无法保留，只能丢弃 |
| `04_conflict.json` | `abab → ab` 两个 `ab` 标签 | 各自唯一落点都是 `[0,2)`，同一对齐不可兼得，确认报冲突 |

网页左上角"示例"下拉可一键填入这四组数据。

## 算法说明

设原文 `s`、修订文 `t`，`d1[i][j] = ed(s[:i], t[:j])`，
`d2[i][j] = ed(s[i:], t[j:])`，`D = ed(s, t)`。

- **落点判定**：标签 `[a,b)` 在某最优对齐中完整连续落在 `[p,p+L)`
  ⟺ `t[p:p+L] == s[a:b]` 且 `d1[a][p] + d2[b][p+L] == D`。
  （前缀最优 + 跨度逐字匹配 + 后缀最优，即拼出一个最优对齐。）
- **自动迁移判定**：对最优对齐计数（`c1/c2` 路径计数，大整数），
  保留该标签的对齐数 `Σp c1[a][p]·c2[b][p+L]` 等于总数且落点唯一。
- **联合一致性**：把保留的跨度按源序排列，目标区间必须同序不重叠，
  且各段（前缀/间隙/后缀）最小编辑代价之和等于 `D`；
  冲突时给出目标次序冲突的标签对，或搜索一个极小的不一致标签子集。

正确性由 `tests/test_bruteforce.py` 保证：对小字符串穷举全部最优对齐，
逐跨度对照落点集合、"所有对齐都保留"标志与联合一致性判定。

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions` | 创建会话（三件套），返回分析结果与 `revision` |
| GET | `/api/sessions/{sid}` | 当前输入 + 分析 + 已存选择 + 结果状态 |
| PUT | `/api/sessions/{sid}/inputs` | 修改任一输入：`revision` 必变，旧选择/旧结果同事务清除 |
| PUT | `/api/sessions/{sid}/selections` | 保存选择（整表替换），`revision` 过期返回 409 |
| POST | `/api/sessions/{sid}/confirm` | 事务内校验版本与联合一致性，成功才原子写入结果 |
| GET | `/api/sessions/{sid}/download` | 仅当前 `revision` 已确认成功时可下载 |

错误码：`400` 输入非法；`404` 会话/结果不存在；`409 stale_revision`
输入已被他处修改；`409 conflict` 选择互相冲突（附冲突标签）；
`422 unresolved` 存在未处理的待选标签。

## 目录结构

```
app/
  alignment.py   # 最小编辑距离、落点集合、对齐计数、联合一致性
  main.py        # FastAPI 路由与确认事务
  db.py          # SQLite（sessions / selections / results）
  schemas.py     # 输入校验
  static/        # 单页网页（原生 JS）
tests/           # 单元、API、暴力对照测试
examples/        # 四组示例（含重复文字）
Dockerfile  docker-compose.yml  requirements*.txt
```
