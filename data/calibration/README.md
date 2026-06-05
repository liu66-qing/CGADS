# Gold Standard Calibration Dataset v1

当前文件是完整 30 条金标校准对话集，覆盖两类外呼任务、多类用户画像，以及 PASS、CAPPED_P1、FAIL_P0 三类判定。

## 文件

- `gold_standard_v1.jsonl`: 金标对话集，每行一个 JSON case。
- `validate.py`: JSONL 合法性、schema、turn 证据、P0/P1 rule_id 与分布校验脚本。
- `stats.json`: 当前草案统计与最终目标分布。

## 当前统计

- 总数：30
- PASS：10
- CAPPED_P1：12
- FAIL_P0：8
- 任务1 `rider_lottery_notify`：15
- 任务2 `course_live_switch`：15
- 边界标记覆盖：`hidden_p1`、`late_exit`、`p0_in_faq`、`multi_p1_no_p0`、`low_dim_no_violation`

## 校验

在本目录运行：

```bash
python validate.py
```

完整数据集使用严格分布校验：

```bash
python validate.py --strict30
```

项目根目录还提供了可导入、可用于 CI 的审计入口，会额外校验 `total_score` 是否严格等于维度加权和 P0/P1 门控结果：

```bash
python run_calibration_audit.py --strict30
python run_calibration_audit.py --strict30 --json
```

## 标注口径

- `total_score` 严格由维度分计算：`raw_weighted = sum(dim_score / 5 * weight)`，权重为 25/20/20/15/10/10。
- P0 一票否决：`total_score = min(raw_weighted, 30)`。
- P1 按数量封顶：1 个 P1 不超过 70，2 个不超过 60，3 个及以上不超过 50。
- 每个 P0/P1 都必须给出真实存在的 `evidence_turn` 和原文证据。
- `state_trace_expected` 记录 assistant turn 输出后的系统状态；用户侧触发事件写入后续 assistant turn 的 slots，例如 `refusal_detected_at_user_turn`。
- `coverage_targets` 只允许 `edge:`、`state:`、`risk:`、`requirement:`、`faq:`、`slot:` 前缀。
- 对抗性元信息写入 `adversarial_traits`，不要混入覆盖率字段。

## 最终目标分布

- PASS：10
- CAPPED_P1：12
- FAIL_P0：8
- 任务1 `rider_lottery_notify`：15
- 任务2 `course_live_switch`：15
