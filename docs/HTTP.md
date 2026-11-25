# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批和当前复核状态。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试。

`GET /api/runs/<id>/evidence` 下载内含运行清单、行号隔离、业务证据和复核信息的 JSON。

## 跨组互认签发台（`/recognition`）

`GET /recognition` 返回工作台页面，数据存于独立 SQLite（`RECOGNITION_DB`，默认 `instance/recognition.sqlite3`）。

| 接口 | 说明 |
|---|---|
| `GET /api/recognition` | 查看事件序号、各组状态（`READY`/`SUSPENDED`/`HELD`）、冲突证据与已签发结论 |
| `POST /api/recognition/events` | 入账一批更正事件，体为 `{"events":[...]}`，入账后整体重算 |
| `POST /api/recognition/signoffs` | 单组签发，体为 `{"group","revision","note"}`；不可签返回 409 |
| `POST /api/recognition/submissions` | 同批提交 `{"events":[...],"signoffs":[...]}`，单事务内更正先入账再校验签发 |
| `GET /api/recognition/signoffs` | 列出当前有效签发结论 |

事件字段见 [DEPTH.md](DEPTH.md) 的「互认事件类型」。冲突码 `GROUP_NOT_RELEASABLE`、`STALE_RECOGNITION` 返回 409；`GROUP_NOT_FOUND`、`CLAIM_NOT_FOUND` 返回 404；字段类错误返回 422。
