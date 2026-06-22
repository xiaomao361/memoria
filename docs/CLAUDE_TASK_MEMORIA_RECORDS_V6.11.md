# Claude 开发任务：Memoria v6.11 流水记录

> 日期：2026-06-22
>
> 项目：`/Users/zhouwei/Documents/ClaraCore/skills/memoria`
>
> 目标版本：`v6.11.0`
>
> 背景文档：`docs/MEMORIA_RECORDS_V6.11_SEED.md`

## 一、任务目标

在 Memoria 内增加一套独立的流水记录能力，用来可靠保存锻炼、饮食、睡眠等高频时序事实。

第一版必须完成一个闭环：

1. Agent 写入一条锻炼记录。
2. 系统确认记录已经真正落库。
3. 可以按用户、类型和时间查回原记录。
4. 可以汇总一段时间内的步数、时长、距离等数字。
5. 重复提交同一条记录不会生成两份数据。

这是 Memoria 的新增能力，不是新的项目，也不是给现有记忆增加一个 `kind`。

## 二、必须保持的边界

### 2.1 流水和记忆分开

流水记录不得进入：

- `store/*.md`
- ChromaDB 向量索引
- FTS 记忆搜索
- `recall()`
- importance 计算
- dormant、merge、conflict 等记忆维护流程
- 现有记忆图谱和标签

现有 `store()`、`recall()`、重建、归档、标签和 Web 页面行为不能改变。

### 2.2 共用 Memoria 运行环境

流水记录应当：

- 使用现有 `MEMORIA_ROOT`。
- 使用现有 `memoria.db`。
- 通过现有 CLI、HTTP API 和 MCP 入口提供能力。
- 将业务规则集中在 Python 核心模块，三个入口只做参数转换，不能各写一套逻辑。

### 2.3 第一版只增和查

第一版不实现：

- 修改记录
- 删除记录
- 独立前端页面
- 饮食、睡眠等完整模板
- 自动生成长期记忆
- 真正的时序数据库
- 每种类型一张专用表
- 复杂统计表达式

发现错误记录时，第一版允许追加一条新的正确记录；修改和作废机制留到后续版本。

## 三、数据设计

在 `memoria/db.py` 的初始化流程中新增一张 `records` 表。不要另建数据库。

建议字段如下：

| 字段 | 要求 |
|------|------|
| `id` | 系统生成的唯一 ID |
| `user_id` | 必填，不能默认为空；所有查询必须按用户隔离 |
| `record_type` | 必填；第一版正式支持 `fitness` |
| `occurred_at` | 必填，事件实际发生时间，必须带时区 |
| `local_date` | 由发生时间和时区计算出的本地日期，用于“今天”和按天统计 |
| `timezone` | 必填，默认可使用 `Asia/Shanghai` |
| `data_json` | 必填，必须是 JSON 对象，不能是普通文本或数组 |
| `schema_version` | 必填，第一版为 `1` |
| `note` | 可选的人类备注，不参与数字统计 |
| `source` | 来源，例如 `manual`、`clara`、`codex` |
| `source_agent` | 可选，写入记录的 Agent |
| `source_run_id` | 可选，来源会话或运行标识 |
| `dedupe_key` | 可选的防重复标识 |
| `created_at` | 系统写入时间 |

必须建立以下查询保障：

- 用户、类型、发生时间的组合查询。
- 用户、本地日期的查询。
- 当 `dedupe_key` 存在时，同一用户和类型下不得重复。

同一个 `dedupe_key` 被再次提交时，不要报内部错误，也不要新建记录。返回已有记录，并明确返回结果是“已存在”。

`records` 是流水的真实数据来源。现有“Markdown 是唯一真实来源”的说法只继续适用于记忆，文档中必须明确区分。`maintain rebuild` 不能删除或重建 `records`。

## 四、结构化字段规则

新增独立模块，例如 `memoria/records.py`，集中处理：

- 写入
- 查询
- 汇总
- 时间和时区校验
- JSON 校验
- 类型字段校验
- 防重复

不要把这些逻辑堆进现有 `core.py`。

### 4.1 通用规则

- `user_id` 和 `record_type` 去掉首尾空格后不能为空。
- `occurred_at` 必须是合法时间，并明确包含时区。
- `data` 必须是对象。
- `schema_version` 必须是大于等于 1 的整数。
- 返回数据时将 `data_json` 还原成对象，不把 JSON 字符串直接交给调用方。
- 时间范围查询使用“开始时间包含、结束时间不包含”，避免相邻日期重复。
- 默认按发生时间从新到旧排列；相同时间用写入时间和 ID 保证顺序稳定。
- `limit` 必须有合理上限，`offset` 不能为负数。
- 不接受调用方直接拼接查询语句或 JSON 路径。

### 4.2 `fitness` 第一版模板

`record_type=fitness`、`schema_version=1` 时，允许以下字段：

| 字段 | 类型和单位 |
|------|------------|
| `activity` | 字符串，例如步行、跑步、凯格尔 |
| `steps` | 非负整数，步 |
| `duration_minutes` | 非负数字，分钟 |
| `distance_km` | 非负数字，公里 |
| `repetitions` | 非负整数，次 |
| `sets` | 非负整数，组 |
| `completed` | 布尔值 |

要求：

- 至少提供一个有效字段。
- 数字不能为负数。
- 整数字段不能接受小数或布尔值。
- 未声明字段应返回清楚的错误，避免拼写错误被静默保存。
- `note` 放在公共字段，不要混入 `data`。

类型规则应采用可扩展的注册方式。以后增加 `diet` 或 `sleep` 时，只增加类型规则，不修改 `records` 表。

## 五、核心能力

核心模块至少提供三个公开函数，命名可以按项目习惯调整，但职责必须清楚。

### 5.1 新增记录

输入：

- 用户
- 类型
- 发生时间
- 时区
- 结构化数据
- 版本
- 备注和来源信息
- 可选防重复标识

输出至少包含：

- `id`
- `status`：`created` 或 `exists`
- 完整记录

写入完成后必须从数据库读回一次再返回。不能只因为执行了写入语句就宣称“记好了”。

### 5.2 查询记录

支持：

- 必填 `user_id`
- 可选 `record_type`
- 可选开始和结束时间
- 可选 `local_date`
- 分页

查询必须始终限制在指定用户内。没有 `user_id` 时应直接拒绝。

### 5.3 锻炼汇总

第一版只要求对 `fitness` 提供固定汇总，不做任意字段和任意表达式。

返回：

- 记录条数
- 有记录的天数
- 总步数
- 总锻炼分钟
- 总距离
- 总次数
- 总组数
- 时间范围

缺少某个字段的记录按零处理。无数据时返回零值和空结果，不报错。

汇总只读取 `fitness` 第一版允许的数字字段，不从 `note` 中猜数字。

## 六、三个入口

### 6.1 CLI

新增一级命令 `record`，包含：

```bash
conda run -n zhouwei python cli.py record add \
  --user-id zhouwei \
  --type fitness \
  --occurred-at 2026-06-21T20:00:00+08:00 \
  --timezone Asia/Shanghai \
  --data '{"activity":"步行","steps":16000,"duration_minutes":90}' \
  --dedupe-key fitness-zhouwei-2026-06-21
```

```bash
conda run -n zhouwei python cli.py record query \
  --user-id zhouwei \
  --type fitness \
  --from 2026-06-01T00:00:00+08:00 \
  --to 2026-07-01T00:00:00+08:00
```

```bash
conda run -n zhouwei python cli.py record summary \
  --user-id zhouwei \
  --type fitness \
  --from 2026-06-01T00:00:00+08:00 \
  --to 2026-07-01T00:00:00+08:00
```

错误输入必须返回非零退出码和可理解的错误信息。

### 6.2 HTTP API

新增：

- `POST /api/records`
- `GET /api/records`
- `GET /api/records/summary`

参数和核心规则保持一致。校验错误返回客户端错误，不能统一变成服务器内部错误。

### 6.3 MCP

在现有 8 个工具之外新增：

- `memoria_record_add`
- `memoria_record_query`
- `memoria_record_summary`

MCP 只包装核心函数。工具说明必须明确：

- 流水不是长期记忆。
- `user_id` 必填。
- `data` 是对象。
- 时间必须带时区。

更新 MCP 烟雾测试，实际完成初始化、列出工具、写入、重复写入、查询和汇总。

## 七、版本和文档

完成实现后统一更新：

- `memoria/__init__.py`：`6.10.0` → `6.11.0`
- `server/app.py`
- `server/mcp.py`
- `README.md`
- `SKILL.md`
- `docs/ARCHITECTURE.md`
- 版本历史

文档必须明确：

- 记忆和流水的边界。
- Markdown 只是真正记忆的来源；流水以 SQLite 为准。
- `maintain rebuild` 不影响流水。
- CLI、HTTP API、MCP 的真实调用示例。
- 第一版只有 `fitness` 完整模板。

不要改项目名称，不要把整个产品重新定位为“个人数据平台”，因此版本为 `v6.11.0`，不是 `v7.0`。

## 八、测试要求

项目当前没有正式测试目录。本次新增 `tests/`，使用项目现有 Python 环境可直接运行的测试方式，不要为了测试引入大型框架。

所有测试必须使用临时 `MEMORIA_ROOT`，不能读写真实的：

`/Users/zhouwei/.claracore/memoria`

至少覆盖：

1. 首次初始化自动创建 `records` 表和索引。
2. 合法锻炼记录写入成功并能原样查回。
3. 写入后确实能从 SQLite 读回。
4. 相同防重复标识重复提交，只保留一条。
5. 不同用户的数据互相不可见。
6. 按类型查询正确。
7. 按开始和结束时间查询边界正确。
8. 按本地日期查询正确。
9. 分页和排序稳定。
10. 汇总步数、时长、距离、次数和组数正确。
11. 无记录汇总返回零值。
12. 普通文本、数组和损坏 JSON 被拒绝。
13. 时间不带时区被拒绝。
14. 负数、整数小数、未知字段被拒绝。
15. 现有记忆写入、召回、删除、恢复功能不受影响。
16. `maintain rebuild` 后流水仍然存在。
17. CLI 三个命令使用真实输入跑通。
18. HTTP 三个接口使用临时数据跑通。
19. MCP 三个新工具通过真实 stdio 会话跑通。

建议验证命令：

```bash
conda run -n zhouwei python -m unittest discover -s tests -v
```

除此之外，必须实际执行一次完整闭环：

1. 在临时目录写入 2026-06-20、2026-06-21 两天的锻炼。
2. 重复提交其中一天。
3. 查询确认只有两条。
4. 汇总确认步数和时长正确。
5. 执行一次现有记忆的写入、召回和清理。
6. 通过 MCP 再查一次锻炼汇总。

## 九、完成标准

只有同时满足以下条件才算完成：

- 新增、查询、汇总闭环真实跑通。
- 重复提交不会产生重复记录。
- 用户隔离和时间边界测试通过。
- 流水不会进入记忆召回、向量、文件和维护流程。
- 现有 Memoria 功能回归测试通过。
- CLI、HTTP API、MCP 三个入口行为一致。
- 所有版本号和文档已同步。
- 没有写入或污染真实个人数据。
- `git diff` 中没有无关改动。

## 十、交付说明

完成后请在回复中只说明：

1. 做了什么。
2. 实际跑过哪些测试。
3. 测试结果。
4. 是否还有未完成项。
5. 改动的提交号。

不要只交代码或只说“已完成”。如果真实流程没跑通，继续修复和重测。
