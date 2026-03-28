# Skill 数据依赖矩阵与缺口盘点 v1

> **版本**: v1.0 | **日期**: 2026-03-29 | **状态**: 盘点完成
> **依赖**: COL-154 Skill 体系设计 + COL-148~153 事实数据体系 + COL-156 REST API

---

## 1. 总览

| Fact Pack | 类别总数 | 已实现 | 未实现 | 覆盖率 |
|-----------|---------|--------|--------|--------|
| Stock Fact Pack | 8 | 8 | 0 | 100% |
| Fund Fact Pack | 8 | 8 | 0 | 100% |
| Market Fact Pack | 8 | 8 | 0 | 100% |
| **合计** | **24** | **24** | **0** | **100%** |

| 辅助能力 | 状态 |
|---------|------|
| Markdown 事实视图 | ✅ 三类全部实现 (stock/fund/market) |
| REST API 端点 | ✅ ~77 端点覆盖 |
| MCP 工具 | ✅ 113 tools |

---

## 2. 各 Skill 数据依赖详析

### S1 搜索与定位

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 股票搜索 | 必需 | `search_stocks` MCP/REST | ✅ 已具备 |
| 基金搜索 | 必需 | `search_funds` MCP/REST | ✅ 已具备 |
| ETF搜索 | 可选 | `get_etf_list` | ✅ 已具备 |
| 板块搜索 | 可选 | `resolve_sector` MCP | ✅ 已具备 |

**覆盖率: 100%** — 无缺口。

---

### S2 个股研究

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| security_master (证券主档) | 必需 | Stock FP → security_master | ✅ 已具备 |
| financial (财务事实) | 必需 | Stock FP → financial | ✅ 已具备 |
| market (市场事实) | 必需 | Stock FP → market | ✅ 已具备 |
| governance (治理与股权) | 必需 | Stock FP → governance | ✅ 已具备 |
| events (事件事实) | 必需 | Stock FP → events | ✅ 已具备 |
| business_structure (业务结构) | 必需 | Stock FP → business_structure | ✅ 已具备 |
| company_master (公司主档) | 必需 | Stock FP → company_master | ❌ 未实现 |
| peers (同业对比) | 必需 | Stock FP → peers | ❌ 未实现 |
| 技术分析信号汇总 | 可选 | `calculate_technical_indicators` | ⚠️ 有指标无信号解读层 |
| 新闻舆情 | 可选 | news group (默认禁用) | ⚠️ 禁用状态 |

**覆盖率: 75%** — 关键缺口: company_master, peers。

**缺口详情**:
- **company_master**: 公司基本信息聚合 (成立日期、注册地、法人、主营业务描述、员工数等)。akshare 有 `stock_individual_info_em` 可直接提供。
- **peers**: 同行业对标公司列表及对比数据。可从 `stock_board_industry_cons_em` 获取同板块成分股，再筛选市值/行业相近标的。
- **技术信号解读**: 已有 SMA/RSI/MACD 等指标计算，但缺少"超买/超卖/金叉/死叉"等确定性信号判断层。
- **news**: 工具组存在但默认禁用，需评估启用条件 (API 配额/合规性)。

---

### S3 基金研究

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| master (基金主档) | 必需 | Fund FP → master | ✅ 已具备 |
| nav (净值与收益) | 必需 | Fund FP → nav | ✅ 已具备 |
| holdings (持仓与穿透) | 必需 | Fund FP → holdings | ✅ 已具备 |
| manager (基金经理) | 必需 | Fund FP → manager | ✅ 已具备 |
| scale (规模与份额) | 必需 | Fund FP → scale | ✅ 已具备 |
| allocation (资产配置) | 必需 | Fund FP → allocation | ✅ 已具备 |
| fees (费率与分红) | 必需 | Fund FP → fees | ❌ 未实现 |
| peer_comparison (同类比较) | 必需 | Fund FP → peer_comparison | ❌ 未实现 |
| 基金经理变更事件 | 可选 | fund detail 中的变更记录 | ⚠️ 需提取 |

**覆盖率: 75%** — 关键缺口: fees, peer_comparison。

**缺口详情**:
- **fees**: 管理费、托管费、申购费、赎回费。akshare 有 `fund_open_fund_info_em` 可获取费率数据。
- **peer_comparison**: 同类型基金收益/风险对比排名。可基于已有 `get_fund_ranking` 构建。
- **经理变更**: 需从 fund detail 中提取变更记录并结构化。

---

### S4 财报速读

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 财务三表 (利润/资产/现金) | 必需 | Stock FP → financial | ✅ 已具备 |
| 关键财务比率 | 必需 | `get_valuation_metrics` | ✅ 已具备 |
| 营收/利润同比环比 | 必需 | financial 中的 YoY/QoQ | ✅ 已具备 |
| A股公告结构化提取 | 可选 | filings 路由 | ⚠️ 有原始文本，缺关键信息提取 |

**覆盖率: 90%** — 公告结构化提取为可选增强。

**缺口详情**:
- **公告结构化**: 当前 filings 有 SEC 文档解析 (edgar)，A股公告为原文。需要从年报/季报公告中自动提取关键财务数字并结构化。

---

### S5 市场观察

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 市场广度 (涨跌家数) | 必需 | Market FP → breadth | ✅ 已具备 |
| 资金流向 | 必需 | Market FP → money_flow | ✅ 已具备 |
| 指数行情 | 必需 | Market FP → index | ✅ 已具备 |
| 板块涨跌排行 | 必需 | `get_sector_trend` | ✅ 已具备 |
| 风格轮动 | 必需 | `get_style_rotation` | ✅ 已具备 |
| 行业估值历史百分位 | 可选 | `get_sector_pe_pb_historical` | ⚠️ 未接入 fact pack |

**覆盖率: 95%** — 行业估值百分位为可选增强。

---

### S6 组合分析

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| N只股票的 Stock FP | 必需 | Stock FP × N | ✅ 已具备 |
| Market FP | 必需 | Market FP | ✅ 已具备 |
| 持仓标的间相关性 | 必需 | `get_stock_correlation` | ✅ 已具备 |
| 行业分类映射 | 必需 | `resolve_sector` | ✅ 已具备 |
| 市值分布/集中度 | 必需 | market category 中的 market_cap | ✅ 已具备 |

**覆盖率: 100%** — 无缺口。已有 `get_stock_correlation` 可直接复用。

---

### S7 风控预警

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 涨跌幅异动 | 必需 | Market FP → snapshot | ✅ 已具备 |
| 成交放量 | 必需 | Market FP → kline | ✅ 已具备 |
| 资金流异常 | 必需 | Market FP → money_flow | ✅ 已具备 |
| 解禁日历 | 必需 | Stock FP → events | ✅ 已具备 |
| 股东变动 | 必需 | Stock FP → governance | ✅ 已具备 |
| 新闻舆情预警 | 可选 | news group | ⚠️ 禁用状态 |
| 技术信号异常 | 可选 | 技术指标 | ⚠️ 缺信号解读层 |

**覆盖率: 85%** — 核心数据齐全，增强层 (新闻/技术信号) 可后续补充。

---

### S8 买前检查

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 估值水平 (PE/PB) | 必需 | Stock FP → financial / valuation | ✅ 已具备 |
| 财务健康 | 必需 | Stock FP → financial | ✅ 已具备 |
| 治理风险 | 必需 | Stock FP → governance | ✅ 已具备 |
| 市场信号 | 必需 | Market FP → money_flow | ✅ 已具备 |
| 解禁计划 | 必需 | Stock FP → events | ✅ 已具备 |
| 股东变动 | 必需 | Stock FP → governance | ✅ 已具备 |
| 同业估值对比 | 可选 | Stock FP → peers | ❌ 未实现 |
| 基金费率检查 | 可选 | Fund FP → fees | ❌ 未实现 |

**覆盖率: 85%** — 核心检查项齐全。peers 缺失影响同业对比环节。

---

### S9 持仓晨报

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 持仓标的价格变动 | 必需 | Market FP → snapshot | ✅ 已具备 |
| 持仓标的异动 | 必需 | Market FP → kline | ✅ 已具备 |
| 今日关注事件 | 必需 | Stock FP → events | ✅ 已具备 |
| 大盘概览 | 必需 | Market FP → index | ✅ 已具备 |
| 北向资金 | 可选 | `get_north_bound_flow` | ✅ 已具备 |

**覆盖率: 100%** — 无缺口。

---

### S10 交易复盘

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 标的事后行情 | 必需 | Stock/Fund/Market FP | ✅ 已具备 |
| 交易期间事件 | 必需 | Stock FP → events | ✅ 已具备 |
| 交易期间资金流 | 可选 | Market FP → money_flow | ✅ 已具备 |

**覆盖率: 100%** — 事后验证数据齐全。

---

### S11 主题搜索

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| 概念板块定位 | 必需 | `resolve_sector` MCP | ✅ 已具备 |
| 板块成分股 | 必需 | `build_sector_universe` MCP | ✅ 已具备 |
| 成分股基本面 | 必需 | Stock FP → business_structure | ✅ 已具备 |
| 概念排名 | 可选 | `get_concept_ranking` | ✅ 已具备 |

**覆盖率: 100%** — 无缺口。

---

### S12 对比分析

| 数据需求 | 类型 | 来源 | 覆盖状态 |
|---------|------|------|---------|
| N只标的 Stock/Fund FP | 必需 | Fact Pack × N | ✅ 已具备 |
| 估值对比 | 必需 | FP → financial/valuation | ✅ 已具备 |
| 财务对比 | 必需 | FP → financial | ✅ 已具备 |
| 市场指标对比 | 必需 | Market FP × N | ✅ 已具备 |
| 同业对比框架 | 可选 | Stock FP → peers | ❌ 未实现 |

**覆盖率: 90%** — 缺 peers 影响自动选择对比标的。

---

## 3. 覆盖率汇总

| Skill | 覆盖率 | 状态 | 关键缺口 |
|-------|--------|------|---------|
| S1 搜索与定位 | 100% | ✅ 可用 | - |
| S2 个股研究 | 75% | ⚠️ 部分可用 | company_master, peers |
| S3 基金研究 | 75% | ⚠️ 部分可用 | fees, peer_comparison |
| S4 财报速读 | 90% | ✅ 可用 | 公告结构化提取 (可选) |
| S5 市场观察 | 95% | ✅ 可用 | 行业估值百分位 (可选) |
| S6 组合分析 | 100% | ✅ 可用 | - |
| S7 风控预警 | 85% | ✅ 可用 | 新闻/技术信号 (可选) |
| S8 买前检查 | 85% | ✅ 可用 | peers (可选) |
| S9 持仓晨报 | 100% | ✅ 可用 | - |
| S10 交易复盘 | 100% | ✅ 可用 | - |
| S11 主题搜索 | 100% | ✅ 可用 | - |
| S12 对比分析 | 90% | ✅ 可用 | peers (可选) |

**可直接使用的 Skill**: S1, S4, S5, S6, S7, S8, S9, S10, S11, S12 (10/12)
**部分可用的 Skill**: S2, S3 (2/12)

---

## 4. 缺口优先级排序

### P0 — 阻塞核心 Skill

| # | 缺口 | 影响 Skill | 实现方案 | 预估工作量 |
|---|------|-----------|---------|-----------|
| G1 | **company_master** | S2 个股研究 | akshare `stock_individual_info_em` 聚合 | 小 |
| G2 | **peers** (同业对比) | S2, S8, S12 | 从 `stock_board_industry_cons_em` 取同板块 → 按市值筛选 | 中 |
| G3 | **fees** (基金费率) | S3 基金研究 | akshare `fund_open_fund_info_em` 提取费率字段 | 小 |
| G4 | **peer_comparison** (基金同类比较) | S3 基金研究 | 基于 `get_fund_ranking` 构建 | 中 |

### P1 — 增强层

| # | 缺口 | 影响 Skill | 实现方案 | 预估工作量 |
|---|------|-----------|---------|-----------|
| G5 | 技术信号解读层 | S2, S5, S7 | 在 `calculate_technical_indicators` 基础上加信号判断 | 中 |
| G6 | A股公告结构化提取 | S4 | 从原始公告提取关键数字 | 大 |
| G7 | 行业估值历史百分位接入 fact pack | S5, S8 | 已有 `get_sector_pe_pb_historical`，需接入 Market FP | 小 |
| G8 | 新闻舆情启用评估 | S2, S7, S9 | 评估 API 配额和合规性后启用 news group | 评估 |

### P2 — 可选增强

| # | 缺口 | 影响 Skill | 实现方案 | 预估工作量 |
|---|------|-----------|---------|-----------|
| G9 | 基金经理变更事件 | S3 | 从 fund detail 提取变更记录 | 小 |
| G10 | 持仓标的间相关性可视化 | S6 | 已有 `get_stock_correlation`，前端展示层 | 小 |

---

## 5. 补齐建议任务拆分

基于以上缺口分析，建议拆分为以下实现任务:

### TASK-A: 补齐 Stock Fact Pack 缺失类别 (G1 + G2)

- 实现 `company_master` 事实类别
- 实现 `peers` 事实类别
- 更新 `get_stock_fact_pack` 的 coverage 输出
- 更新 `build_stock_fact_markdown` 的 Markdown 视图

### TASK-B: 补齐 Fund Fact Pack 缺失类别 (G3 + G4)

- 实现 `fees` 事实类别
- 实现 `peer_comparison` 事实类别
- 更新 `get_fund_fact_pack` 的 coverage 输出
- 更新 `build_fund_fact_markdown` 的 Markdown 视图

### TASK-C: 技术信号解读层 (G5)

- 为 `calculate_technical_indicators` 输出增加确定性信号判断
- 信号类型: 超买/超卖 (RSI)、金叉/死叉 (MACD)、突破/跌破 (布林带)
- 信号输出为事实型: "RSI(14)=78.2" 而非 "超买"

### TASK-D: 行业估值百分位接入 Market FP (G7)

- 将 `get_sector_pe_pb_historical` 接入 Market Fact Pack 的 index 类别
- 计算历史百分位并作为确定性加工输出

---

## 6. Skill 实施路径建议

基于数据依赖分析，建议分三批实施 Skill:

**第一批 (数据完备)**: S1, S6, S9, S10, S11 — 覆盖率 100%，可直接开始
**第二批 (补齐 G1-G4 后)**: S2, S3, S12 — 需要补齐 fact pack 缺失类别
**第三批 (增强层)**: S4, S5, S7, S8 — 已可用但可选增强数据进一步提升体验

---

## 附录 A: Fact Pack 类别与 Markdown 视图对应

| Fact Pack | 类别 | Markdown 渲染函数 |
|-----------|------|-----------------|
| Stock | security_master | `_render_security_master` |
| Stock | financial | `_render_financial` |
| Stock | market | `_render_market` |
| Stock | governance | `_render_governance` |
| Stock | events | `_render_events` |
| Stock | business_structure | `_render_business_structure` |
| Stock | company_master | ❌ 无 (未实现) |
| Stock | peers | ❌ 无 (未实现) |
| Fund | 全部 | `build_fund_fact_markdown` (统一渲染) |
| Market | 全部 | `build_market_fact_markdown` (统一渲染) |

## 附录 B: REST API ↔ Skill 可用端点

| Skill | 可用 REST 端点 |
|-------|-------------|
| S1 | `/api/v1/market/search`, `/api/v1/fund/search` |
| S2 | `/api/v1/fundamental/*`, `/api/v1/money-flow/stock/*` |
| S3 | `/api/v1/fund/*`, `/api/v1/fact-pack/fund` |
| S4 | `/api/v1/fundamental/financials`, `/api/v1/fundamental/main-business` |
| S5 | `/api/v1/money-flow/market-breadth`, `/api/v1/money-flow/style-rotation`, `/api/v1/index/*` |
| S6 | `/api/v1/fundamental/*` × N, `/api/v1/quant/correlation` |
| S7 | `/api/v1/money-flow/*`, `/api/v1/money-flow/restricted-release` |
| S8 | `/api/v1/fundamental/*`, `/api/v1/money-flow/*`, `/api/v1/fact-pack/stock` |
| S9 | `/api/v1/money-flow/north-bound`, `/api/v1/market/*` |
| S10 | `/api/v1/fact-pack/*`, `/api/v1/fundamental/*` |
| S11 | `/api/v1/quant/concept-ranking`, `/api/v1/index/*` |
| S12 | `/api/v1/fact-pack/*` × N, `/api/v1/quant/correlation` |
