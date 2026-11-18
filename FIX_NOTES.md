# 日批补账事故修复说明

## 根因

1. `publication/replay.py` 未做真实重放。旧实现按列累积"曾出现的读值"域：某笔事务的旧值只要各自在列域中出现过即视为可生效，不要求全部旧值在同一表状态同时成立，也不检查事务间的顺序可行性；日终读值落入列域即判封存成功。因此第一批中互斥的 A（x 0→1）、D（x 0→2）被同时签发成功回执。各事务"刚提交时的表状态"由列域按位置拼接（`_positional_samples`），并非任何真实重放到达过的状态。
2. `review/projection.py` 把每列取值域做笛卡尔积，而不是投影实际同表共现的整表状态，于是第二批复核报出从未同时出现的读值（如 `(0,1,1)`、`(2,2,0)`）。

## 修复

- `evaluate_replay` 改为全量重放计算：在 (整表状态, 已用事务掩码) 上，从日初表前向扩展（旧值同时匹配才整笔应用），并从日终表后向逆向恢复；存在完整重放当且仅当日终态在使用全部事务后前向可达，否则 `seal_day` 照旧抛 `DAY_REPLAY_MISMATCH`，不新增成果或成功回执。每笔事务的固定证据取"前向可达、提交后状态又能后向到达日终"的全部提交后整表状态，去重排序——即所有完整重放中该事务刚提交时的同表状态。证据内部表示与版本 1 交班件格式、校验、绑定、失败回滚均未改动。
- `project_joint_rows` 改为按请求列序（保留重复列）投影每条固定状态，整元组去重后按整数元组字典序排列。

接口、运行入口、原测试全部保留；新增 `tests/test_replay_regressions.py` 四项回归（互斥拒签且无残留、等待旧值还原的链式顺序、各事务联合态仅来自完整重放、拒签与后到更正不影响旧成果及交班件字节）。

## 实际验证

- `python3 -B incident.py`：退出码 0。seal 案例实际为 `DAY_REPLAY_MISMATCH` 且 `sealed_days`、`successful_receipts` 均为 0；review 案例在线与断源重开均得 `[(0,0,0),(0,0,1),(1,1,1),(2,2,1)]`，重复键 `(w,x,w)` 得 `[(0,0,0),(1,0,1),(1,1,1),(1,2,1)]`。
- `python3 -B -m unittest discover -s tests -v`（核验入口）：34 项全部通过，含原 30 项回归（此前失败的 `test_no_common_replay`、`test_joint_rows_remain_correlated_online_and_after_handoff`、`test_only_completable_prefixes_contribute_at_named_receipt` 均恢复通过）及新增 4 项回归。
- `python3 -B demo.py`（演示入口）：封存、导出、导入、后到修订、关闭源库并重开隔离库后，M 提交后的 `(x,y)` 为 `[(0, 0), (1, 1)]`。
