# Codex 任务 — 前端优化（P0-3, P1-2, P2-1, P2-2）

## 背景
这是美团AI Hackathon比赛项目。第一轮评审68分，需要修复到95分。Claude已完成后端逻辑修改（PASS逻辑、证据链、对话查看器、批量API）。现在需要Codex并行完成前端修改。

## 任务清单

### P0-3: 删除假数据/模板（高优先）

评委严厉批评"未开始评测就显示假数据伤可信度"。以下组件在评测未启动时显示了假/模板数据，必须清除：

1. **`frontend/src/components/StateMachineGraph.tsx`**
   - 删除 `fallbackStates` (lines 6-16) 和 `fallbackEdges` (lines 18-27) 这两个硬编码数组
   - 当 `states.length === 0` 时，显示一个简洁的空状态: "等待评测 — DSL编译后生成状态图"
   - 删除 lines 139-151 的假事件时间轴（4个硬编码fake events），改为: "等待评测启动后生成事件日志"

2. **`frontend/src/components/ScoreCard.tsx`**
   - 删除 lines 65-72 的假violation（`rule_id: '等待证据链'`, `scenario: '评测启动后生成'`）
   - 当 violations 为空时显示: 灰色 "待测" 标签 + "等待评测完成"

3. **`frontend/src/components/ReportPanel.tsx`**
   - 删除 lines 17-29 的 `fallbackMarkdown`（含假分数 `--`、假覆盖率）
   - 替换为: `'> 评测尚未完成。请先运行评测，报告将在完成后自动生成。'`

4. **`frontend/src/components/EvidenceTimeline.tsx`** — 已由Claude修改完成，跳过

**原则**: 未跑评测 = 空白干净。不能有任何数字、分数、节点名、假violation。

### P1-2: Markdown表格渲染

`ReportPanel.tsx` 使用 `<ReactMarkdown>` 但不支持GFM表格。

1. 安装: `npm install remark-gfm`
2. 修改 `ReportPanel.tsx`:
   ```tsx
   import remarkGfm from 'remark-gfm'
   // ...
   <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
   ```

### P2-1: 视觉风格收敛

评委说"整体偏花，像运营大屏，不像评测工作台"。

在 `frontend/src/style.css` 中:
1. 减少橙色发光/渐变 — 搜索所有 `box-shadow` 含 `#FF` 或 `orange` 的，降低强度或改为更克制的色调
2. 减少 `linear-gradient` 中过于鲜艳的颜色过渡
3. 卡片阴影从 `0 8px 32px rgba(...)` 改为更轻薄的 `0 2px 8px rgba(0,0,0,0.08)`
4. 整体色调从"运营橙色"向"工程蓝灰"靠拢

**不要改动功能组件的结构，只改CSS视觉效果。**

### P2-2: 状态机从主角降为辅助

当前 `App.tsx` 布局中 StateMachineGraph 和 ScoreCard 并列占据 main-grid。

修改 `App.tsx`:
```tsx
<div className="main-grid results-primary">
  <ScoreCard />
</div>
<details className="state-machine-collapsible" open>
  <summary>状态机可视化 (点击折叠)</summary>
  <StateMachineGraph />
</details>
```

并在 `style.css` 添加对应样式让 `<details>` 看起来像可折叠面板。

## 注意事项
- TypeScript必须通过: `npx tsc --noEmit`
- Vite build必须成功: `npx vite build`
- 不要修改 `evaluationStore.ts`（Claude已改过）
- 不要修改 `EvidenceTimeline.tsx`（Claude已改过）
- 不要修改 `types.ts`（Claude已改过）
