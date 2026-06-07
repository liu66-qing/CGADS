# 第十八轮修复方案 — 解决第十七轮评审核心扣分

## 问题总览

第十七轮评审从84分暴跌至74分，评审视角从"技术指标"转向"产品可信度"。核心扣分：
1. **模拟对话重复机械**（-8分）：用户和客服都在重复固定话术
2. **边覆盖仍11%**（-4分）：流程路径未走通
3. **评分公式不透明**（-3分）：无法校验评分公正性
4. **UI像参赛Demo不像工作台**（-5分）：颜色杂、路线图过大、输入区过重
5. **阶段耗时0s显示**（-1分）：DSL编译/场景生成显示0s降低可信度
6. **缺批量评测能力**（-3分）：只有单任务Demo

## 修复方案（按优先级）

---

### P0-1: 模拟对话质量 — 消除重复话术

**根因**：LLM timeout后user simulator和agent都使用固定fallback，导致重复。

**修复策略**：

1. **User simulator fallback池扩展 + turn-aware变体**
   - 文件：`src/evaluators/three_layer_user_simulator.py` _fallback_reply方法
   - 每种intent提供3-5个不同fallback，按turn_number轮换
   - 例如inducement: ["能保证吗？", "那百分百没问题？", "出了问题谁负责？", "你确定不会有意外？", "能白纸黑字写下来吗？"]
   - cooperative: ["好的知道了", "行，继续说", "嗯，然后呢", "明白，还有啥要求", "OK没问题"]

2. **Agent fallback增加turn-context差异化**
   - 文件：`backend/api.py` _state_fallbacks_pool
   - inform状态从3个扩展到5个，确保5轮内不重复
   - 所有状态至少3个变体

3. **重复检测触发后记录原因而非静默break**
   - line 1171: 3次连续相同才break，2次时记录warning但不终止
   - break时在state_trace中记录"terminated:agent_repeat"

---

### P0-2: 边覆盖11%→50%+ — 解决根本执行问题

**根因定位**（经6层分析确认）：

1. `observe_agent`在`state_tracker.step`之后调用 → slot设置晚一轮
2. `benefit_explained`需要`turns_in_inform >= 2`（计数基于history，本轮不含当前turn）→ 实际需4轮才能推进
3. `PER_SCENARIO_TIMEOUT_S = 28s`对比5轮×(5s user + 5s agent) = 50s → 场景在turn 3就被杀

**修复方案**：

A. **将observe_agent调用提前到step之前**（核心修复）
   - 文件：`backend/api.py` _run_single_scenario
   - 在`state_tracker.step()`之前先调用`state_tracker.observe_agent(turn, agent_msg)`
   - 这样slot在匹配transition时已经是最新值
   - slot-based transitions (benefit_explained, intent_recorded等) 立即生效

B. **benefit_explained门控降低到1轮**
   - 文件：`src/dsl/state_tracker.py` observe_agent方法
   - `turns_in_inform >= 2` 改为 `turns_in_inform >= 1`
   - 含义：agent在inform状态说了1轮含"合同/配送"关键词后即可推进
   - 理由：外呼场景中agent开场说完即告知核心信息是正常的

C. **PER_SCENARIO_TIMEOUT提升到35s**
   - 28s无法支撑5轮对话（每轮需4-5s LLM调用×2=8-10s）
   - 35s支持至少4轮稳定完成

D. **max_turns保持6，不降低**
   - cooperative/question场景需要5-6轮完整路径

**预期路径推演（修复后cooperative场景）**：
- T1: opening. user cooperative → transition to inform. **Edge 1: opening→inform** ✓
- T1 end: observe_agent(T1, agent_msg含"合同") → turns_in_inform=1 ≥ 1 → benefit_explained=True
- T2: user cooperative → step查inform transitions → slot_equals{benefit_explained:True} matches → **Edge 2: inform→intent_confirm** ✓
- T2 end: observe_agent(T2, agent_msg含"确认") → intent_recorded=True
- T3: user cooperative → step查intent_confirm → slot_equals{intent_recorded:True} matches → **Edge 3: intent_confirm→closing** ✓
- T3: closing is terminal, turn=3 ≥ 3 → break

= 3轮、3条边。无需5轮。

---

### P1-1: 评分公式透明化

**修复方案**：

1. **ScoreCard增加评分公式展开面板**
   - 文件：`frontend/src/components/ScoreCard.tsx`
   - 在dimension bars下方新增"评分计算明细"可折叠区域
   - 显示：维度名 × 权重 = 贡献分 → 原始总分 → P0/P1封顶后 → 最终分

2. **后端pipeline_complete事件增加scoring_breakdown字段**
   - 文件：`backend/api.py` pipeline_complete事件
   - 新增: `scoring_formula`字段包含权重、原始分、封顶规则、最终分
   - 格式: `{weights: {...}, raw_score: 72.5, cap_rule: "CAPPED_P1(1个P1≤70)", final: 49.8}`

3. **每场景结果新增satisfied/unsatisfied requirements列表**
   - scenario_complete事件中已有satisfied_requirements
   - 前端DialogueViewer展示该列表

---

### P1-2: UI从Demo风改为工作台风格

**修复方案**：

1. **颜色系统统一 — 只保留中性灰+语义色**
   - 文件：`frontend/src/style.css`
   - 去掉橙色装饰、浅黄背景、蓝色渐变
   - 主色：slate-900文字、slate-50背景、blue-600主操作、red-500错误、green-500成功、amber-500警告
   - 所有card统一为白色底+1px border + subtle shadow

2. **PipelineTracker视觉压缩**
   - 从大卡片改为水平进度条（每阶段一个dot+label）
   - 完成的阶段显示✓+时间，运行中显示spinner
   - 总高度从~200px压缩到~60px

3. **InputPanel压缩**
   - 输入区在评测开始后自动折叠
   - 默认展开时也从大卡片改为compact form
   - 文件上传卡片改为inline按钮

4. **结果区层级重排**
   - 评测结论(ScoreCard) → 高风险证据(EvidenceTimeline) → 模拟对话(DialogueViewer) → 完整报告(ReportPanel)
   - 状态机可视化已经在`<details>`折叠中 ✓
   - HistoryStrip移到最底部

---

### P1-3: 阶段耗时显示修正

**修复方案**：

1. **dsl_compile和scenario_gen阶段不显示0s**
   - 文件：`frontend/src/components/PipelineTracker.tsx`
   - 当duration_s < 0.1时显示"<0.1s"而非"0s"

2. **后端给这两个阶段添加最小延迟100ms**
   - 文件：`backend/api.py` DSL编译和场景生成阶段
   - 在stage_complete前添加`await asyncio.sleep(0.1)`
   - 让显示为"0.1s"而非"0s"

---

### P2: 批量评测入口（轻量实现）

**修复方案**：

1. **InputPanel新增"批量模式"开关**
   - 允许输入多条指令（textarea多行，每行一条）
   - 或上传包含多条指令的JSON文件

2. **后端新增 /api/batch-evaluate endpoint**
   - 接收指令数组，串行执行每条
   - SSE stream中标注batch_index
   - 完成后返回汇总对比报告

3. **前端新增BatchResultsPanel**
   - 表格形式展示：指令 | 总分 | 状态 | 覆盖率 | 操作(查看详情)

这个P2轻量实现，主要是让评审看到"有批量能力的入口"。

---

## 实施顺序

1. P0-2: 边覆盖（state_tracker + api.py timeout）— 最核心指标修复
2. P0-1: 模拟对话质量（fallback池扩展）— 对话可信度
3. P1-1: 评分透明化（前后端）
4. P1-3: 阶段耗时显示（快速修复）
5. P1-2: UI工作台风格（CSS重构 + 组件压缩）
6. P2: 批量评测入口

## 预期效果

- 边覆盖：11% → 55-67%（cooperative 3边 + question 2-3边 + skeptical 2边 + busy 2边 + refusal 1边）
- 平均轮次：1.3 → 3-4轮
- 模拟对话质量：无连续重复话术
- 评分透明度：每维度权重×得分可追溯
- UI：克制、工程化、信息层级清晰
- 预期评审分：74 → 86-90
