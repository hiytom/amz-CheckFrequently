import asyncio
from playwright.async_api import async_playwright
import json
import random
import pandas as pd
import time  # 用于统计时间
import re  # 引入正则库

COOKIES_FILE = "amazon_cookies.json"
OUTPUT_FILE = "amazon_products.csv"


async def get_variants_asins(page):
    """ 获取商品的变体 ASIN 列表 """
    variant_asins = set()
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
        # 随机延迟，减少风控
        await asyncio.sleep(random.uniform(0.5, 1.5))  # 减少延迟时间

        # 访问页面，等待 DOM 加载完成
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_selector("#productTitle", timeout=30000)

        # 获取商品标题
        title_element = await page.query_selector("#productTitle")
        title = await title_element.inner_text() if title_element else "Title not found"

        # 获取品牌（Brand）和品牌链接
        brand_element = await page.query_selector("#bylineInfo")
        brand = await brand_element.inner_text() if brand_element else "Brand not found"
        brand_link = await brand_element.get_attribute("href") if brand_element else None

        # **处理品牌字段**
        if "Visit the" in brand and "Store" in brand:
            brand = brand.replace("Visit the", "").replace("Store", "").strip()
        elif "Brand:" in brand:
            brand = brand.replace("Brand:", "").strip()
        # 只保留品牌名
        brand = re.sub(r'[^a-zA-Z0-9\s-]', '', brand).strip()

        # 如果品牌链接存在，则将其转换为完整的URL
        if brand_link and not brand_link.startswith("http"):
            brand_link = f"https://www.amazon.com{brand_link}"

        # 获取价格
        price = "Price not found"

        # **第一种方式：优先尝试 `a-offscreen`**
        price_element = await page.query_selector("span.a-offscreen")
        if price_element:
            price_text = await price_element.inner_text()
            if price_text.strip():
                price = price_text.strip()

        # **第二种方式：拼接 `a-price-whole` + `a-price-fraction`**
        if price == "Price not found":
            price_whole_element = await page.query_selector("span.a-price-whole")
            price_fraction_element = await page.query_selector("span.a-price-fraction")

            whole_text = (await price_whole_element.inner_text()).strip() if price_whole_element else ""
            fraction_text = (await price_fraction_element.inner_text()).strip() if price_fraction_element else ""

            # **去掉换行符和空格**
            whole_text = whole_text.replace(
                "\n", "").replace(" ", "").replace(".", "")
            fraction_text = fraction_text.replace("\n", "").replace(" ", "")

            # **合并价格**
            if whole_text and fraction_text:
                price = f"${whole_text}.{fraction_text}"
            elif whole_text:  # **只有整数部分**
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
                fabric_type_element = await fabric_element.evaluate_handle(
                    "el => el.parentElement.parentElement.nextElementSibling.querySelector('.a-color-base')"
                )
                fabric_type = await fabric_type_element.inner_text() if fabric_type_element else None

        # `Frequently returned item` 标签
        frequently_returned_element = await page.query_selector(
            "div#buyingOptionNostosBadge_feature_div .hrrv-badge-T2-title p span.a-text-bold"
        )
        frequently_returned = True if frequently_returned_element else False

        # 获取变体 ASIN
        variant_asins = await get_variants_asins(page)

        print(f"✅ 爬取成功")

        return {
            "asin": asin,
            "brand": brand,
            "brand_link": brand_link,  # 新增品牌链接
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
            return {"asin": asin, "retry": True}  # **返回 retry 标记**
        return None


async def test_scraper():
    """ 测试爬取单个 ASIN，并递归爬取所有变体 """
    test_asin = "B0C61QXH6F"
    scraped_data = {}
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
            product_info = await get_product_details(current_asin, page)

            if product_info:
                if product_info.get("retry"):  # **失败重试逻辑**
                    to_scrape.append(current_asin)  # **将失败的 ASIN 重新加入队列**
                else:
                    scraped_data[current_asin] = product_info

                    # **避免 KeyError: 'variants'**
                    if "variants" in product_info:
                        for variant_asin in product_info["variants"]:
                            if variant_asin not in seen_asins and variant_asin not in to_scrape:
                                to_scrape.append(variant_asin)

        await page.close()
        await browser.close()

        # 记录结束时间
        end_time = time.perf_counter()
        total_time = end_time - start_time  # 计算总爬取时间

        # 保存数据到 CSV
        df = pd.DataFrame(scraped_data.values())  # 直接转换为 DataFrame
        df.to_csv(OUTPUT_FILE, index=False)
        print(f"✅ 数据已保存到 {OUTPUT_FILE}")

        # **遍历 JSON 数据输出**
        print("\n🛒 爬取完成！所有数据如下：")
        for asin, data in scraped_data.items():
            print("=" * 50)
            print(f"ASIN: {asin}")  # **只打印一次**
            for key, value in data.items():
                if key != "asin":  # **避免 `asin` 重复打印**
                    print(f"{key}: {value}")

        # **打印爬取时间统计**
        print("=" * 50)
        print(f"⏱️ 总爬取时间: {total_time:.2f} 秒")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_scraper())
