import asyncio
from playwright.async_api import async_playwright
import json
import random
import pandas as pd
import time  # 用于统计时间

COOKIES_FILE = "amazon_cookies.json"
OUTPUT_FILE = "amazon_products.csv"


async def get_variants_asins(page):
    """ 获取商品的变体 ASIN 列表 """
    variant_asins = set()

    # 变体 ASIN 可能在 data-asin, data-defaultasin, 或 data-csa-c-asin
    variant_elements = await page.query_selector_all("li[data-asin], div[data-defaultasin], div[data-csa-c-asin]")

    for elem in variant_elements:
        asin = await elem.get_attribute("data-asin") or await elem.get_attribute("data-defaultasin") or await elem.get_attribute("data-csa-c-asin")
        if asin:
            variant_asins.add(asin.strip())

    return list(variant_asins)


async def get_product_details(asin, page):
    """爬取商品详情"""
    url = f"https://www.amazon.com/dp/{asin}"
    print(f"📦 正在爬取商品详情: {url}")

    try:
        await asyncio.sleep(random.uniform(1, 3))  # 随机延迟，减少风控
        await page.goto(url, timeout=90000)
        await page.wait_for_selector("#productTitle", timeout=60000)

        # 获取商品标题
        title_element = await page.query_selector("#productTitle")
        title = await title_element.inner_text() if title_element else "Title not found"

        # 获取价格
        price = "Price not found"

        # **第一种方式：优先尝试 `a-offscreen`，因为它通常包含完整价格**
        price_element = await page.query_selector("span.a-offscreen")
        if price_element:
            price_text = await price_element.inner_text()
            if price_text.strip():
                price = price_text.strip()

        # **第二种方式：如果 `a-offscreen` 找不到，则拼接 `a-price-whole` + `a-price-fraction`**
        if price == "Price not found":
            price_whole_element = await page.query_selector("span.a-price-whole")
            price_fraction_element = await page.query_selector("span.a-price-fraction")

            whole_text = (await price_whole_element.inner_text()).strip() if price_whole_element else ""
            fraction_text = (await price_fraction_element.inner_text()).strip() if price_fraction_element else ""

            # **去掉换行符和空格**
            whole_text = whole_text.replace("\n", "").replace(" ", "")
            fraction_text = fraction_text.replace("\n", "").replace(" ", "")

            # **确保 `.` 只出现一次**
            if whole_text.endswith("."):
                whole_text = whole_text[:-1]  # 去掉 `.`

            if whole_text and fraction_text:
                price = f"${whole_text}.{fraction_text}"
            elif whole_text:  # 只有整数部分
                price = f"${whole_text}"
            else:
                price = "Price not found"

        # 获取上月销量
        bought_element = await page.query_selector("#social-proofing-faceout-title-tk_bought .a-text-bold")
        bought = (await bought_element.inner_text()).split()[0] if bought_element else "< 50"

        # 获取 fabric_type
        fabric_type = None
        details_section = await page.query_selector("#productFactsDesktopExpander")

        if details_section:
            fabric_element = await details_section.query_selector("span.a-color-base:has-text('Fabric type')")
            if fabric_element:
                fabric_type_element = await fabric_element.evaluate_handle("el => el.parentElement.parentElement.nextElementSibling.querySelector('.a-color-base')")
                fabric_type = await fabric_type_element.inner_text() if fabric_type_element else None

        # `Frequently returned item` 标签
        frequently_returned_element = await page.query_selector("div#buyingOptionNostosBadge_feature_div .hrrv-badge-T2-title p span.a-text-bold")
        frequently_returned = True if frequently_returned_element else False

        # 获取变体 ASIN
        variant_asins = await get_variants_asins(page)

        print(
            f"✅ 爬取成功: {title} - {price} - {bought} - Frequently Returned: {frequently_returned} - Variants: {len(variant_asins)}")

        return {
            "asin": asin,
            "title": title,
            "price": price,
            "bought": bought,
            "fabric_type": fabric_type,
            "url": url,
            "frequently_returned": frequently_returned,
            "variants": variant_asins
        }

    except Exception as e:
        print(f"❌ 爬取失败: {asin}，错误: {e}")
        if "ERR_ABORTED" in str(e):
            print(f"⚠️ ASIN {asin} 加入重试队列")
            return {"asin": asin, "retry": True}
        return None


async def test_scraper():
    """ 测试爬取单个 ASIN，并递归爬取所有变体 """
    test_asin = "B0C61QXH6F"
    scraped_data = []
    to_scrape = [test_asin]
    seen_asins = set()
    # 记录开始时间
    start_time = time.perf_counter()

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

        page = await context.new_page()

        while to_scrape:
            current_asin = to_scrape.pop(0)
            if current_asin in seen_asins:
                continue

            seen_asins.add(current_asin)
            product_data = await get_product_details(current_asin, page)

            if product_data:
                if product_data.get("retry"):
                    to_scrape.append(current_asin)  # 失败的 ASIN 重新加入队列
                else:
                    scraped_data.append(product_data)
                    for variant_asin in product_data["variants"]:
                        if variant_asin not in seen_asins and variant_asin not in to_scrape:
                            to_scrape.append(variant_asin)

        await page.close()
        await browser.close()

        # 记录结束时间
        end_time = time.perf_counter()
        total_time = end_time - start_time  # 计算总爬取时间

        # 保存数据到 CSV
        df = pd.DataFrame(scraped_data)
        df.to_csv(OUTPUT_FILE, index=False)
        print(f"✅ 数据已保存到 {OUTPUT_FILE}")

        # 打印所有爬取结果
        print("\n🛒 爬取完成！所有数据如下：")
        for data in scraped_data:
            print("=" * 50)
            print(f"ASIN: {data['asin']}")
            print(f"Title: {data['title']}")
            print(f"Price: {data['price']}")
            print(f"Bought: {data['bought']}")
            print(f"FabricType: {data['fabric_type']}")
            print(f"URL: {data['url']}")
            print(f"Frequently Returned: {data['frequently_returned']}")
            print(f"Variants: {len(data['variants'])}")

        # 打印爬取时间统计
        print("=" * 50)
        print(f"⏱️ 总爬取时间: {total_time:.2f} 秒")
        print("=" * 50)

if __name__ == "__main__":
    asyncio.run(test_scraper())
