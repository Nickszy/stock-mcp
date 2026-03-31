# Stock MCP 数据覆盖缺口与补充路线

## 1. 背景

当前 `stock-mcp` 的整体架构，已经具备继续扩数的基础：

- `src/server/domain/adapter_manager.py` 已经实现了按 ticker / market 维度的统一调度与 failover。
- `src/server/domain/adapters/base.py` 已经把大部分数据能力抽象成了 adapter 方法。
- `src/server/mcp/tools/` 已经按数据域拆成了 `asset`、`fundamental`、`money-flow`、`filings`、`technical`、`us-*`、`sector-research` 等工具组。

这意味着后续不需要“每个数据源暴露一套接口”，而是应该坚持：

1. 每个数据类别只暴露一个统一接口。
2. 接口下面挂多个 adapter。
3. 按数据质量和稳定性做主源 + 备源回退。
4. 对 LLM 的输出统一走 Markdown，而不是原始 JSON。

## 2. 外部对标结论

### 2.1 AKShare

AKShare 官方文档展示的覆盖面明显比当前 `stock-mcp` 更宽，尤其在 A 股事件类和扩展资产域上。

从其股票数据文档可见，已覆盖或提供接口入口的数据域包括：

- A 股 / 港股 / 美股行情与分时
- 机构调研
- 股权质押
- 商誉专题
- 分析师指数、千股千评
- 沪深港通资金流与持股
- 停复牌
- 公告、业绩报表、业绩快报、业绩预告
- 资产负债表、利润表、现金流量表
- 高管持股、股东增减持
- 资金流向、筹码分布
- 个股研报
- 十大股东 / 十大流通股东
- 基金、宏观等独立数据域

这说明如果只以免费公开源为目标，`stock-mcp` 仍然有较大补充空间。

参考来源：

- [AKShare 股票数据文档](https://akshare.akfamily.xyz/data/stock/stock.html)
- [AKShare 公募基金数据文档](https://akshare.akfamily.xyz/data/fund/fund_public.html)
- [AKShare 宏观数据文档](https://akshare.akfamily.xyz/data/macro/macro.html)

### 2.2 iFinD

iFinD 官方站点更强调“投研平台 + 另类数据 + 智能资讯 + 产业洞察 + AI 预测”。

从官方介绍可以抽象出它的优势数据域：

- 传统金融数据之外的另类数据
- 智能资讯 / 事件库
- 产业链与行业洞察
- 宏观、行业、公司三级预测
- 大规模指标库与企业库

这意味着 iFinD / Wind 的价值不只是“替代 AKShare 的行情接口”，而是能补足当前仓库最薄弱的几块：

- 事件驱动研究
- 产业链研究
- 分析师 / 机构预期
- 另类数据与舆情
- 更高质量的机构级宽表

参考来源：

- [iFinD 官方站点](https://www.aifind.com/)

### 2.3 Wind

Wind 官方数据接口与 EDB 页面体现的核心优势是：

- 全市场金融数据
- 商业数据、宏观数据、资讯舆情、专题特色数据
- 全球宏观与行业经济数据库
- 企业数据、事件日历、预测值与实际值
- ESG 与专题数据库

Wind 对 `stock-mcp` 的真正补充价值主要在：

- 机构级统一口径
- 宏观 + 行业 + 公司的一体化研究链
- 日历 / 预期 / surprise 类数据
- 债券、基金、外汇、期权、ESG 等广覆盖资产域

参考来源：

- [Wind 数据接口服务](https://www.wind.com.cn/mobile/WDS/sapi/zh.html)
- [Wind Economic Database](https://www.wind.com.cn/portal/en/EDB/index.html)
- [Wind 官网](https://www.wind.com.cn/)

## 3. 当前 stock-mcp 已覆盖的数据

按现有代码，当前仓库已经具备以下基础能力：

### 3.1 已有核心能力

- 行情：实时价、K 线、技术指标、形态、支撑阻力、成交量分析
- A 股基本面：财务趋势、主营构成、股东信息、分红、业绩预告、估值、盈利预测
- 资金面：个股资金流、北向、筹码、市场流动性、板块资金流、板块估值
- 宏观：M2、CPI、PMI、GDP、社融、利率
- 公告 / 文件：SEC 与 A 股公告抓取、Markdown 处理、章节事实抽取
- 美股：盈利历史、现金流质量、估值、机构持仓、价格历史、成交量分析、行业 ETF、宏观
- 其他资产：加密、商品、部分外汇 / 大宗现货的基础行情能力

### 3.2 现状中的结构性问题

虽然“有不少工具”，但仍有四个明显短板：

1. 没有 `WindAdapter` / `IFindAdapter`
2. 资产域覆盖不均衡，明显偏 A 股股票研究
3. 事件类数据与行为类数据不完整
4. 对 LLM 的输出仍然不是 Markdown-first

## 4. 缺口清单

下面按“研究价值 + 可落地性 + 与现有架构匹配程度”排序。

### 4.1 盘点清单

说明：

- `已开发`：仓库里已经有统一工具，且至少接了一个可用 adapter。
- `部分开发`：仓库里已经有部分能力，但还没形成完整统一接口，或缺少高质量主源。
- `源有但未开发`：AKShare / iFinD / Wind 有对应数据能力，但仓库里还没有工具或 adapter 接入。

| 优先级 | 数据类别 | 当前状态 | 当前已接数据源 | 外部数据源有但仓库未开发 | 建议下一步 |
| --- | --- | --- | --- | --- | --- |
| P0 | 行情 / K 线 | 已开发 | `akshare` `tushare` `baostock` `yahoo` `finnhub` `twelve_data` | `wind` `ifind` | 补 `wind/ifind` 行情 adapter，提高质量与稳定性 |
| P0 | 完整财报三大表 | 部分开发 | `tushare` `akshare` `baostock` `yahoo` | `wind` `ifind` | 收敛成正式 `get_financial_statements` |
| P0 | 公司事件中心 | 源有但未开发 | 局部只有 `filings` / `forecast` / `news` | `akshare` `tushare` `wind` `ifind` | 新增 `get_company_events` |
| P0 | 机构与资金行为 | 部分开发 | `tushare` `akshare` `yahoo` `finnhub` | `wind` `ifind` | 新增 `get_market_participant_data` |
| P0 | 一致预期 / 评级 / 目标价 / 研报 | 部分开发 | `akshare` `tushare` 仅局部盈利预测 | `wind` `ifind` | 新增 `get_analyst_expectations` |
| P0 | Markdown-first 输出层 | 部分开发 | 已有 `summary + artifact` | 所有数据域都需要 | 新增统一 Markdown 渲染 helper |
| P1 | 板块 / 指数成分与权重 | 源有但未开发 | 无正式统一工具 | `tushare` `akshare` `wind` `ifind` | 新增 `get_index_constituents` |
| P1 | 产业链 / 行业链路 | 源有但未开发 | 只有 `sector_research` 工作流骨架 | `ifind` `wind` | 新增 `get_industry_chain_data` |
| P1 | 基金数据 | 源有但未开发 | 底层 `AssetType.FUND` 存在，但无工具 | `akshare` `tushare` `wind` `ifind` | 新增 `get_fund_data` |
| P1 | 债券数据 | 源有但未开发 | 无 | `akshare` `wind` `ifind` | 新增 `AssetType.BOND` + `get_bond_data` |
| P1 | 期权数据 | 源有但未开发 | 无 | `akshare` `wind` `ifind` | 新增 `AssetType.OPTION` + `get_option_data` |
| P1 | 外汇研究数据 | 部分开发 | `yahoo` `twelve_data` `alpha_vantage` 仅行情 | `wind` `ifind` | 新增 `get_fx_data` 研究接口 |
| P1 | 日历类数据 | 源有但未开发 | 无正式统一工具 | `akshare` `wind` `ifind` | 新增 `get_calendar_data` |
| P2 | 另类数据 / 舆情 | 源有但未开发 | 只有基础新闻 | `ifind` `wind` | 新增 `get_alt_data` |
| P2 | ESG | 源有但未开发 | 无 | `wind` `ifind` | 新增 `get_esg_data` |
| P2 | AI 预测 / 宏观预测 | 源有但未开发 | 无 | `ifind` `wind` | 新增 `get_ai_forecast` |

### 4.2 已开发清单

- `[已开发][P0]` 行情 / K 线
  当前工具：`get_kline_data`
  当前数据源：`akshare` `tushare` `baostock` `yahoo` `finnhub` `twelve_data`
- `[已开发][P0]` 技术分析
  当前工具：`get_technical_indicators`、`analyze_price_patterns`、`calculate_support_resistance`、`analyze_volume_profile`
  当前数据源：`tushare` 为主，海外部分由 `yahoo`
- `[已开发][P0]` A 股基本面基础能力
  当前工具：`get_financial_reports`、`get_mainbz_info`、`get_shareholder_info`、`get_dividend_info`、`get_valuation_metrics`、`get_profit_forecast`
  当前数据源：`tushare` `akshare` `baostock`
- `[已开发][P0]` 资金流与宏观
  当前工具：`get_money_flow`、`get_north_bound_flow`、`get_chip_distribution`、`get_money_supply`、`get_inflation_data`、`get_pmi_data`、`get_gdp_data`、`get_social_financing`、`get_interest_rates`、`get_market_liquidity`、`get_market_money_flow`
  当前数据源：`tushare` `akshare`
- `[已开发][P0]` 美股研究基础能力
  当前工具：`get_earnings_history`、`get_cash_flow_quality`、`get_us_valuation_metrics`、`get_us_institutional_holdings`、`get_us_price_history`、`get_us_volume_analysis`、`get_us_sector_etf_analysis`
  当前数据源：`yahoo` `finnhub` `fred`
- `[已开发][P0]` 公告 / 文件解析
  当前工具：`fetch_periodic_sec_filings`、`fetch_event_sec_filings`、`fetch_ashare_filings`、`get_filing_markdown`、`extract_filing_key_metrics`
  当前数据源：`edgar` `akshare` `finnhub`

### 4.3 部分开发清单

- `[部分开发][P0]` 财务数据
  问题：现在更像多个零散工具，不是一个完整、统一、可扩展的财报接口。
  已接源：`tushare` `akshare` `baostock` `yahoo`
  缺源：`wind` `ifind`
- `[部分开发][P0]` 机构行为
  问题：美股机构持仓有，A 股机构行为、融资融券、基金持仓、席位行为没有统一收口。
  已接源：`yahoo` `finnhub` `tushare` `akshare`
  缺源：`wind` `ifind`
- `[部分开发][P0]` 研究输出
  问题：很多工具仍是 JSON-first，不是 Markdown-first。
  已有：`summary + artifact`
  缺少：统一 Markdown 渲染和标准 section 模板
- `[部分开发][P1]` 外汇
  问题：只有底层行情，没有研究型统一接口。
  已接源：`yahoo` `twelve_data` `alpha_vantage`
  缺源：`wind` `ifind`
- `[部分开发][P1]` 行业研究
  问题：已有 `sector_research` 工作流，但没有真正的产业链 / 行业指标底层数据接口。
  已接源：少量 `tushare`
  缺源：`ifind` `wind`

### 4.4 数据源有但未开发清单

- `[未开发][P0]` 公司事件中心
  数据源已有：`akshare` `tushare` `wind` `ifind`
  仓库现状：没有统一 `get_company_events`
- `[未开发][P0]` 一致预期 / 评级 / 目标价 / 研报
  数据源已有：`wind` `ifind`，`akshare` 有部分替代能力
  仓库现状：只有 `get_profit_forecast` 的局部版本
- `[未开发][P1]` 指数成分 / 行业成分 / 权重
  数据源已有：`tushare` `akshare` `wind` `ifind`
  仓库现状：无统一工具
- `[未开发][P1]` 基金数据
  数据源已有：`akshare` `tushare` `wind` `ifind`
  仓库现状：无统一工具
- `[未开发][P1]` 债券数据
  数据源已有：`akshare` `wind` `ifind`
  仓库现状：无 `AssetType.BOND`
- `[未开发][P1]` 期权数据
  数据源已有：`akshare` `wind` `ifind`
  仓库现状：无 `AssetType.OPTION`
- `[未开发][P1]` 日历类数据
  数据源已有：`akshare` `wind` `ifind`
  仓库现状：无统一工具
- `[未开发][P2]` 另类数据 / ESG / AI 预测
  数据源已有：`ifind` `wind`
  仓库现状：无统一工具

### P0: 应该最先补的

| 优先级 | 统一接口 | 当前状态 | 主要缺口 | 建议主源 -> 备源 |
| --- | --- | --- | --- | --- |
| P0 | `get_company_events` | 缺失统一接口 | 公告事件、业绩快报、停复牌、限售解禁、回购、增减持、股权质押、龙虎榜、大宗交易、机构调研、重大合同 | `wind -> ifind -> tushare -> akshare -> cninfo` |
| P0 | `get_financial_statements` | 不稳定 / 未形成正式统一工具 | 完整三大表、指标表、报表口径统一、周期切换、币种切换 | `wind -> ifind -> tushare -> akshare -> baostock` |
| P0 | `get_market_participant_data` | 部分分散存在 | 融资融券、北向持股、港股通持股、基金持仓、ETF 持仓、十大股东变动、机构席位行为 | `wind -> ifind -> tushare -> akshare` |
| P0 | `get_analyst_expectations` | 只有局部盈利预测 | 一致预期、评级、目标价、预测变动、研报摘要 | `wind -> ifind -> akshare` |

### P1: 第二阶段补齐研究面

| 优先级 | 统一接口 | 当前状态 | 主要缺口 | 建议主源 -> 备源 |
| --- | --- | --- | --- | --- |
| P1 | `get_index_constituents` | 缺失 | 指数成分、权重、样本调整、申万/中信/概念板块成分 | `wind -> ifind -> tushare -> akshare` |
| P1 | `get_industry_chain_data` | 缺失 | 产业链上下游、行业指标、产业映射、链路事件 | `ifind -> wind -> manual/akshare` |
| P1 | `get_fund_data` | 缺失正式工具 | 公募基金概况、净值、持仓、经理、规模、申赎、风格漂移 | `wind -> ifind -> tushare -> akshare` |
| P1 | `get_bond_data` | 完全缺失 | 利率债、信用债、可转债、到期收益率、久期、利差、发行信息 | `wind -> ifind -> akshare` |
| P1 | `get_option_data` | 完全缺失 | 期权链、IV、Greeks、成交持仓、到期结构 | `wind -> ifind -> akshare` |
| P1 | `get_fx_data` | 只有底层行情能力 | 货币对历史、利差、宏观驱动、央行路径 | `wind -> ifind -> yahoo/twelve_data/alpha_vantage` |
| P1 | `get_calendar_data` | 缺失 | 宏观日历、财报日历、分红日历、解禁日历、事件提醒 | `wind -> ifind -> akshare` |

### P2: 第三阶段做差异化

| 优先级 | 统一接口 | 当前状态 | 主要缺口 | 建议主源 -> 备源 |
| --- | --- | --- | --- | --- |
| P2 | `get_alt_data` | 缺失 | 舆情、新闻情感、供应链、工商、招聘、地图 / 出行 / 电商类另类数据 | `ifind -> wind -> external specialized source` |
| P2 | `get_esg_data` | 缺失 | ESG 评级、分项分数、争议事件 | `wind -> ifind` |
| P2 | `get_ai_forecast` | 缺失 | 宏观 / 行业 / 公司预测与 backtest 结果 | `ifind -> wind` |

## 5. 最值得先补的四个数据域

如果按投入产出比，我建议先做下面四类，而不是先扩到所有资产：

### 5.1 公司事件 `get_company_events`

这是 A 股研究最缺的一层，也是 AKShare / iFinD / Wind 都能明显补强的一层。

建议统一到一个接口里，通过 `categories` 参数控制：

- `announcement`
- `earnings_preview`
- `earnings_express`
- `suspension`
- `unlock`
- `buyback`
- `shareholder_change`
- `executive_change`
- `pledge`
- `block_trade`
- `dragon_tiger`
- `institutional_survey`
- `major_contract`

推荐原因：

- 与研究流程最贴近
- 可以直接串联“事件 -> 价格/资金/估值”
- 免费源也能先做基础版

### 5.2 完整财报 `get_financial_statements`

当前 `get_financial_reports` 更接近“财务趋势图”，不是完整财务数据接口。

建议正式补齐：

- `balance_sheet`
- `income_statement`
- `cash_flow`
- `financial_indicators`
- `report_summary`

并支持：

- `period_type`: annual / quarterly / ttm
- `periods`: 返回期数
- `currency`: local / CNY / USD / HKD

### 5.3 机构与资金行为 `get_market_participant_data`

当前资金流工具较多，但“机构行为”没有一个统一入口。

建议聚合：

- 融资融券
- 北向 / 港股通持股
- 基金 / ETF 持仓
- 十大股东 / 十大流通股东变动
- 机构席位 / 机构调研

这类数据对选股和行业研究都很关键。

### 5.4 一致预期与研报 `get_analyst_expectations`

当前 `get_profit_forecast` 只覆盖了一部分盈利预测。

建议统一到：

- 一致预期 EPS / Revenue / Net Profit
- 目标价
- 评级分布
- 评级变动
- 研报摘要

这类数据用 Wind / iFinD 质量会明显更高，AKShare 只能做基础 fallback。

## 6. 统一接口设计建议

### 6.1 设计原则

- 一个数据域只暴露一个 MCP 工具
- 工具名对齐“研究任务”，不要对齐数据源名
- adapter 层屏蔽字段差异
- tool 层不暴露源站原始 schema
- 返回结果要带来源说明和 fallback 轨迹

### 6.2 adapter 顺序建议

不同数据域的优先顺序不应完全一样：

- 行情 / K 线：`wind -> ifind -> tushare -> akshare -> baostock`
- 完整财报：`wind -> ifind -> tushare -> akshare -> baostock`
- 公告事件：`wind -> ifind -> tushare -> akshare -> cninfo`
- 一致预期 / 研报：`wind -> ifind -> akshare`
- 基金：`wind -> ifind -> tushare -> akshare`
- 债券 / 期权：`wind -> ifind -> akshare`
- 宏观：`wind -> ifind -> fred/tushare/akshare`

### 6.3 建议新增的 DataSource / AssetType

当前建议尽快补：

- `DataSource.WIND`
- `DataSource.IFIND`

当前建议尽快补的资产类型：

- `AssetType.BOND`
- `AssetType.OPTION`

否则后续基金、债券、期权工具会越来越别扭。

## 7. Markdown-first 输出规范

这是我认为应当和补数据并行推进的一个 P0 级改造。

### 7.1 现状问题

当前很多工具虽然返回了 `summary + artifact`，但实质上还是“给前端/程序看的结构化 JSON”，而不是“给 LLM 看的结构化 Markdown”。

问题在于：

- `summary` 往往只有一两行
- 关键结论没有标准化 section
- 表格和明细被塞在 `artifact.content`
- LLM 很难稳定抓住重点、来源、口径和异常说明

### 7.2 目标

所有对 LLM 暴露的工具返回，都应该至少包含一段完整 Markdown：

```markdown
## 结论
- 结论 1
- 结论 2

## 关键数据
| 指标 | 数值 | 说明 |
| --- | --- | --- |
| 指标A | 123 | 近四季 |

## 数据来源
- 主源: wind
- 备源: akshare
- 是否回退: 是

## 口径说明
- TTM 口径
- 单位: 亿元
```

### 7.3 建议的工具返回契约

建议后续统一成：

- `summary`: 完整 Markdown，直接给 LLM
- `artifact`: 继续保留，用于 UI / chart / table 渲染
- `metadata`: 补来源、回退、时间戳、单位、口径

不要再让工具直接把“原始大字典”暴露为主要阅读对象。

### 7.4 建议新增公共辅助函数

建议后续新增一个统一 helper，例如：

- `create_markdown_response()`
- `render_markdown_table()`
- `render_source_trace()`
- `render_metric_bullets()`

这样每个 MCP 工具都可以先拼 Markdown，再附带 artifact。

## 8. 推荐实施顺序

### 第 1 阶段

- 新增 `DataSource.WIND` / `DataSource.IFIND`
- 定义 `get_company_events` 统一 schema
- 定义 `get_financial_statements` 统一 schema
- 补 `create_markdown_response()` 公共 helper

### 第 2 阶段

- 先接 `AKShare / Tushare` 版本的 `company_events`
- 先接 `Tushare / AKShare` 版本的 `financial_statements`
- 把新工具输出先统一成 Markdown-first

### 第 3 阶段

- 增加 `WindAdapter` / `IFindAdapter`
- 为 `company_events` / `analyst_expectations` / `market_participant_data` 接入高质量主源

### 第 4 阶段

- 扩到基金 / 债券 / 期权 / 外汇
- 最后再做另类数据 / ESG / AI 预测

## 9. 我对本仓库的明确建议

如果只做一件事，先做：

1. `get_company_events`
2. Markdown-first 输出层

如果做两件事，再加：

3. `get_financial_statements`

如果做三件事，再加：

4. `get_market_participant_data`

原因很简单：

- 这三类数据最能把研究链条补完整
- 与现有 A 股研究工具天然互补
- 免费源先落地、付费源后增强的路径最顺
- 最符合“一个数据类别一个接口，adapter 自动择优 + 回退”的设计思路
