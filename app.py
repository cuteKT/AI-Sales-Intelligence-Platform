import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from openai import OpenAI
import os
from dotenv import load_dotenv

# --- 1. 初始化配置 ---
st.set_page_config(page_title="电商智能分析平台", layout="wide")
st.title("📊 电商数据分析仪表盘 & AI 顾问")

load_dotenv()

# 获取环境变量
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DB_USER = os.getenv("MYSQL_USER")
DB_PASS = os.getenv("MYSQL_PASSWORD")
DB_HOST = os.getenv("MYSQL_HOST", "localhost")
DB_PORT = os.getenv("MYSQL_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "ecommerce_db")

# 数据库连接字符串 (加上 charset 防止中文乱码)
DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

# 初始化 Session State
if 'messages' not in st.session_state:
    st.session_state.messages = []

# --- 2. 数据库工具函数 ---
@st.cache_resource
def get_engine():
    try:
        return create_engine(DATABASE_URI)
    except Exception as e:
        st.error(f"数据库连接失败: {e}")
        return None

def run_query(query):
    engine = get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
            return df
    except Exception as e:
        return None

# --- 3. 首页仪表盘区域 ---
st.header("📈 核心指标概览")

# 尝试加载基础数据用于计算 KPI
df_kpi = run_query("SELECT COUNT(DISTINCT order_id) as orders, SUM(price) as sales, AVG(review_score) as score FROM sales_wide_table LIMIT 5000")

if df_kpi is not None and not df_kpi.empty:
    col1, col2, col3 = st.columns(3)
    col1.metric("总销售额 (BRL)", f"R$ {df_kpi['sales'].iloc[0]:,.0f}")
    col2.metric("总订单量", f"{int(df_kpi['orders'].iloc[0]):,}")
    col3.metric("平均评分", f"{df_kpi['score'].iloc[0]:.1f} / 5.0")

    # 标签页切换不同维度的分析
    tab1, tab2, tab3 = st.tabs(["📉 销售趋势", "🏆 热销产品 TOP10", "🌍 热销城市 TOP10"])

    with tab1:
        df_trend = run_query("SELECT DATE(order_purchase_timestamp) as date, SUM(price) as sales FROM sales_wide_table GROUP BY date ORDER BY date DESC LIMIT 90")
        if df_trend is not None:
            fig = px.line(df_trend, x='date', y='sales', title="近90天销售趋势")
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        df_prod = run_query("SELECT product_category_name, SUM(price) as sales FROM sales_wide_table GROUP BY product_category_name ORDER BY sales DESC LIMIT 10")
        if df_prod is not None:
            fig = px.bar(df_prod, x='product_category_name', y='sales', title="Top 10 热销品类")
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        df_city = run_query("SELECT customer_city, SUM(price) as sales FROM sales_wide_table GROUP BY customer_city ORDER BY sales DESC LIMIT 10")
        if df_city is not None:
            fig = px.bar(df_city, x='customer_city', y='sales', title="Top 10 热销城市")
            st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("⚠️ 无法连接到数据库或表不存在，请检查 data_clean.py 是否已运行。")

st.divider()

# --- 4. AI 经营顾问区域 (修复重点：确保此部分显示) ---
st.header("🤖 AI 经营顾问")
st.caption("支持深度分析，例如：'为什么最近销量下降？' 或 '上个月哪个州卖得最好？'")

# 显示历史消息
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 输入框 (关键代码)
if prompt := st.chat_input("请输入你的问题..."):
    # 1. 显示用户问题
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. AI 思考与回复
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        if not DEEPSEEK_API_KEY:
            full_response = "❌ 请在 .env 文件中配置 DEEPSEEK_API_KEY。"
        else:
            try:
                # 构建系统提示词 - 增强版
                system_prompt = """
                你是一个资深的电商数据分析师和经营顾问。
                你是商业分析师。

                只能依据数据库返回结果分析。

                如果没有证据支持原因推断：

                必须回答：

                “当前数据无法证明具体原因，需要更多业务数据支持。”
                数据库表名：sales_wide_table。
                关键字段：price(价格), order_id(订单号), customer_state(州), product_category_name(品类), order_purchase_timestamp(时间), review_score(评分)。

                任务：
                1. 将用户的自然语言转化为 MySQL SQL 语句。
                2. 如果用户问“为什么销量下降”等复杂问题，请先查询最近两个月的销售总额对比，再查询各品类的销售变化，最后查询差评率。
                3. 根据查询到的数据，给出具体的业务建议（如：优化物流、促销特定品类）。

                注意：
                - 只返回纯 SQL 语句，不要包含 Markdown 格式（如 ```sql）。
                - 日期处理请使用 MySQL 语法：DATE_FORMAT(order_purchase_timestamp, '%Y-%m') 或 YEAR()/MONTH()。
                - 严禁使用 DATE_TRUNC。
                """

                client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
                )

                sql_query = response.choices[0].message.content.strip()

                # 简单的安全检查
                if not sql_query.upper().startswith("SELECT"):
                     full_response = "⚠️ AI 生成的不是查询语句。"
                else:
                    # 执行 SQL
                    result_df = run_query(sql_query)

                    if result_df is not None and not result_df.empty:
                        # 构造给 AI 的二次 Prompt，让它解释数据
                        analysis_prompt = f"""
                        用户问题是：{prompt}
                        我执行的 SQL 是：{sql_query}
                        查询结果数据如下：
                        {result_df.to_string()}

                        请根据以上数据回答用户的问题。如果是分析类问题，请给出原因和建议。
                        """

                        final_response = client.chat.completions.create(
                            model="deepseek-chat",
                            messages=[{"role": "user", "content": analysis_prompt}]
                        )
                        full_response = final_response.choices[0].message.content

                        # 在界面上展示数据和文字
                        st.dataframe(result_df, hide_index=True)
                        st.markdown("---")
                        st.markdown(full_response)
                    else:
                        full_response = "😕 抱歉，我没有查到相关数据，或者 SQL 生成有误。"
                        st.code(sql_query, language="sql")

            except Exception as e:
                full_response = f"❌ AI 出错了: {str(e)}"

        # 更新对话历史
        message_placeholder.markdown(full_response)
        st.session_state.messages.append({"role": "assistant", "content": full_response})