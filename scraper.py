import asyncio
from playwright.async_api import async_playwright
import json
import random
import pandas as pd
import time  # 用于统计时间
import re  # 引入正则库

COOKIES_FILE = "amazon_cookies.json"
OUTPUT_FILE = "amazon_products.csv"
MAX_RETRIES = 3  # 最大重试次数


async def get_variants_asins(page):
    """ 获取商品的变体 ASIN 列表 """
    variant_asins = set()
    variant_elements = await page.query_selector_all("li[data-asin], div[data-defaultasin], div[data-csa-c-asin]")

    for elem in variant_elements:
        asin = await elem.get_attribute("data-asin") or await elem.get_attribute("data-defaultasin") or await elem.get_attribute("data-csa-c-asin")
        if asin:
            variant_asins.add(asin.strip())

    return list(variant_asins)


async def get_product_details(asin, page, retry_count=0):
    """爬取商品详情"""
    url = f"https://www.amazon.com/dp/{asin}"
    print(f"📦 正在爬取商品详情: {url}")

    try:
        # 随机延迟，减少风控（保持范围较小）
        await asyncio.sleep(random.uniform(0.2, 0.8))

        # 恢复 domcontentloaded，只等待主要内容加载
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
        brand = re.sub(r'[^a-zA-Z0-9\s-]', '', brand).strip()

        if brand_link and not brand_link.startswith("http"):
            brand_link = f"https://www.amazon.com{brand_link}"

        # 获取价格
        price = "Price not found"
        price_element = await page.query_selector("span.a-offscreen")
        if price_element:
            price_text = await price_element.inner_text()
            if price_text.strip():
                price = price_text.strip()

        if price == "Price not found":
            price_whole_element = await page.query_selector("span.a-price-whole")
            price_fraction_element = await page.query_selector("span.a-price-fraction")
            whole_text = (await price_whole_element.inner_text()).strip() if price_whole_element else ""
            fraction_text = (await price_fraction_element.inner_text()).strip() if price_fraction_element else ""
            whole_text = whole_text.replace("\n", "").replace(" ", "").replace(".", "")
            fraction_text = fraction_text.replace("\n", "").replace(" ", "")
            if whole_text and fraction_text:
                price = f"${whole_text}.{fraction_text}"
            elif whole_text:
                price = f"${whole_text}"

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

        # 获取评分 (Rating) 和评分数量 (Review Count)
        rating = "Rating not found"
        review_count = "Review count not found"
        rating_element = await page.query_selector("#averageCustomerReviews .a-icon-alt")
        review_count_element = await page.query_selector("#acrCustomerReviewText")

        if rating_element:
            rating_text = await rating_element.inner_text()
            rating_match = re.search(r"(\d+\.\d+|\d+)", rating_text)
            rating = rating_match.group(0) if rating_match else "Rating not found"

        if review_count_element:
            review_text = await review_count_element.inner_text()
            review_match = re.search(r"(\d+,?\d*)", review_text)
            review_count = review_match.group(0).replace(",", "") if review_match else "Review count not found"

        # 获取 Date First Available（优化为单次查询 + 缓存选择器）
        date_first_available = "Date not found"
        date_selectors = [
            "#detailBullets_feature_div li span:has-text('Date First Available')",
            "#productDetails_detailBullets_sections1 tr:has-text('Date First Available') td",
            "#productDetails_techSpec_section_1 tr:has-text('Date First Available') td",
            "th.prodDetSectionEntry:has-text('Date First Available') + td"
        ]

        # 单次查询所有可能的选择器，减少循环开销
        for selector in date_selectors:
            date_element = await page.query_selector(selector)
            if date_element:
                date_value = await date_element.inner_text()
                date_match = re.search(r"(?:\w+\s+\d{1,2},\s+\d{4}|\d{1,2}\s+\w+\s+\d{4})", date_value)
                if date_match:
                    date_first_available = date_match.group(0).strip()
                    # 只在成功时打印日志，减少 I/O
                    # print(f"ℹ️ 找到 Date First Available: {date_first_available} (使用选择器: {selector})")
                    break
                # 如果调试需要，可取消注释
                # else:
                #     print(f"ℹ️ 提取值非日期格式: {date_value} (选择器: {selector})")
            # 如果调试需要，可取消注释
            # else:
            #     print(f"ℹ️ 未找到 Date First Available (选择器: {selector})")

        if retry_count > 0:
            print(f"🔄 ASIN {asin} 重试成功！")
        print(f"✅ 爬取成功")

        return {
            "asin": asin,
            "brand": brand,
            "brand_link": brand_link,
            "title": title,
            "price": price,
            "bought": bought,
            "fabric_type": fabric_type,
            "url": url,
            "frequently_returned": frequently_returned,
            "variants": variant_asins,
            "rating": rating,
            "review_count": review_count,
            "date_first_available": date_first_available
        }

    except Exception as e:
        print(f"❌ 爬取失败: {asin}，错误: {e}")
        if retry_count < MAX_RETRIES:
            print(f"⚠️ ASIN {asin} 加入重试队列，重试次数: {retry_count + 1}")
            await asyncio.sleep(random.uniform(1, 3))
            return await get_product_details(asin, page, retry_count + 1)
        else:
            print(f"🚨 ASIN {asin} 重试次数已达上限，放弃爬取")
            return {"asin": asin, "retry": True}


async def test_scraper():
    """ 测试爬取单个 ASIN，并递归爬取所有变体 """
    test_asin = "B0C61QXH6F"
    scraped_data = {}
    to_scrape = [test_asin]
    seen_asins = set()

    start_time = time.perf_counter()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

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
                if product_info.get("retry"):
                    to_scrape.append(current_asin)
                else:
                    scraped_data[current_asin] = product_info
                    if "variants" in product_info:
                        for variant_asin in product_info["variants"]:
                            if variant_asin not in seen_asins and variant_asin not in to_scrape:
                                to_scrape.append(variant_asin)

        await page.close()
        await browser.close()

        end_time = time.perf_counter()
        total_time = end_time - start_time

        df = pd.DataFrame(scraped_data.values())
        df.to_csv(OUTPUT_FILE, index=False)
        print(f"✅ 数据已保存到 {OUTPUT_FILE}")

        print("\n🛒 爬取完成！所有数据如下：")
        for asin, data in scraped_data.items():
            print("=" * 50)
            print(f"ASIN: {asin}")
            for key, value in data.items():
                if key != "asin":
                    print(f"{key}: {value}")

        print("=" * 50)
        print(f"⏱️ 总爬取时间: {total_time:.2f} 秒")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_scraper())