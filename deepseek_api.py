import requests
import pandas as pd
from sqlalchemy import create_engine

# ------------------- DeepSeek API配置 -------------------
DEEPSEEK_API_KEY = "your_deepseek_api_key"  # 替换为你的API Key
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"  # 官方API端点

# ------------------- 数据库引擎（复用Streamlit的配置） -------------------
DB_CONFIG = {
    "host": "localhost",
    "user": "your_mysql_user",
    "password": "your_mysql_password",
    "database": "ecommerce_db"
}
engine = create_engine(f"mysql+pymysql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}/{DB_CONFIG['database']}")

# ------------------- Prompt模板（关键！指导AI生成正确SQL） -------------------
SYSTEM_PROMPT = """你是一个专业的电商数据分析师，负责将用户的自然语言问题转换为MySQL查询语句。
规则：
1. 只输出SQL语句，不添加任何解释、注释或多余内容。
2. 必须使用以下表结构和字段：
   - 表名：sales_analysis_wide_table
   - 关键字段：
     order_id, customer_id, order_status, order_purchase_timestamp,
     customer_state, geo_state, product_category_name_english, payment_value,
     review_score, payment_type 等（参考完整表结构）。
3. 确保SQL语法正确（如日期用DATE()函数，字符串用单引号）。
4. 若用户问题模糊，优先选择最合理的字段关联（如“销量”默认指payment_value总和）。

示例：
用户问题：“哪个州销量最高？”
输出：SELECT geo_state, SUM(payment_value) AS total_sales FROM sales_analysis_wide_table GROUP BY geo_state ORDER BY total_sales DESC LIMIT 1;
"""

# ------------------- 生成SQL（调用DeepSeek API） -------------------
def generate_sql(user_question: str) -> str:
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",  # 模型名称（根据实际调整）
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_question}
        ],
        "temperature": 0.2  # 降低随机性，保证SQL稳定性
    }
    response = requests.post(DEEPSEEK_URL, headers=headers, json=payload)
    response.raise_for_status()  # 抛出HTTP错误
    ai_response = response.json()["choices"][0]["message"]["content"].strip()
    return ai_response

# ------------------- 执行SQL并返回DataFrame -------------------
def execute_query(sql: str) -> pd.DataFrame:
    try:
        df = pd.read_sql(sql, engine)
        return df
    except Exception as e:
        raise ValueError(f"SQL执行失败：{str(e)}\nSQL语句：{sql}")