import asyncio
from playwright.async_api import async_playwright
import json

COOKIES_FILE = "amazon_cookies.json"


async def get_product_details(asin, page):
    """爬取商品详情"""
    url = f"https://www.amazon.com/dp/{asin}"
    print(f"\U0001F4E6 正在爬取商品详情: {url}")

    try:
        await page.goto(url, timeout=90000)
        await page.wait_for_selector("#productTitle", timeout=60000)

        # 获取商品标题
        title_element = await page.query_selector("#productTitle")
        title = await title_element.inner_text() if title_element else "Title not found"

        # 获取价格
        price_element = await page.query_selector("span.a-offscreen")
        price = await price_element.inner_text() if price_element else "Price not found"

        # **检查 `Frequently returned item` 标签**
        frequently_returned_element = await page.query_selector(
            "div#buyingOptionNostosBadge_feature_div .hrrv-badge-T2-title p span.a-text-bold")
        frequently_returned = True if frequently_returned_element else False

        print(
            f"✅ 爬取成功: {title} - {price} - Frequently Returned: {frequently_returned}")

        return {"asin": asin, "title": title, "price": price, "url": url, "frequently_returned": frequently_returned}

    except Exception as e:
        print(f"❌ 爬取失败: {asin}，错误: {e}")
        return None

# **✅ 运行 `scraper.py` 进行测试**


async def test_scraper():
    test_asin = "B0CN8SL6MV"
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
        product_data = await get_product_details(test_asin, page)

        await page.close()
        await browser.close()

        if product_data:
            print("\n\U0001F6D2 测试结果：")
            print(f"ASIN: {product_data['asin']}")
            print(f"Title: {product_data['title']}")
            print(f"Price: {product_data['price']}")
            print(f"URL: {product_data['url']}")
            print(
                f"Frequently Returned: {product_data['frequently_returned']}")
        else:
            print("❌ 爬取失败！")

if __name__ == "__main__":
    asyncio.run(test_scraper())
