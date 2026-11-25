# 馆藏重名合并核验规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 证据登记 | 检查领域约束 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 分组归并 | 查看业务计算结果 | `POST /api/stages/calculate` | `app/modules/calculate.py` | `tests/test_calculate.py` |
| M4 禁止边复核 | 查看签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信和隔离行 | `POST /api/stages/balance` | `app/modules/reconcile.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |
| M8 跨组互认签发 | 互认冲突传播、更正重算与分组签发 | `GET /recognition、/api/recognition/*` | `app/recognize/` | `tests/test_recognition_*.py` |

## 跨组互认签发规则（M8）

同一批馆藏开馆前签发时，作者记录在组间通过互认关系（`recognize` 事件）连接。规则：

1. **权威冲突**：同一互认连通组件内出现两个不同的非零权威编号即冲突；权威编号 0 表示未确认，不参与判定。组内人数核验合格也不能抵消权威冲突。
2. **冲突传播**：冲突沿互认边传播到第三组，组件内所有组标记 `SUSPENDED` 一并暂缓；与冲突组件无互认关联的合格组保持 `READY`，可以先签。
3. **编号碰巧相同不传播**：不同组的本地作者编号相同但没有互认边时，各属独立组件，互不牵连，各自核验。
4. **更正重算**：晚到的 `revoke`（撤销互认）或权威编号更正入账后整体重算；冲突解除且组内核验仍合格的组恢复 `READY`，可重新签发。撤销为终态，重放旧互认事件不会让其复活。
5. **更正先入账**：`/api/recognition/submissions` 在单事务内先记更正再校验签发；受影响组的既有结论按受影响范围失效，携带旧 `revision` 的请求返回 `STALE_RECOGNITION`。事务原子，签发失败则更正一并回滚。
6. **状态口径**：`READY` 可签、`SUSPENDED` 被冲突牵连暂缓、`HELD` 组内核验不合格（内部问题优先于牵连标记）。
7. **工作台**：编目员在 `/recognition` 查看各组状态、冲突传播链与已签发结论，并登记事件、提交单组或同批签发。

### 互认事件类型

| kind | 字段 | 含义 |
|---|---|---|
| `group` | `group`、`headcount_ok` | 登记分组及组内人数核验结论 |
| `authority` | `group`、`author`、`authority` | 登记本地作者的权威编号（0=未确认） |
| `recognize` | `claim`、`group`、`author`、`peer_group`、`peer_author` | 建立跨组互认关系 |
| `revoke` | `claim` | 撤销指定互认关系（终态） |

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

权威编号 0 表示未确认。先按相同权威编号归并，再按相似度降序、端点升序处理候选边。禁止关系检查跨整个分组，不能经第三人绕过。不同非零权威编号阻止合并。

`sample_data/incoming.csv` 的 0003 组触发预检异常，0004 组触发业务判定。`tests/test_calculate.py` 还核对逐组结论和证据字段。
