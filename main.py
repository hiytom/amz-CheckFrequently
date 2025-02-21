import asyncio
import csv
import json
from search import search_products
from scraper import get_product_details
from playwright.async_api import async_playwright
import time  # 用于统计时间

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
    """任务队列 Worker: 从队列获取 ASIN 并爬取"""
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

    # **✅ 动态提取字段，不写死**
    if not results:
        print("❌ 没有爬取到数据")
        return

    # **获取 CSV 头部（从第一个商品的数据动态提取）**
    fieldnames = list(results[0].keys())

    # **存入 CSV 文件**
    with open(SEARCH_QUERY + OUTPUT_FILE, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        # 读取字段列表，跳过 `url` 和 `brand_link` 字段
        field_names = [field for field in results[0].keys() if field not in [
            "url", "brand_link"]]

        # 写入表头
        writer.writerow(field_names)

        for product_data in results:
            # 将 ASIN 转换为超链接
            product_data["asin"] = f'=HYPERLINK("https://www.amazon.com/dp/{product_data["asin"]}", "{product_data["asin"]}")'

            # 将品牌链接转换为超链接
            if product_data.get("brand_link"):
                product_data["brand"] = f'=HYPERLINK("{product_data["brand_link"]}", "{product_data["brand"]}")'

            # 写入数据，跳过 `url` 和 `brand_link` 字段
            writer.writerow([product_data[field] for field in field_names])

    print(f"\n🎉 所有商品信息已保存到 `{SEARCH_QUERY + OUTPUT_FILE}`！")


# 运行主函数
if __name__ == "__main__":
    # 记录开始时间
    start_time = time.perf_counter()

    asyncio.run(main())

    # 记录结束时间
    end_time = time.perf_counter()

    # 计算并打印总耗时
    total_time = end_time - start_time
    print("=" * 50)
    print(f"⏳ 整个 `main.py` 运行时间: {total_time:.2f} 秒")
    print("=" * 50)
