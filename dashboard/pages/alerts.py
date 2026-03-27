"""
告警页面
"""

import streamlit as st
import pandas as pd
from datetime import datetime


def show(alert_manager, db):
    """显示告警页面"""
    st.title("🚨 告警管理")

    # 告警汇总
    summary = alert_manager.get_alert_summary(hours=24)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("总告警", summary["total"])

    with col2:
        st.metric("🔴 严重", summary["critical"], delta_color="inverse")

    with col3:
        st.metric("🟡 警告", summary["warning"], delta_color="inverse")

    with col4:
        st.metric("未解决", summary["unresolved"], delta_color="inverse")

    st.markdown("---")

    # 过滤器
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        show_resolved = st.checkbox("显示已解决的告警", value=False)

    with col2:
        severity_filter = st.selectbox("告警级别", ["全部", "critical", "warning", "info"])

    with col3:
        hours = st.number_input("最近N小时", min_value=1, max_value=168, value=24)

    st.markdown("---")

    # 获取告警列表
    alerts = alert_manager.get_recent_alerts(hours=hours, limit=1000)

    # 过滤
    if not show_resolved:
        alerts = [a for a in alerts if not a.resolved]

    if severity_filter != "全部":
        alerts = [a for a in alerts if a.severity == severity_filter]

    # 显示告警
    if alerts:
        st.subheader(f"📋 告警列表 ({len(alerts)} 条)")

        for alert in alerts:
            severity_config = {
                "critical": {"emoji": "🔴", "color": "red"},
                "warning": {"emoji": "🟡", "color": "orange"},
                "info": {"emoji": "🟢", "color": "green"},
            }

            config = severity_config.get(alert.severity, {"emoji": "⚪", "color": "gray"})

            # 告警卡片
            with st.container():
                col1, col2, col3 = st.columns([0.1, 4, 1])

                with col1:
                    st.markdown(f"### {config['emoji']}")

                with col2:
                    st.markdown(
                        f"""
                        **{alert.message}**
                        - 数据源: {alert.source or '系统'} | 时间: {alert.timestamp.strftime('%m-%d %H:%M:%S')}
                        - 状态: {'✅ 已解决' if alert.resolved else '⏳ 未解决'}
                        """
                    )

                with col3:
                    if not alert.resolved:
                        if st.button("解决", key=f"resolve_{alert.id}"):
                            alert_manager.resolve_alert(alert.id)
                            st.success("告警已标记为解决")
                            st.rerun()

                st.markdown("---")

        # 批量操作
        st.subheader("🔧 批量操作")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("解决所有告警", type="primary"):
                unresolved_alerts = [a for a in alerts if not a.resolved]
                for alert in unresolved_alerts:
                    alert_manager.resolve_alert(alert.id)
                st.success(f"已解决 {len(unresolved_alerts)} 条告警")
                st.rerun()

        with col2:
            if st.button("刷新"):
                st.rerun()

    else:
        st.success("✅ 没有告警")

    st.markdown("---")

    # 告警规则说明
    st.subheader("📖 告警规则")

    st.markdown(
        """
        | 规则 | 条件 | 级别 |
        |------|------|------|
        | 成功率过低 | 成功率 < 80% | 🔴 Critical |
        | 成功率较低 | 成功率 < 90% | 🟡 Warning |
        | 延迟过高 | 平均延迟 > 10s | 🔴 Critical |
        | 延迟较高 | 平均延迟 > 5s | 🟡 Warning |
        | 无可用数据 | 数据可用率 = 0% | 🔴 Critical |
        """
    )

    st.markdown("---")

    # 手动创建告警（测试用）
    with st.expander("🧪 创建测试告警"):
        col1, col2, col3 = st.columns(3)

        with col1:
            test_source = st.selectbox(
                "数据源", ["tushare", "akshare", "yahoo", "finnhub", "system"]
            )

        with col2:
            test_severity = st.selectbox("级别", ["info", "warning", "critical"])

        with col3:
            test_message = st.text_input("消息", "这是一个测试告警")

        if st.button("创建告警"):
            from src.server.monitoring.models import Alert

            alert = Alert(
                source=test_source,
                severity=test_severity,
                message=test_message,
            )
            alert_manager.db.create_alert(alert)
            st.success("告警已创建")
            st.rerun()
