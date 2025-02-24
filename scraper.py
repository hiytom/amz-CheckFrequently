import asyncio
from playwright.async_api import async_playwright
import json
import random
import pandas as pd
import time  # 用于统计时间
import re  # 引入正则库

COOKIES_FILE = "amazon_cookies.json"
OUTPUT_FILE = "amazon_products.csv"
MAX_RETRIES = 5  # 保持重试次数为 5


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
        # 随机延迟，减少风控
        await asyncio.sleep(random.uniform(0.2, 0.8))

        # 使用随机 User-Agent 并保持 60 秒超时
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0"
        ]
        await page.set_extra_http_headers({"User-Agent": random.choice(user_agents)})
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_selector("#productTitle", timeout=60000)

        # 检查是否遇到验证码
        captcha = await page.query_selector("input#captchacharacters")
        if captcha:
            print(f"❌ ASIN {asin} 遇到验证码，请手动解决后继续...")
            await asyncio.sleep(30)  # 暂停 30 秒等待手动解决
            await page.reload()

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

        # 获取负面词语 (Negative Aspects)
        negative_aspects = []
        insights_section = await page.query_selector("#cr-product-insights-cards")
        if insights_section:
            negative_elements = await insights_section.query_selector_all("a[data-csa-c-item-id*='_NEGATIVE']")
            for elem in negative_elements:
                aspect_text = await elem.inner_text()
                aspect_cleaned = re.sub(r'[^a-zA-Z\s]', '', aspect_text).strip()
                if aspect_cleaned:
                    negative_aspects.append(aspect_cleaned)
            if negative_aspects:
                print(f"ℹ️ 找到负面词语: {negative_aspects}")
            else:
                print("ℹ️ 未找到负面词语")
        else:
            print("ℹ️ 未找到评论洞察模块")

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
            "negative_aspects": negative_aspects
        }

    except Exception as e:
        print(f"❌ 爬取失败: {asin}，错误: {str(e)}")
        if retry_count < MAX_RETRIES:
            print(f"⚠️ ASIN {asin} 加入重试队列，重试次数: {retry_count + 1}")
            await asyncio.sleep(random.uniform(2, 5))
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