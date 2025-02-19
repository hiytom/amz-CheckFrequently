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
    search_url = f"https://www.amazon.com/s?k={query.replace(' ', '+')}"
    asin_list = []
    current_page = 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 伪装真实浏览器
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        })

        print(f"🔍 正在搜索关键词: {query}")

        # 访问搜索页面
        await page.goto(search_url, timeout=90000)
        await page.wait_for_selector("div.s-main-slot", timeout=60000)

        while current_page <= max_pages:
            print(f"📄 正在爬取第 {current_page} 页...")

            # 获取 ASIN
            asin_elements = await page.query_selector_all("div.s-main-slot div[data-asin]")
            current_asins = [await elem.get_attribute("data-asin") for elem in asin_elements if await elem.get_attribute("data-asin")]

            if not current_asins:
                print("⚠️ 没有找到 ASIN，可能触发了反爬机制！")
                break

            print(f"✅ 第 {current_page} 页找到 {len(current_asins)} 个 ASIN")
            asin_list.extend(current_asins)

            # 休息 3-5 秒，降低反爬风险
            await asyncio.sleep(random.uniform(3, 5))

            # 处理翻页逻辑
            next_button = await page.query_selector('a.s-pagination-next')
            if current_page < max_pages and next_button and "s-pagination-disabled" not in (await next_button.get_attribute("class")):
                print("➡️ 翻页中...")
                await next_button.click()
                await asyncio.sleep(random.uniform(3, 5))  # 等待页面加载
                current_page += 1
            else:
                print("🚀 所有搜索结果已爬取完毕！")
                break

        await browser.close()

    # 存入 CSV 文件
    if asin_list:
        with open(csv_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["ASIN"])
            for asin in asin_list:
                writer.writerow([asin])
        print(f"✅ ASIN 列表已保存到 {csv_file}")

    return asin_list
