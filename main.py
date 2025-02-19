import csv
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from search import search_products
from scraper import get_product_details

# 配置
SEARCH_QUERY = "vintage apron"
CSV_FILE = "amazon_asins.csv"
OUTPUT_FILE = "amazon_listings.csv"
MAX_THREADS = 5  # 控制最大线程数，防止被封 IP

# 1️⃣ 获取 ASIN 列表
asins = search_products(SEARCH_QUERY, CSV_FILE)

if not asins:
    print("❌ 没有找到 ASIN，退出程序！")
    exit()

# 2️⃣ 处理爬取商品详情（使用多线程）


def process_asin(asin):
    product_data = get_product_details(asin)
    if product_data:
        return product_data
    return None


# 3️⃣ 存入 CSV
with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow(["ASIN", "Title", "Price", "URL",
                    "Frequently Returned"])  # CSV 表头

    # 使用多线程爬取
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_asin = {executor.submit(
            process_asin, asin): asin for asin in asins}

        for future in as_completed(future_to_asin):
            product_data = future.result()
            if product_data:
                writer.writerow([product_data["asin"], product_data["title"], product_data["price"],
                                 product_data["url"], product_data["frequently_returned"]])
                print(f"✅ 已存入 CSV: {product_data['title']}")

            # 防止被 Amazon 封 IP，线程间随机延迟
            time.sleep(random.uniform(3, 8))

print(f"\n🎉 所有商品信息已保存到 `{OUTPUT_FILE}`！")
