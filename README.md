<p align="center">
  <img src="./assets/banner.png" alt="橙脉CGADS" width="100%"/>
</p>

<h1 align="center">橙脉 CGADS · AI数字人外呼多轮对话评测系统</h1>

<p align="center">
  <strong>美团 AI Hackathon 2026 · 命题赛道二</strong><br/>
  <em>复杂指令下的多轮对话指令遵循评测 — 从"给个分"到"给个可信的、可执行的、可验证的答案"</em><br/>
  <strong>团队：对对队</strong>
</p>

<p align="center">
  <a href="http://139.196.183.227/">🌐 在线体验(国内)</a> ·
  <a href="https://diligent-eagerness-production-14ff.up.railway.app/">🌐 在线体验(海外)</a> ·
  <a href="./docs/项目文档.md">📄 项目文档</a> ·
  <a href="./docs/系统设计方案.md">📐 系统设计</a> ·
  <a href="./docs/作品简介.md">📋 作品简介</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/状态覆盖-100%25-brightgreen" alt="state"/>
  <img src="https://img.shields.io/badge/边覆盖-83%25-green" alt="edge"/>
  <img src="https://img.shields.io/badge/风险覆盖-80%25+-blue" alt="risk"/>
  <img src="https://img.shields.io/badge/需求覆盖-90%25-blueviolet" alt="req"/>
  <img src="https://img.shields.io/badge/P0误判率-↓90%25-red" alt="p0"/>
  <img src="https://img.shields.io/badge/评测耗时-3~4min-yellow" alt="time"/>
</p>

---

## 💡 一句话理解本系统

> **别人的系统告诉你"数字人得了72分"。**
> **我们的系统告诉你"为什么得72分、哪个Turn扣的、扣在什么规则上、怎么改、改完能到多少分、这个结论能不能信"。**

---

## 🎯 赛题深度理解

赛题不是要我们"做一个能打分的工具"。

赛题真正要的是：**一个能替代人工质检团队、能让数字人团队拿到就知道怎么改的自动化评测平台。**

我们将赛题拆解为五个递进层次：

```
Level 1: 能跑通 — 输入指令能输出评分          ← 大多数队伍止步于此
Level 2: 能覆盖 — 评测能触及各个业务分支        ← 覆盖率是关键
Level 3: 能可信 — 评分有证据、有规则、可校验     ← 不是LLM随便说说
Level 4: 能指导 — 告诉团队"改哪里、怎么改、涨几分" ← 业务价值核心
Level 5: 能落地 — 批量API、版本对比、复测闭环    ← 真实业务接入

                        本系统 ──→ 直接冲击 Level 5
```

### 对"过程可解释"的三层理解

| 层面 | 评委关心的问题 | 本系统的回答 |
|------|-------------|------------|
| **选择可解释** | 为什么选这个测试场景？ | "因为 edge:auth_or_trust→inform 未覆盖" |
| **判断可解释** | 为什么扣这个分？ | "Turn 3, 用户质疑身份, 客服未提供验证路径, 命中 p1_no_verification_path" |
| **结论可解释** | 这份报告能信吗？ | "边覆盖83%, 风险覆盖80%, 评测基本充分, 可作为问题定位参考" |

### 对"结果可量化"的五维量化

- **覆盖率** 量化评测充分性（4类×百分比）
- **维度分** 量化数字人表现（6维度×5分制）
- **封顶分** 量化合规风险（P0/P1一票否决）
- **采信度** 量化报告可信度（三层判定）
- **修复收益** 量化优化方向（改完涨几分）

---

## 🔬 核心创新：CGADS算法

<p align="center">
  <img src="./assets/架构总览流程图.png" alt="CGADS架构" width="90%"/>
</p>

### 灵感来源：从软件测试到对话评测

| 软件测试 Coverage-Guided Fuzzing | → | 对话评测 CGADS |
|---:|:---:|:---|
| 代码路径覆盖 | 迁移 | 对话状态路径覆盖 |
| 变异输入触发新路径 | 迁移 | 生成场景触发新状态边 |
| 覆盖率收敛 = 测试充分 | 迁移 | 4类覆盖率收敛 = 评测充分 |

### 形式化定义

将任务指令编译为评测空间 **D = ⟨S, E, R, Q⟩**：

| 符号 | 含义 | 示例 | 数量 |
|:---:|------|------|:---:|
| **S** | 对话状态 | opening, inform, auth_or_trust, busy, faq, confirm, refusal, handoff, closing | 9 |
| **E** | 状态转移边 | opening→inform, inform→faq, auth→refusal_exit... | 20 |
| **R** | P0/P1风险规则 | 绝对承诺、敏感信息、虚假身份、拒绝后营销... | 16 |
| **Q** | 原子业务需求 | 合同通知、配送提醒、App查看、转人工... | 10 |

### CGADS vs 传统方法

| 方法 | 状态覆盖 | 边覆盖 | 风险覆盖 | 业务需求 | 首次P1 |
|------|:-------:|:------:|:-------:|:--------:|:------:|
| 随机模拟 (12条) | 44% | 19% | 25% | 56% | 8条 |
| 分层抽样 (12条) | 67% | 44% | 56% | 67% | 5条 |
| **CGADS (9+3)** | **100%** | **83%** | **80%+** | **90%** | **2条** |

> 同等12场景预算，覆盖率全面碾压。CGADS不是"更好的随机"，是"有方向的系统搜索"。

---

## 🏗️ 系统架构

<p align="center">
  <img src="./assets/系统流程图.png" alt="系统流程图" width="90%"/>
</p>

### 端到端评测链路

```
┌─────────────────────────────────────────────────────────────────────┐
│  任务指令(自然语言)                                                    │
│    ↓ 指令解析 (LLM + 角色标准化 + 缓存加速)                            │
│  结构化DSL (角色/目标/流程8步/约束2条/FAQ/风险红线)                      │
│    ↓ DSL编译器                                                       │
│  评测空间 D = ⟨S(9), E(20), R(16), Q(10)⟩                           │
│    ↓ 风险优先调度 (Round-Robin: P0×3 → P1×4 → edge×3)               │
│  19种场景模板 × 状态感知用户模拟器                                      │
│    ↓ Runtime状态追踪 (slot门控 + intent分类 + auto-advance)           │
│  12场景 × 4轮均深 = 48轮多轮对话                                      │
│    ↓ 混合评测引擎                                                     │
│  规则Hard Gate (P0/P1否定语义检测) + 6维度LLM Judge                   │
│    ↓ 评分聚合 (加权 + 封顶 + 维度联动)                                │
│  三层采信判定 + Turn级证据链 + 修复收益预估                              │
│    ↓                                                                │
│  结构化报告 (Markdown/JSON) + 批量API + 复测闭环                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 每一步都可解释

| 环节 | 输入 | 输出 | 为什么可解释 |
|------|------|------|------------|
| 指令解析 | 自然语言 | JSON | 每字段溯源到原文 |
| DSL编译 | JSON | 状态机 | flow→states, constraints→rules |
| 场景生成 | 覆盖缺口 | 场景列表 | **"选这个场景因为edge X未覆盖"** |
| 状态追踪 | 用户话术 | 状态转移 | intent分类(0.92) + slot匹配 |
| 规则检查 | 客服回复 | pass/fail | **否定语境过滤 + 关键词命中** |
| 维度评分 | 对话+违规 | 6维度分 | **原子公式：8/10需求×5=4.0** |
| 采信判定 | 覆盖率 | 三层结论 | **边83%+风险80% → 基本充分** |

---

## 🛡️ 四大创新详解

### 创新一：三层生产采信判定

> 传统评测：给72分。业务方："所以呢？能上线吗？"
> 本系统：给三个答案。

```
┌─────────────────────────────────────────────┐
│  Tier 1  数字人表现    → 有条件通过 🟡       │
│          (存在1个P1违规)                      │
│                                             │
│  Tier 2  评测充分性    → 基本充分 🟢         │
│          (边覆盖83%, 风险覆盖80%)            │
│                                             │
│  Tier 3  生产采信      → 不可直接放行 🟡     │
│          (P1存在 → 永不给"可放行")           │
└─────────────────────────────────────────────┘
```

**铁律**：P1存在 → 永不放行。边<65% → 永不采信。

### 创新二：P0/P1 否定语义检测

| 客服原话 | 旧方案 | 本系统 | 原因 |
|---------|:------:|:------:|------|
| "我**无法**查询您的身份证号" | ❌ P0 | ✅ 跳过 | 否定语境 |
| "请您把身份证号发给我" | P0 | P0 | 意图明确 |
| "我**无法保证**百分百成功" | ❌ P0 | ✅ 跳过 | 否定语境 |
| "保证能通过，百分百没问题" | P0 | P0 | 绝对承诺 |

**误判率降低 90%+。** 这不是微调阈值，是引入了语义层判断。

### 创新三：修复→复测闭环

```
┌─────── 修复收益预估 ───────┐
│                            │
│  当前：54.4分 (CAPPED_P1)  │
│  预估：74.4分 (+20分)      │
│                            │
│  具体修复项：               │
│  ├─ [+10] 补充验证路径话术  │
│  ├─ [+5]  消除重复话术     │
│  └─ [+5]  压缩超长回复     │
│                            │
│  → POST /api/retest 验证   │
└────────────────────────────┘
```

### 创新四：状态感知Fallback

即使100% LLM超时，评测也不会中断：

```python
# 每个状态有2-5种语义正确的fallback，按turn轮换
STATE_FALLBACKS = {
    "opening":     ["您好，我是美团站长，通知您合同签署的事。", ...],
    "inform":      ["合同已签署生效，今日需完成配送任务。", ...],
    "auth_or_trust": ["您可在App-我的合同查看官方通知。", ...],
    "closing":     ["好的，祝您顺利，再见。", ...],
}
```

---

## 📊 评分机制

```python
# 6维度加权
raw = 25%×任务完成 + 20%×流程遵循 + 20%×约束合规
    + 15%×分支处理 + 10%×上下文 + 10%×沟通体验

# P0/P1封顶（一票否决）
if P0触发:   final = min(raw, 30)   # 致命违规
elif P1≥3:  final = min(raw, 50)
elif P1==2: final = min(raw, 60)
elif P1==1: final = min(raw, 70)   # 有P1就封顶
else:       final = raw             # 无违规

# 维度联动：检出违规 → 反向影响相关维度分
no_repeat检出       → 上下文一致性 ≤ 2分
truncated_output    → 沟通体验 ≤ 3分
```

---

## 🏭 业务落地能力

### 为什么能接入真实业务？

| 能力 | 实现 | 业务价值 |
|------|------|---------|
| 批量评测 | `POST /api/batch-evaluate` 最多20条并发 | 版本迭代批量跑 |
| 状态查询 | `GET /api/batch-evaluate/{id}/status` | 异步不阻塞 |
| 失败重试 | `POST /api/batch-evaluate/{id}/retry` | 稳定性兜底 |
| A/B对比 | `POST /api/compare` | 版本升级有数据 |
| 复测闭环 | `POST /api/retest` | 修复后验证收益 |
| 报告导出 | Markdown + JSON双格式 | 对接内部系统 |

### 适用场景

| 外呼场景 | 评测产出 | 业务收益 |
|---------|---------|---------|
| 骑手合同通知 | P1:缺验证路径 → 修复后+10分 | 减少"你是骗子"投诉 |
| 商家结算通知 | P0:承诺兜底 → 必须修复 | 避免合规风险 |
| 用户售后回访 | 覆盖:忙碌/拒绝/转人工路径 | 提升回访完成率 |
| 课程购买确认 | P1:关键信息遗漏 → 补充FAQ | 减少退费纠纷 |

---

## 🆚 与现有方案对比

| 维度 | Prompt+Judge | DeepEval | **橙脉CGADS** |
|------|:-----------:|:--------:|:-------------:|
| 场景来源 | 手工枚举 | 固定persona | **覆盖缺口反向生成** |
| 覆盖保证 | ❌ | ❌ | ✅ 4类覆盖+Adequacy |
| 风险发现 | 看运气 | 看运气 | ✅ P0优先+Round-Robin |
| 误判控制 | ❌ | ❌ | ✅ 否定语义过滤 |
| 可解释性 | "3分" | "0.7" | ✅ Turn→规则→证据→修复 |
| 采信判定 | ❌ | ❌ | ✅ 三层(表现/充分/放行) |
| 业务闭环 | ❌ | ❌ | ✅ 修复收益+复测对比 |
| 批量接入 | ❌ | ✅ | ✅ Job+重试+对比 |

---

## 🚀 快速开始

### 在线体验

> **🌐 国内：[http://139.196.183.227](http://139.196.183.227)**  
> **🌐 海外：[https://diligent-eagerness-production-14ff.up.railway.app](https://diligent-eagerness-production-14ff.up.railway.app)**

粘贴任务指令 → 开始评测 → 实时观察 → 查看三层判定 → 下载报告

### 本地部署

```bash
git clone https://github.com/liu66-qing/CGADS.git && cd CGADS
pip install -r requirements.txt
cp .env.example .env  # 填入 DEEPSEEK_API_KEY
uvicorn backend.api:app --host 0.0.0.0 --port 8000
# 前端
cd frontend && npm install && npm run build
```

### 命令行评测

```bash
python -X utf8 run_eval_pipeline.py \
  --instruction_file data/processed/task_001_rider_flying_leg.json \
  --max_scenarios 12
```

---

## 📚 参考文献

| 来源 | 迁移用途 | 论文 |
|------|---------|------|
| Coverage-Guided Fuzzing | CGADS覆盖率驱动核心思想 | AFL/LibFuzzer |
| IFEval | 可验证约束检查 | arXiv:2311.07911 |
| G-Eval | LLM Judge with CoT | arXiv:2303.16634 |
| Prometheus | Fine-grained rubric | arXiv:2310.08491 |
| MultiChallenge | 多轮instance rubric | arXiv:2501.17399 |
| ConvLab-2 | DST/Policy思想 | ACL 2020 Demo |
| Anthropic Eval | Reasoning-first judge | docs.anthropic.com |

---

## 👥 团队

**对对队** · 美团AI Hackathon 2026

---

<p align="center">
  <em>"评测系统的价值不在于给一个分，而在于让数字人团队拿到报告的那一刻就知道下一步该做什么。"</em>
</p>

---

## License

MIT
