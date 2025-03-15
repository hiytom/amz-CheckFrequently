from playwright.async_api import async_playwright
import asyncio
import random
import csv

async def search_products(query, csv_file, max_pages=1):
    """
    搜索 Amazon 关键词，获取 ASIN 列表，并存入 CSV。

    :param query: 搜索关键词
    :param csv_file: 存储 ASIN 的 CSV 文件路径
    :param max_pages: 最大翻页数（默认 1）
    :return: ASIN 列表
    """
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"  # 构造搜索 URL
    asin_list = []  # 存储所有 ASIN
    current_page = 1  # 当前页码

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # 启动无头浏览器
        page = await browser.new_page()  # 创建新页面

        # 伪装真实浏览器，设置请求头
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        })

        print(f"🔍 正在搜索关键词: {query}")  # 显示搜索关键词
        await page.goto(search_url, timeout=90000)  # 访问搜索页面
        await page.wait_for_selector("div.s-main-slot", timeout=60000)  # 等待搜索结果加载

        while current_page <= max_pages:
            print(f"📄 正在爬取第 {current_page} 页...")
            # 获取当前页的 ASIN
            asin_elements = await page.query_selector_all("div.s-main-slot div[data-asin]")
            current_asins = [await elem.get_attribute("data-asin") for elem in asin_elements if await elem.get_attribute("data-asin")]

            if not current_asins:  # 如果未找到 ASIN，可能触发反爬
                print("⚠️ 没有找到 ASIN，可能触发了反爬机制！")
                break

            print(f"✅ 第 {current_page} 页找到 {len(current_asins)} 个 ASIN")
            asin_list.extend(current_asins)  # 添加到总列表

            # 随机休息 3-5 秒，降低反爬风险
            await asyncio.sleep(random.uniform(3, 5))

            # 处理翻页逻辑
            next_button = await page.query_selector('a.s-pagination-next')
            class_attr = (await next_button.get_attribute("class")) or "" if next_button else ""
            if current_page < max_pages and next_button and "s-pagination-disabled" not in class_attr:
                print("➡️ 翻页中...")
                await next_button.click()
                await asyncio.sleep(random.uniform(3, 5))  # 等待页面加载
                current_page += 1
            else:
                print(f"🚀 所有搜索结果已爬取完毕！共找到 {len(asin_list)} 个 ASIN")  # 输出总 ASIN 数
                break

        await browser.close()  # 关闭浏览器

    # 将 ASIN 存入 CSV 文件
    if asin_list:
        with open(csv_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["ASIN"])  # 写入表头
            for asin in asin_list:
                writer.writerow([asin])  # 写入每行 ASIN
        print(f"✅ ASIN 列表已保存到 {csv_file}")

    return asin_list  # 返回 ASIN 列表

# 程序入口（仅用于独立测试）
if __name__ == "__main__":
    asyncio.run(search_products("floral apron", "amazon_asins.csv", 7))