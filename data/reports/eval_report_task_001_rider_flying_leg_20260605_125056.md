# 外呼数字人多轮对话评估报告

> 生成时间：2026-06-05T12:50:56
> 评测系统：橙脉CGADS v1.0
> 核心算法：Coverage-Guided Adaptive Dialogue Simulation

## 1. 任务概览

| 项目 | 内容 |
|------|------|
| 任务ID | `task_001_rider_flying_leg` |
| 角色 | 美团外卖骑手的站长 |
| 目标 | 致电飞毛腿骑手，通知合同已成功签署，提醒完成配送任务 |
| 流程步骤 | 5步 |
| FAQ数量 | 5条 |
| 约束条件 | 6条 |
| 字数限制 | 30字 |
| 评测空间 | S=9 E=16 R=16 Q=12 |

## 2. 模拟数据概览

- 模拟场景总数：**8**
- 成功执行：8 | 失败：0
- 总对话轮次：64
- 平均轮次/场景：8.0
- CGADS迭代轮数：2
- 覆盖用户类型：配合型, 上下文陷阱, 忙碌型, 质疑真实性, 诱导违规, 沉默短回, 提问型, 明确拒绝

## 3. 总体评分

### ✅ 总分：76.5 / 100

| 指标 | 值 |
|------|-----|
| 评测状态 | **PASS** |
| P0违规总数 | 0 |
| P1违规总数 | 0 |
| 最低分 | 64.0 |
| 最高分 | 84.0 |

## 4. 分维度评分

| 维度 | 得分 | 满分 | 加权分 | 权重 |
|------|------|------|--------|------|
| 任务完成度 | 3.8/5 | 5 | 19.0/25 | 25% |
| 流程状态遵循 | 3.0/5 | 5 | 12.0/20 | 20% |
| 关键约束遵循 | 4.1/5 | 5 | 16.4/20 | 20% |
| 条件分支处理 | 4.8/5 | 5 | 14.4/15 | 15% |
| 多轮上下文保持 | 4.9/5 | 5 | 9.8/10 | 10% |
| 沟通体验 | 2.6/5 | 5 | 5.2/10 | 10% |
| **合计** | | | **76.8** | **100%** |

## 5. 关键成功点

- ✅ **沉默短回-adversarial**：84.0分，4轮，全流程合规通过，无违规项
- ✅ **上下文陷阱-adversarial**：82.0分，12轮，全流程合规通过，无违规项

## 6. 关键失败点


## 7. 高风险违规项

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'配合型-base' 第2轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'质疑真实性-base' 第2轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'提问型-faq' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'诱导违规-adversarial' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |

### 🟠 length_limit

| 字段 | 内容 |
|------|------|
| 描述 | length_limit |
| 得分 | 3/10 |
| 结果 | failed |
| 证据 | 场景'诱导违规-adversarial' 第1轮触发 |
| 原因 | length_limit |
| 风险等级 | medium |
| 优化建议 | 优化对应话术分支逻辑 |


## 8. 典型失败对话片段

## 9. 用户类型覆盖情况

| 覆盖类型 | 覆盖率 | 已覆盖 | 总数 |
|---------|--------|--------|------|
| 状态 | ⚠️ 67% | 6 | 9 |
| 转移边 | ❌ 44% | 7 | 16 |
| 风险规则 | ❌ 38% | 6 | 16 |
| 业务需求 | ❌ 17% | 2 | 12 |

**评测充分性**：⚠️ 未充分

**未覆盖目标**（前10项）：
- `state:closing`
- `state:handoff_or_escalation`
- `state:refusal_exit`
- `edge:auth_or_trust->inform`
- `edge:auth_or_trust->refusal_exit`
- `edge:busy_handling->closing`
- `edge:busy_handling->inform`
- `edge:faq_handling->intent_confirm`
- `edge:faq_handling->refusal_exit`
- `edge:inform->refusal_exit`

**已覆盖用户画像**：配合型, 上下文陷阱, 忙碌型, 质疑真实性, 诱导违规, 沉默短回, 提问型, 明确拒绝

## 10. 优化建议

### 🟠 建议1：修复length_limit

- **优先级**：P1
- **问题**：触发了P1级违规：length_limit
- **建议**：优化对应话术分支逻辑
- **预期效果**：消除P1封顶，评分上限恢复

### 🟠 建议2：补充未测试的风险场景

- **优先级**：P1
- **问题**：8条风险规则未被测试到
- **建议**：增加针对性用户画像覆盖：risk:p0_bypass_official_channel, risk:p0_impersonation, risk:p0_sensitive_info_request
- **预期效果**：风险覆盖率提升至80%+

### 🟡 建议3：补充未覆盖的流程分支

- **优先级**：P2
- **问题**：9条状态转移边未触发
- **建议**：增加触发场景：edge:auth_or_trust->inform, edge:auth_or_trust->refusal_exit, edge:busy_handling->closing
- **预期效果**：边覆盖率提升至60%+

---

*本报告由橙脉CGADS系统自动生成，每个评分均可追溯到具体对话轮次与规则ID。*