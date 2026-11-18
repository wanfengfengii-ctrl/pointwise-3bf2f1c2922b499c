# 浦岸观测日批账库

白班接收员冻结日初、日终观测表并登记两个离线工位的更正原件。资料员按固定修订号和事务号核账。夜班在隔离库凭原成果号复核同一事务刚提交时的多个测点读值。

## 运行

需要 Python 3.11，使用标准库和 SQLite。从项目根目录运行事故核账、完整原回归及演示。`.pointwise-runtime.json` 中的 `verify` 和 `demo` 指向原回归及演示。

```sh
python3 -B incident.py
python3 -B -m unittest discover -s tests -v
python3 -B demo.py
```

演示用临时源库及隔离库，展示实际封存、导入、后到修订、关闭源库和隔离库重开。示例中北工位 A 同改 x、y，南工位 M 独立改 z。M 可在 A 之前或之后，两个合法联合值是 `[(0, 0), (1, 1)]`。

## Python 接口

调用者持有并关闭 `sqlite3.Connection`。写接口拥有单次提交边界，传入连接须处于空闲事务状态。项目从库的本地路径读写，不依赖网络。不同源库应配置不同的稳定出处标识 `origin`。同一源库重复初始化应传原标识，已有业务数据保留。隔离库重复初始化保留原副本。

| 接口 | 输入与结果 |
| --- | --- |
| `publication.initialize_source(db, origin)` | 建立或重开源库业务结构。已登记出处不可更换。 |
| `snapshots.freeze_table(db, day, source, rows)` | 接收行键到整数的映射，或逐行提供 `ObservationRow`、二元元组或二元列表。返回固定整数修订号。 |
| `snapshots.read_revision(db, revision_id)` | 返回原修订和出处。查无此号返回 `None`。 |
| `corrections.register_sheet(db, day, station, document, transactions)` | 整单登记一个或多个 `CorrectionTransaction(name, changes)`，其中每个 `RowChange(key, old, new)` 描述一行变化。返回 `SheetRecord`。 |
| `corrections.read_sheet(db, sheet_id)` | 按登记号返回原件和事务。查无此号返回 `None`。 |
| `publication.seal_day(db, opening_id, closing_id, transaction_ids)` | 选择两个固定修订及至多十个具名事务，返回 `SealReceipt`。返回后可凭 `receipt.result_id` 读取。 |
| `publication.read_sealed_day(db, result_id)` | 返回同一提交绑定的 `SealedDay` 及回执。 |
| `exchange.export_day(db, result_id)` | 导出版本 1 交班件字节串。 |
| `exchange.initialize_archive(db)` | 建立隔离库。 |
| `exchange.import_day(db, blob)` | 校验并保存固定交班件，返回 `ReceivedCopy`。同内容重送返回同一登记。 |
| `exchange.read_received_day(db, result_id)` | 读取归档副本、出处及固定成果。 |
| `review.audit_after(db, result_id, transaction_id, keys, archive=False)` | 按请求键序返回 `list[tuple[int, ...]]`。在隔离库调用时传 `archive=True`。 |

日号、来源、行键、事务号、工位和原件名为非空 UTF-8 文本，首尾不可带空白，内部不可含 NUL。行键及事务号区分大小写。读数为精确整数，保持原观测单位，允许零、负数和大整数，拒绝缺值、布尔和非整数。每张表的行键唯一，每笔事务至少一行且键唯一。同日事务号唯一，原件可跨日重复使用事务号。表和变化的键顺序对封存无影响。

封存的两端表须同日且键集相同。完整重放从指定日初表开始，每笔所选事务恰使用一次。只有全部旧值同在当前表中匹配，新值才整笔生效。终点须与日终全表一致。零笔事务按两端表相等核账。成功回执与成果同一提交可见。测试夹具 `fail_before_commit=True` 在成果和回执均暂写后、提交前触发 `COMMIT_FAILED`。

成果保存两端固定修订、具名事务及原件出处，并支持在断源后复核。复核只计入能走到指定日终的完整重放，以指定事务刚提交时的同一张表为准。在线和隔离复核保留请求位置和重复键，整元组去重后按整数元组字典序排列。已知事务上的空键请求返回 `[()]`。允许调整证据的内部表示。后续源表更正和隔离库重开不改变已有合法成果。

交班件为 UTF-8 JSON。其版本 1 正文绑定出处、原成果号、成功回执和固定证据，经规范化 JSON 计算 SHA-256。内部读值为精确十六进制文本。隔离库校验完整格式、校验值和成果绑定，并原子比对同号内容。同号异内容时原副本保持可读。校验值用于检测内容损坏，交班件由业务双方在既有可信渠道中传递。

业务拒绝统一抛出 `snapshots.LedgerError`，其 `code` 标记原因。坏表或坏单不会留下部分登记。无完整重放时报 `DAY_REPLAY_MISMATCH`，无新成果或成功回执。未知成果、事务或行键整次查询报错。截断、校验失败、绑定错误和同号异内容都不会更改既有归档。SQLite 打开、锁等待及底层 I/O 错误保留自身异常类型。

## 业务源码与核验

| 工作环节 | 源码 | 原回归 |
| --- | --- | --- |
| 固定日表及历史读取 | `snapshots/` | `tests/test_snapshots.py` |
| 整单接纳及按日选件 | `corrections/` | `tests/test_corrections.py`、`tests/test_publication.py` |
| 完整重放、固定证据及原子发布 | `publication/` | `tests/test_publication.py`、`tests/test_review.py` |
| 导出、完整性校验及不可变归档 | `exchange/` | `tests/test_handoff.py` |
| 在线及断源联合复核 | `review/` | `tests/test_review.py`、`tests/test_handoff.py` |
