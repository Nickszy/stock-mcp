"""
历史记录页面
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime


def show(db, calculator, hours):
    """显示历史记录页面"""
    st.title("📜 历史记录")

    # 过滤器
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        filter_source = st.selectbox(
            "数据源",
            ["全部"] + ["tushare", "akshare", "baostock", "yahoo", "finnhub", "fred"],
        )

    with col2:
        filter_data_type = st.selectbox(
            "数据类型",
            ["全部"] + ["price", "financials", "news", "event", "macro"],
        )

    with col3:
        limit = st.number_input("显示数量", min_value=10, max_value=1000, value=100, step=10)

    st.markdown("---")

    # 查询日志
    source_filter = None if filter_source == "全部" else filter_source
    data_type_filter = None if filter_data_type == "全部" else filter_data_type

    logs = db.get_logs(
        source=source_filter,
        data_type=data_type_filter,
        hours=hours,
        limit=limit,
    )

    if logs:
        # ========== 趋势图 ==========
        st.subheader("📈 请求趋势")

        # 转换为 DataFrame
        df = pd.DataFrame([log.to_dict() for log in logs])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        # 按小时聚合
        df["hour"] = df["timestamp"].dt.floor("H")
        hourly_stats = (
            df.groupby(["hour", "source"])
            .agg({"id": "count", "latency_ms": "mean", "status": lambda x: (x == "success").sum() / len(x)})
            .reset_index()
        )
        hourly_stats.columns = ["时间", "数据源", "请求数", "平均延迟", "成功率"]

        # 绘制请求数趋势
        fig1 = px.line(
            hourly_stats,
            x="时间",
            y="请求数",
            color="数据源",
            title="请求数趋势",
        )
        st.plotly_chart(fig1, use_container_width=True)

        # 绘制成功率趋势
        fig2 = px.line(
            hourly_stats,
            x="时间",
            y="成功率",
            color="数据源",
            title="成功率趋势",
        )
        fig2.add_hline(y=0.95, line_dash="dash", line_color="green")
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")

        # ========== 详细记录表 ==========
        st.subheader("📋 详细记录")

        # 格式化显示
        df_display = df.copy()
        df_display["时间"] = df_display["timestamp"].dt.strftime("%m-%d %H:%M:%S")
        df_display["延迟"] = df_display["latency_ms"].apply(lambda x: f"{x:.0f}ms")
        df_display["状态"] = df_display["status"].apply(
            lambda x: "✅" if x == "success" else "❌"
        )

        # 选择要显示的列
        columns_to_show = ["时间", "source", "data_type", "instrument_id", "状态", "延迟", "error_message"]
        df_display = df_display[columns_to_show]
        df_display.columns = ["时间", "数据源", "数据类型", "标的", "状态", "延迟", "错误信息"]

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        # 导出功能
        col_export1, col_export2 = st.columns([1, 4])
        with col_export1:
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 导出 CSV",
                data=csv,
                file_name=f"monitoring_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

    else:
        st.info("暂无历史记录")

    st.markdown("---")

    # ========== 质量指标统计 ==========
    st.subheader("📊 质量指标统计")

    metrics = calculator.calculate_all_metrics(hours=hours)

    if metrics:
        # 创建指标表格
        metrics_list = []
        for source, data_types in metrics.items():
            for data_type, m in data_types.items():
                metrics_list.append(
                    {
                        "数据源": source,
                        "数据类型": data_type,
                        "成功率": f"{m.success_rate:.1%}",
                        "平均延迟": f"{m.avg_latency_ms:.0f}ms",
                        "总请求": m.total_requests,
                        "成功数": m.success_count,
                        "失败数": m.failed_count,
                    }
                )

        df_metrics = pd.DataFrame(metrics_list)
        st.dataframe(df_metrics, use_container_width=True, hide_index=True)
