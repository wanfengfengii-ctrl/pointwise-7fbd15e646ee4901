# 联丰热处理炉次观测湖

设备按班次导出炉次观测。早班档案员登记固定源修订，白班质控员选取争议炉次，夜班可在设备与工作库关闭后读取交接文件。日结更正产生新的固定修订，历史包继续供复核。

使用 Python 3.11 标准库。在项目根目录运行以下命令。演示与回归使用各自的临时目录。

```sh
python3 -B handoff.py verify
python3 -B handoff.py demo
python3 -B -m unittest discover -s tests -t .
```

## 设备申报和交接文件

`samples/shift-batch.json` 是可直接传给 `register` 的申报对象。`batch_id` 和 `revision` 是非空文本，共同标识一次申报。`rows` 是按 `row_number` 严格递增的列表，行号可以不连续。举例来说，`{"row_number":108,"trays":[[{},{}],[],null]}` 描述一行炉次。第一只托盘有两个实际测点，第二只托盘已报送且为空，第三只托盘缺报。行的 `trays` 也可以为 `null` 或 `[]`，分别表示托盘清单缺报和已报送空清单。每个 `{}` 在形状中占一个实际槽，两列都缺值的测点也占槽。空清单、空托盘及缺报均占零槽。

`temperature` 与 `pressure` 各自保存 `[正间隔, 整数读值]` 的列表。每列从虚拟槽 −1 独立起算。零是有值读数。每项按设备自己的整数刻度记录，复核原样返回，缺值为 `None`。窗口按原列表位置使用零基左闭右开索引。发布后原行号不变，两条带均改用各自的包内槽坐标。

版本 1 包为 UTF-8 JSON 对象，包含 `version`、`revision_id`、`start`、`stop`、`rows`、`temperature`、`pressure`。`start` 和 `stop` 描述源行位置窗口，`rows` 长度等于窗口宽度。`samples/window-package.json` 是可直接离线读取的手填合法包。样例源的原行 101 有温度 41，窗口 `[1,2)` 只含原行 108。包中压力 9 位于槽 0，温度 7 位于槽 1，复核顺序为 `(None, 9)`、`(7, None)`，其后保留空托盘与缺报托盘。

## Python 接口

`catalog.schema.open_catalog(path)` 打开工作库。`handoff.initialize(db)` 初始化持久结构，可重复调用并保留原记录。使用由 `open_catalog` 返回的连接，入口调用时连接应处于空闲状态，调用者负责关闭连接。登记、停用和发布各自管理写事务。

| 入口 | 成功结果 | 拒绝情形 |
| --- | --- | --- |
| `intake.register.register(db, submission)` | 固定修订号 | `SubmissionInputError` 或 `RegistrationValidationError` 表示申报非法。`RevisionConflict` 表示已有同名申报的内容不同。 |
| `publish.window.publish_window(db, revision_id, start, stop)` | `(package_id, PublicationReceipt)`，回执绑定修订号、行窗口和包号 | `SourceNotFound`、`SourceUnavailable`、`InvalidWindow`、`PackageBuildError` 或 `PublicationCommitError`。本次包和回执无新增。 |
| `archive.export.fetch_package(db, package_id)` | 原包字节 | 未知号引发 `PackageNotFound`。 |
| `review.read.read_package(payload)` | 有序的 `ReviewResult`，逐炉次、托盘、测点返回原行和两列读值 | `PackageValidationError`，整包拒收。 |
| `catalog.lifecycle.retire_source(db, revision_id)` | 原固定修订号，可重复调用 | 未知号引发 `SourceNotFound`。 |

`archive.export.write_package` 接收打开的二进制输出流，写入原字节并返回字节数。`catalog.history.current_revision` 可查某日批的当前修订，发布始终使用调用方指定的固定号。登记更正保留原修订的供给状态，直到对该固定号执行停用。成功发布的包在更正、停用以及重开后仍按原号交付原字节。

```python
import json
from contextlib import closing
from pathlib import Path

from archive.export import fetch_package
from catalog.schema import open_catalog
from handoff import initialize
from intake.register import register
from publish.window import publish_window
from review.read import read_package

submission = json.loads(Path("samples/shift-batch.json").read_text(encoding="utf-8"))
with closing(open_catalog(":memory:")) as db:
    initialize(db)
    revision_id = register(db, submission)
    package_id, receipt = publish_window(db, revision_id, 1, 2)
    payload = fetch_package(db, package_id)
result = read_package(payload)
```
