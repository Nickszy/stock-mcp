"""
总览页面
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime


def show(db, calculator, alert_manager, hours):
    """显示总览页面"""
    st.title("📈 数据质量总览")

    # 刷新按钮
    col_refresh, col_last_update = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 刷新", key="refresh_overview"):
            st.rerun()
    with col_last_update:
        st.markdown(f"**统计时间范围:** 最近 {hours} 小时")

    st.markdown("---")

    # ========== 第一行：关键指标卡片 ==========
    st.subheader("🎯 关键指标")

    # 获取数据源汇总
    source_summary = calculator.get_source_summary(hours=hours)

    if source_summary:
        col1, col2, col3, col4 = st.columns(4)

        # 计算总体指标
        total_requests = sum(s["total_requests"] for s in source_summary)
        avg_success_rate = (
            sum(s["success_rate"] * s["total_requests"] for s in source_summary) / total_requests
            if total_requests > 0
            else 0
        )
        avg_latency = (
            sum(s["avg_latency_ms"] * s["total_requests"] for s in source_summary) / total_requests
            if total_requests > 0
            else 0
        )

        with col1:
            st.metric(
                "总请求数",
                f"{total_requests:,}",
                delta=None,
            )

        with col2:
            st.metric(
                "平均成功率",
                f"{avg_success_rate:.1%}",
                delta=f"{(avg_success_rate - 0.95):.1%}" if avg_success_rate > 0.95 else None,
                delta_color="normal" if avg_success_rate >= 0.95 else "inverse",
            )

        with col3:
            st.metric(
                "平均延迟",
                f"{avg_latency:.0f}ms",
                delta=f"-{(2000 - avg_latency):.0f}ms" if avg_latency < 2000 else f"+{(avg_latency - 2000):.0f}ms",
                delta_color="inverse",
            )

        with col4:
            # 告警数
            alert_summary = alert_manager.get_alert_summary(hours=hours)
            st.metric(
                "告警数",
                f"{alert_summary['unresolved']}",
                delta=f"-{alert_summary['unresolved']}" if alert_summary["unresolved"] == 0 else None,
                delta_color="inverse",
            )

    st.markdown("---")

    # ========== 第二行：数据源健康度 ==========
    st.subheader("🏥 数据源健康度")

    if source_summary:
        # 创建数据源健康度表格
        df_sources = pd.DataFrame(source_summary)

        # 添加状态列
        df_sources["status"] = df_sources["success_rate"].apply(
            lambda x: "🟢 健康" if x >= 0.95 else ("🟡 降级" if x >= 0.90 else "🔴 故障")
        )

        # 格式化列
        df_sources_display = df_sources.copy()
        df_sources_display["success_rate"] = df_sources_display["success_rate"].apply(
            lambda x: f"{x:.1%}"
        )
        df_sources_display["avg_latency_ms"] = df_sources_display["avg_latency_ms"].apply(
            lambda x: f"{x:.0f}ms"
        )

        # 重命名列
        df_sources_display.columns = ["数据源", "成功率", "平均延迟", "总请求数", "状态"]

        st.dataframe(
            df_sources_display,
            use_container_width=True,
            hide_index=True,
        )

        # 绘制成功率柱状图
        fig = px.bar(
            df_sources,
            x="source",
            y="success_rate",
            color="success_rate",
            color_continuous_scale="RdYlGn",
            range_color=[0.7, 1.0],
            title="数据源成功率对比",
            labels={"source": "数据源", "success_rate": "成功率"},
        )
        fig.add_hline(y=0.95, line_dash="dash", line_color="green", annotation_text="目标 95%")
        fig.add_hline(y=0.90, line_dash="dash", line_color="orange", annotation_text="告警阈值 90%")

        st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("暂无数据源统计数据。请先进行数据请求。")

    st.markdown("---")

    # ========== 第三行：数据类型概览 ==========
    st.subheader("📊 数据类型概览")

    data_type_summary = calculator.get_data_type_summary(hours=hours)

    if data_type_summary:
        # 创建卡片布局
        cols = st.columns(len(data_type_summary))

        for idx, (data_type, summary) in enumerate(data_type_summary.items()):
            with cols[idx]:
                with st.container():
                    st.markdown(f"**{data_type.upper()}**")
                    st.metric(
                        "最佳数据源",
                        summary["best_source"],
                        delta=f"{summary['best_success_rate']:.1%}",
                    )
                    st.metric("平均成功率", f"{summary['avg_success_rate']:.1%}")
                    st.metric("平均延迟", f"{summary['avg_latency_ms']:.0f}ms")
                    st.caption(f"总请求: {summary['total_requests']:,}")

    st.markdown("---")

    # ========== 第四行：最近告警 ==========
    st.subheader("🚨 最近告警")

    recent_alerts = alert_manager.get_recent_alerts(hours=hours, limit=5)

    if recent_alerts:
        for alert in recent_alerts:
            severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🟢"}.get(
                alert.severity, "⚪"
            )
            resolved_text = "✅ 已解决" if alert.resolved else "⏳ 未解决"

            st.markdown(
                f"""
                {severity_emoji} **{alert.source or '系统'}** - {alert.message}
                - {alert.timestamp.strftime('%m-%d %H:%M')} | {resolved_text}
                """
            )
    else:
        st.success("✅ 最近没有告警")

    # 自动刷新（可选）
    st.markdown("---")
    auto_refresh = st.checkbox("自动刷新（30秒）", value=False)
    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()
