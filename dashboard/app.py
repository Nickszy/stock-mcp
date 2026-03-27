"""
Stock MCP 数据质量监控 Dashboard

启动命令:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

from src.server.monitoring import MonitoringDB, MetricsCalculator, AlertManager

# 隐藏默认导航栏
st.markdown("""
<style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# 页面配置
st.set_page_config(
    page_title="Stock MCP 数据质量监控",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化（使用缓存避免重复初始化）
@st.cache_resource
def init_db():
    """初始化数据库"""
    db_path = project_root / "monitoring.db"
    return MonitoringDB(str(db_path))

@st.cache_resource
def init_calculator(_db):
    """初始化指标计算器"""
    return MetricsCalculator(_db)

@st.cache_resource
def init_alert_manager(_db):
    """初始化告警管理器"""
    return AlertManager(_db)

# 初始化组件
db = init_db()
calculator = init_calculator(db)
alert_manager = init_alert_manager(db)

# 侧边栏
st.sidebar.title("📊 数据质量监控")
st.sidebar.markdown("---")

# 导航
page = st.sidebar.radio(
    "导航",
    ["📈 总览", "📋 数据报告", "📜 历史记录", "🚨 告警"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 时间范围")
hours = st.sidebar.slider("统计最近N小时", 1, 168, 24, 1)

# 根据选择显示不同页面
if page == "📈 总览":
    from pages import overview as overview_page
    overview_page.show(db, calculator, alert_manager, hours)
elif page == "📋 数据报告":
    from pages import data_quality_report as report_page
    report_page.show(db, project_root)
elif page == "📜 历史记录":
    from pages import history as history_page
    history_page.show(db, calculator, hours)
elif page == "🚨 告警":
    from pages import alerts as alerts_page
    alerts_page.show(alert_manager, db)

# 页脚
st.sidebar.markdown("---")
st.sidebar.markdown(
    f"""
    <div style='text-align: center; color: gray; font-size: 12px;'>
        最后更新: {datetime.now().strftime('%H:%M:%S')}
    </div>
    """,
    unsafe_allow_html=True,
)
