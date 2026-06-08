import pandas as pd
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# --- 配置部分 ---
DB_USER = os.getenv('MYSQL_USER', 'root')
DB_PASS = os.getenv('MYSQL_PASSWORD', '') # 如果没有密码留空
DB_HOST = os.getenv('MYSQL_HOST', 'localhost')
DB_PORT = os.getenv('MYSQL_PORT', '3306')
DB_NAME = os.getenv('DB_NAME', 'ecommerce_db') # 确保这里和你Navicat里的名字一致

# 构建连接字符串 (注意：先不指定数据库名，以便我们先检查/创建数据库)
base_url = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}"
engine_base = create_engine(base_url)

# 指定具体数据库的连接
full_url = f"{base_url}/{DB_NAME}"
engine = create_engine(full_url)

# 数据文件夹路径
DATA_DIR = './olist-data'

def check_and_create_db():
    """检查数据库是否存在，不存在则创建"""
    print(f"正在检查数据库: {DB_NAME} ...")
    with engine_base.connect() as conn:
        # 查询所有数据库
        result = conn.execute(text("SHOW DATABASES"))
        databases = [row[0] for row in result]

        if DB_NAME not in databases:
            print(f"⚠️ 数据库 '{DB_NAME}' 不存在，正在自动创建...")
            conn.execute(text(f"CREATE DATABASE {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            print("✅ 数据库创建成功！")
        else:
            print(f"✅ 数据库 '{DB_NAME}' 已存在。")

def load_and_clean_data():
    """读取 CSV 并写入 MySQL"""
    print("开始处理原始数据集...")

    # 定义文件名映射 (CSV文件名 -> 数据库表名)
    file_map = {
        'olist_customers_dataset': 'customers',
        'olist_geolocation_dataset': 'geolocation',
        'olist_order_items_dataset': 'order_items',
        'olist_order_payments_dataset': 'order_payments',
        'olist_order_reviews_dataset': 'order_reviews',
        'olist_orders_dataset': 'orders',
        'olist_products_dataset': 'products',
        'olist_sellers_dataset': 'sellers',
        'product_category_name_translation': 'category_translation'
    }

    for csv_prefix, table_name in file_map.items():
        # 尝试寻找 .csv 或 .xls/.xlsx (虽然Olist通常是csv，但以防万一)
        csv_path = os.path.join(DATA_DIR, f"{csv_prefix}.csv")

        if os.path.exists(csv_path):
            try:
                # 读取 CSV
                df = pd.read_csv(csv_path)

                # 简单的列名清洗（去除空格）
                df.columns = [c.strip() for c in df.columns]

                # 写入数据库 (如果存在则替换)
                df.to_sql(table_name, engine, if_exists='replace', index=False)
                print(f"✅ 表 {table_name} 已更新 ({len(df)} 行)")

            except Exception as e:
                print(f"❌ 读取 {csv_prefix} 失败: {e}")
        else:
            print(f"⚠️ 未找到文件: {csv_path}")

def build_wide_table():
    """构建用于分析的宽表"""
    print("\n开始构建销售分析宽表 (sales_wide_table)...")

    try:
        # 1. 从数据库读取各分表数据
        orders = pd.read_sql_table('orders', engine)
        customers = pd.read_sql_table('customers', engine)
        items = pd.read_sql_table('order_items', engine)
        payments = pd.read_sql_table('order_payments', engine)
        reviews = pd.read_sql_table('order_reviews', engine)
        products = pd.read_sql_table('products', engine)
        sellers = pd.read_sql_table('sellers', engine)

        # 尝试读取翻译表 (如果之前没导入成功，这里会跳过)
        translation = None
        try:
            translation = pd.read_sql_table('category_translation', engine)
        except ValueError:
            print("ℹ️ 未找到翻译表，将使用原始分类名称进行分析。")

        # 2. 逐步合并 (Merge)

        # 订单 + 客户
        df = orders.merge(customers, on='customer_id', how='left')

        # + 订单项 (获取价格和商品ID)
        df = df.merge(items[['order_id', 'product_id', 'seller_id', 'price', 'freight_value']], on='order_id', how='left')

        # + 商品详情 (获取类别、重量等)
        df = df.merge(products[['product_id', 'product_category_name', 'product_weight_g', 'product_length_cm']], on='product_id', how='left')

        # + 卖家信息
        df = df.merge(sellers[['seller_id', 'seller_city', 'seller_state']], on='seller_id', how='left')

        # + 支付信息 (为了计算总支付金额，可能需要聚合，这里简单左连取主要支付方式)
        # 注意：一个订单可能有多笔支付，直接 merge 会导致行数膨胀。
        # 这里我们只取每笔订单的总支付额进行合并演示，或者稍后在SQL层处理。
        # 为简化 Pandas 操作，我们先聚合 payment 表
        payment_agg = payments.groupby('order_id')['payment_value'].sum().reset_index()
        df = df.merge(payment_agg, on='order_id', how='left')

        # + 评价分数
        df = df.merge(reviews[['order_id', 'review_score']], on='order_id', how='left')

        # 3. 处理分类名称 (关键修复点)
        if translation is not None:
            # 如果有翻译表，就合并翻译成中文/英文
            df = df.merge(translation, left_on='product_category_name', right_on='product_category_name', how='left')
            # 假设翻译表里有一列叫 'product_category_name_english'
            # 如果没有这列，请检查你的 translation.csv 内容
            if 'product_category_name_english' in df.columns:
                 df['category_display'] = df['product_category_name_english']
            else:
                 df['category_display'] = df['product_category_name'] # fallback
        else:
            # 没有翻译表，直接用原名
            df['category_display'] = df['product_category_name']

        # 4. 时间格式转换
        df['order_purchase_timestamp'] = pd.to_datetime(df['order_purchase_timestamp'])
        df['order_year'] = df['order_purchase_timestamp'].dt.year
        df['order_month'] = df['order_purchase_timestamp'].dt.month

        # 5. 写入最终的宽表
        # 选择需要的列写入，避免表太大
        final_cols = [
            'order_id', 'customer_id', 'order_purchase_timestamp',
            'order_year', 'order_month',
            'price', 'freight_value', 'payment_value', 'review_score',
            'product_category_name', 'category_display',
            'product_weight_g',
            'seller_city', 'seller_state',
            'customer_city', 'customer_state'
        ]

        # 过滤掉可能因合并产生的重复列或不存在的列
        existing_cols = [c for c in final_cols if c in df.columns]

        df_final = df[existing_cols]

        df_final.to_sql('sales_wide_table', engine, if_exists='replace', index=False)
        print(f"✅ 宽表构建完成！共 {len(df_final)} 条记录。")

    except Exception as e:
        print(f"❌ 构建宽表失败: {e}")

if __name__ == "__main__":
    # 1. 确保数据库存在
    check_and_create_db()

    # 2. 导入数据
    load_and_clean_data()

    # 3. 构建宽表
    build_wide_table()

    print("\n🎉 所有数据处理任务结束！可以运行 app.py 了。")