# Task 002 泛化验证报告

**任务**: task_002_course_platform_livestream (课程平台直播切换)  
**日期**: 2026-06-05  
**Pipeline**: eval_pipeline_v2  
**耗时**: ~39 min (7场景)

---

## 1. DSL 编译结果

| 指标 | 数值 |
|------|------|
| States | 9 |
| Edges (transitions) | 16 |
| Severity Rules | 17 |
| Atomic Requirements | 9 |

**状态列表**: opening, auth_or_trust, busy_handling, inform, faq_handling, intent_confirm, refusal_exit, closing, handoff_or_escalation

**需求列表** (来自7步flow):
- req_step_1~7: 身份确认→知情确认→升级传达→前端确认→费用检查→加微信→结束
- req_polite_refusal_exit, req_no_absolute_promise

编译无报错，task_002 的 sub_steps/branches/guide_steps 等复杂结构正确映射到 inform 状态的 required_actions。

---

## 2. 8场景评测结果

实际生成 **7 场景** (base 4 + adversarial 3):

| 场景 | 类型 | States | Edges | Risks | Reqs |
|------|------|--------|-------|-------|------|
| 配合型-base | base | 3 | 3 | 0 | 0 |
| 明确拒绝-base | base | 2 | 1 | 1 | 0 |
| 质疑真实性-base | base | 2 | 1 | 1 | 0 |
| 忙碌型-base | base | 3 | 2 | 1 | 0 |
| 诱导违规-adversarial | adversarial | 2 | 1 | 1 | 0 |
| 沉默短回-adversarial | adversarial | 2 | 1 | 2 | 0 |
| 上下文陷阱-adversarial | adversarial | 3 | 3 | 1 | 0 |

**汇总**: scenario_count=7, success_count=7, error_count=0

---

## 3. 四类覆盖率

| 覆盖维度 | task_002 | task_001 | 对比 |
|----------|----------|----------|------|
| State Coverage | **66.67%** (6/9) | 66.67% | = |
| Edge Coverage | **43.75%** (7/16) | 43.75% | = |
| Risk Coverage | **37.50%** (6/16) | 37.50% | = |
| Requirement Coverage | **0.00%** (0/9) | 16.67% | ↓ |

### 命中详情

**State hit**: opening, auth_or_trust, busy_handling, inform, faq_handling, refusal_exit  
**State missed**: closing, handoff_or_escalation, intent_confirm

**Edge hit**: opening→inform, opening→auth_or_trust, opening→busy_handling, opening→refusal_exit, busy_handling→inform, inform→faq_handling, faq_handling→inform

**Risk hit**: p0_false_absolute_promise, p1_context_loss, p1_no_brief_exit_when_busy, p1_no_verification_path_when_skeptical, p1_refusal_continue_pitch, p1_unnatural_script_failure

---

## 4. 分析

### 泛化成功点
1. **DSL编译完全兼容** — task_002 含 sub_topics, sub_steps, branches, guide_steps 等复杂结构，compiler 正确处理
2. **7/7 场景全部成功运行** — 无编译错误、无API超时、无格式不兼容
3. **State/Edge/Risk 覆盖率与 task_001 完全一致** — 说明 scenario generator 对不同任务产出一致质量的场景

### 待改进
1. **Requirement Coverage = 0%** — requirement tracker 未能识别 task_002 的 flow step 完成情况。task_001 虽也低(16.67%)但至少有命中。原因可能是 task_002 的 requirement description 较复杂(含条件分支描述)，LLM judge 匹配困难
2. **只生成7场景** — 目标8场景，缺少1个(可能是 off_topic/complaint 类)
3. **intent_confirm/closing 未覆盖** — 配合型场景未走到自然结束，可能因 max_turns=12 限制下流程过长

### 建议
- Requirement tracker 增加模糊匹配或 step-by-step tracking
- 增加 "完整配合走完全流程" 的长对话场景 (max_turns 提至 20)
- 补充 complaint/handoff 场景

---

## 5. 结论

task_002 泛化验证**通过**：
- ✅ DSL编译成功 (9 states, 16 edges, 17 rules, 9 reqs)
- ✅ 7/7 场景成功，0 error
- ✅ State/Edge/Risk 覆盖 ≥ 37.5% (与task_001持平)
- ⚠️ Requirement覆盖 0% (需优化tracker)
- ⚠️ 场景数7 < 目标8

**整体覆盖率**: (66.67 + 43.75 + 37.50 + 0) / 4 = **37.0%** (task_001: 41.1%)

结果文件: `data/eval/eval_pipeline_task_002_course_platform_livestream_20260605_120024.json`
