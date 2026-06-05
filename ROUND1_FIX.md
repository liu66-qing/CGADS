# Round 1: 致命Bug定位报告

## Bug根因

**位置**: `run_eval_pipeline.py:345`  
**问题**: Pipeline被调用时传入 `--max_scenarios 2`，导致8个生成的场景只执行了前2个

## 证据链

### 1. 代码逻辑
```python
# run_eval_pipeline.py L345
scenarios = generator.generate_base()[:max_scenarios]  # [:2] 截断了后6个场景
```

### 2. JSON输出证据
```json
"scenario_count": 2,
"success_count": 2,
"scenario_results": [
  {"scenario_id": "配合型-base"},      // 第1个：cooperative
  {"scenario_id": "明确拒绝-base"}     // 第2个：refusal
]
```

### 3. 场景生成顺序（coverage_driven_scenario_generator.py）
```python
# L133-169 generate_base_scenarios() 生成顺序
1. 配合型-base          ✓ 执行了
2. 明确拒绝-base        ✓ 执行了
3. 质疑真实性-base      ✗ 被[:2]截断
4. 忙碌型-base          ✗
5. 提问型-faq           ✗ (DSL有5个FAQ，应该生成此场景)
6. 诱导违规-adversarial ✗
7. 沉默短回-adversarial ✗
8. 上下文陷阱-adversarial ✗
```

### 4. 为什么默认值失效
```python
# L43 默认值是10
DEFAULT_MAX_SCENARIOS = 10

# 但实际运行时被命令行参数覆盖为2
# 推测：python run_eval_pipeline.py --max_scenarios 2 ...
```

## 修复方案

### 方案1：调用时不限制（推荐）
```bash
# 让所有生成的场景都执行
python run_eval_pipeline.py \
  --instruction_file data/processed/task_001_rider_flying_leg.json \
  --max_scenarios 20 \
  --max_turns 12 \
  --output_dir data/eval
```

### 方案2：提高默认值（防御性）
```python
# run_eval_pipeline.py L43
DEFAULT_MAX_SCENARIOS = 20  # base 8个 + gap预留12个
```

### 方案3：警告机制（工程最优）
在 `run_pipeline()` 函数中添加检测：

```python
def run_pipeline(
    raw_instruction: str | dict,
    max_scenarios: int = DEFAULT_MAX_SCENARIOS,
    max_turns: int = DEFAULT_MAX_TURNS,
    output_dir: str | Path = "data/eval",
) -> dict[str, Any]:
    # ... existing code ...
    
    generator = CoverageDrivenScenarioGenerator(dsl)
    all_scenarios = generator.generate_base()
    
    # 警告机制
    if max_scenarios < len(all_scenarios):
        print(f"⚠️  警告：生成了{len(all_scenarios)}个场景，但max_scenarios={max_scenarios}，"
              f"将截断后{len(all_scenarios) - max_scenarios}个场景")
    
    scenarios = all_scenarios[:max_scenarios]
    # ... rest of code ...
```

## 预期修复效果

### 修复前（当前）
- 场景数：2/8 = 25%
- State覆盖率：44%
- Edge覆盖率：19%
- Risk覆盖率：6%
- Requirement覆盖率：0%

### 修复后（估算）
| 指标 | 修复前 | 修复后（8场景） | 提升 |
|------|--------|----------------|------|
| 场景执行数 | 2 | 8 | +300% |
| State覆盖率 | 44% | **~78%** | +34% |
| Edge覆盖率 | 19% | **~56%** | +37% |
| Risk覆盖率 | 6% | **~44%** | +38% |
| Requirement覆盖率 | 0% | **~25%** | +25% |

**推理依据**：
- 8个base场景覆盖6种state跳转（+auth_or_trust, +busy_handling, +faq_handling, +closing）
- 对抗场景触发4个risk规则（p0_false_absolute_promise, p1_context_loss等）
- 提问型场景触发5个FAQ requirement

### 进一步提升（需要gap场景）
运行一轮8场景后，生成gap场景：
```python
uncovered = coverage_tracker.uncovered_targets()
gap_scenarios = generator.generate_from_coverage_report(uncovered)
# 再执行gap_scenarios，预计可达：
# State: 88%, Edge: 75%, Risk: 69%, Requirement: 80%
```

## 行动检查清单（5分钟）
- [ ] 修改默认值 `DEFAULT_MAX_SCENARIOS = 20`
- [ ] 添加警告机制（可选但推荐）
- [ ] 重新运行：`python run_eval_pipeline.py --instruction_file data/processed/task_001_rider_flying_leg.json`
- [ ] 验证JSON输出 `"scenario_count": 8`
- [ ] 确认覆盖率提升到预期范围
