# 🍊 橙脉 CGADS · 外呼指令状态机试炼场

> Coverage-Guided Adaptive Dialogue Simulation for Explainable Outbound-Call Evaluation

![橙脉CGADS](./assets/banner.png)

**任务指令 → 状态机编译 → 覆盖率驱动模拟 → 合规评测 → 证据链报告**

同等预算下覆盖率+25%，P0风险发现率翻倍。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置API
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

# 3. 启动后端
uvicorn backend.api:app --host 0.0.0.0 --port 8000

# 4. 启动前端
cd frontend && npm install && npm run dev

# 5. 或使用Gradio Demo
python -X utf8 app.py
```

## 系统架构

```
任务指令 → 指令解析 → DSL编译(9状态16边) → CGADS覆盖率驱动场景生成
    → 三层用户模拟(Persona+行为采样+状态转移)
    → 多轮对话执行 + Runtime状态追踪
    → 规则检查(P0/P1 hard gate) + Reasoning-First LLM Judge
    → 合规门槛 + 维度加权评分
    → 证据链可解释报告
```

## 核心创新：CGADS算法

**问题**：传统评测随机模拟用户，无法保证覆盖关键风险分支。

**方案**：将外呼任务编译为状态机，定义4类覆盖准则，用覆盖率缺口反向驱动场景生成。

```python
# CGADS 闭环
Round 1: warmup scenarios → coverage 44%
→ gaps: [edge:opening→auth_or_trust, risk:p0_false_promise, ...]
Round 2: targeted scenarios → coverage 72%
→ new findings: 1 P1 (refusal_continue_pitch)
```

**效果**：同等预算下覆盖率+25%，P0发现率翻倍。

## 项目结构

```
├── src/
│   ├── dsl/                    # DSL核心（schema/compiler/state_tracker/coverage）
│   ├── evaluators/             # 评测器（cgads/llm_judge/user_simulator/scenario_gen）
│   ├── checkers/               # 规则检查（severity_rules/auto_checker）
│   ├── calibration/            # 校准（30条金标/audit）
│   ├── report/                 # 报告生成
│   ├── instruction_parser/     # 指令解析
│   └── visualization/          # 可视化（mermaid/plotly）
├── backend/                    # FastAPI SSE后端
├── frontend/                   # React前端
├── data/
│   ├── processed/              # 已解析任务配置
│   ├── calibration/            # 30条金标校准集
│   └── eval/                   # 评测结果
├── experiments/                # 消融实验
├── tests/                      # 测试
├── run_eval_pipeline.py        # E2E Pipeline入口
├── 系统设计方案.md              # 完整设计文档
└── 作品简介.md                  # 作品简介
```

## API文档

### POST /api/evaluate

SSE流式评测接口。

```json
{
  "instruction": "# Role\n你是美团外卖骑手的站长...",
  "budget": 8,
  "warmup_ratio": 0.5,
  "max_turns": 10
}
```

返回SSE事件流：`stage_start` → `stage_complete` → `coverage_update` → `pipeline_complete`

### GET /api/examples

返回示例任务列表。

### GET /api/health

健康检查。

## 评测指标

| 维度 | 权重 | 评测方式 |
|------|------|---------|
| 任务完成度 | 25% | LLM Judge |
| 流程遵循 | 20% | 状态机+规则 |
| 约束合规 | 20% | 规则检查 |
| 分支处理 | 15% | LLM Judge |
| 上下文一致 | 10% | LLM Judge |
| 沟通体验 | 10% | LLM Judge |

合规门槛：P0一票否决(≤30分) | P1封顶(1个≤70/2个≤60/3个≤50)

## 参考文献

- IFEval (arXiv:2311.07911) — 可验证约束
- G-Eval (arXiv:2303.16634) — LLM Judge with CoT
- Prometheus (arXiv:2310.08491) — Rubric judge
- MultiChallenge (arXiv:2501.17399) — 多轮评测
- ConvLab-2 (ACL 2020) — 对话状态追踪
- Anthropic Eval Best Practices — Reasoning-first judge

## License

MIT
