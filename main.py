import csv
import time
import random
from multiprocessing import Pool
from search import search_products
from scraper import get_product_details
from playwright.sync_api import sync_playwright
import json

# 读取配置文件
with open("config.json", "r") as f:
    config = json.load(f)

SEARCH_QUERY = config["search_query"]
CSV_FILE = config["csv_file"]
OUTPUT_FILE = config["output_file"]
MAX_PROCESSES = config["max_processes"]
MAX_PAGES = config["max_pages"]
COOKIES_FILE = config["cookies_file"]


def process_asin(asin):
    """让每个 ASIN 独立运行 Playwright"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # **加载 Amazon 登录 Cookies**
        try:
            with open("amazon_cookies.json", "r") as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
        except:
            print("⚠️ 没有找到 Cookies，可能需要先运行 `login.py` 手动登录")
            return None

        page = context.new_page()
        product_data = get_product_details(asin, page)

        page.close()
        browser.close()
        return product_data


if __name__ == "__main__":
    # 1️⃣ 获取 ASIN 列表
    asins = search_products(SEARCH_QUERY, CSV_FILE)

    if not asins:
        print("❌ 没有找到 ASIN，退出程序！")
        exit()

    # 2️⃣ **使用 `multiprocessing.Pool()` 进行并行爬取**
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["ASIN", "Title", "Price", "URL",
                        "Frequently Returned"])  # **CSV 表头**

        with Pool(processes=MAX_PROCESSES) as pool:
            results = pool.map(process_asin, asins)  # **确保只传递 ASIN**

            for product_data in results:
                if product_data:
                    writer.writerow([product_data["asin"], product_data["title"], product_data["price"],
                                    product_data["url"], product_data["frequently_returned"]])
                    print(f"✅ 已存入 CSV: {product_data['title']}")

    print(f"\n🎉 所有商品信息已保存到 `{OUTPUT_FILE}`！")
