import asyncio
import csv
import json
from search import search_products
from scraper import get_product_details
from playwright.async_api import async_playwright

# 配置
CONFIG_FILE = "config.json"

# 读取配置
with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

SEARCH_QUERY = config["search_query"]
CSV_FILE = config["csv_file"]
OUTPUT_FILE = config["output_file"]
MAX_WORKERS = config["max_processes"]
MAX_PAGES = config["max_pages"]
COOKIES_FILE = config["cookies_file"]


async def worker(queue, context, results):
    """任务队列 Worker：从队列获取 ASIN 并爬取"""
    while not queue.empty():
        asin = await queue.get()
        print(f"🛒 任务队列领取 ASIN: {asin}")
        page = await context.new_page()
        product_data = await get_product_details(asin, page)
        await page.close()
        queue.task_done()  # **标记任务已完成**
        if product_data:
            results.append(product_data)  # **存储结果**


async def main():
    """主函数：创建任务队列 + 并行爬取"""
    asins = await search_products(SEARCH_QUERY, CSV_FILE, MAX_PAGES)

    if not asins:
        print("❌ 没有找到 ASIN，退出程序！")
        return

    queue = asyncio.Queue()

    # 添加所有 ASIN 到队列
    for asin in asins:
        await queue.put(asin)

    # 创建 Playwright 浏览器
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        # **加载 Amazon 登录 Cookies**
        try:
            with open(COOKIES_FILE, "r") as f:
                cookies = json.load(f)
                await context.add_cookies(cookies)
                print("✅ 已加载 Amazon 登录 Cookies")
        except:
            print("⚠️ 没有找到 Cookies，可能需要先运行 `login.py` 手动登录")
            await browser.close()
            return

        # 存储爬取结果
        results = []

        # 创建任务队列的 Workers（**创建和 ASIN 数量相同的任务**）
        tasks = [worker(queue, context, results)
                 for _ in range(min(len(asins), MAX_WORKERS))]

        await asyncio.gather(*tasks)  # **确保所有任务都执行完**

        # 关闭浏览器
        await browser.close()

    # 存入 CSV 文件
    with open(SEARCH_QUERY + OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["ASIN", "Title", "Price",
                        "URL", "Bought", "Frequently Returned"])

        for product_data in results:
            writer.writerow([product_data["asin"], product_data["title"], product_data["price"],
                             product_data["url"], product_data["bought"], product_data["frequently_returned"]])
            print(f"✅ 已存入 CSV: {product_data['title']}")

    print(f"\n🎉 所有商品信息已保存到 `{SEARCH_QUERY + OUTPUT_FILE}`！")

# 运行主函数
if __name__ == "__main__":
    asyncio.run(main())
