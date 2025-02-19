from playwright.sync_api import sync_playwright
import time
import random
import json

COOKIES_FILE = "amazon_cookies.json"


def get_product_details(asin):
    url = f"https://www.amazon.com/dp/{asin}"
    print(f"📦 正在爬取商品详情: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # 使用无头模式
        context = browser.new_context()

        # **加载已保存的 Amazon 登录 Cookies**
        try:
            with open(COOKIES_FILE, "r") as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
                print("✅ 已加载 Amazon 登录 Cookies")
        except:
            print("⚠️ 没有找到 Cookies，可能需要先运行 `login.py` 手动登录")
            browser.close()
            return None

        page = context.new_page()

        # 伪装真实浏览器
        page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1"
        })

        try:
            # 访问商品页面
            page.goto(url, timeout=90000)
            page.wait_for_selector("#productTitle", timeout=60000)

            # 获取商品标题
            title_element = page.query_selector("#productTitle")
            title = title_element.inner_text().strip() if title_element else "Title not found"

            # 获取价格
            price_element = page.query_selector("span.a-offscreen")
            price = price_element.inner_text().strip() if price_element else "Price not found"

            # **检查是否有 `Frequently returned item` 标签**
            frequently_returned_element = page.query_selector(
                "div#buyingOptionNostosBadge_feature_div .hrrv-badge-T2-title p span.a-text-bold")
            frequently_returned = True if frequently_returned_element else False

            print(
                f"✅ 爬取成功: {title} - {price} - Frequently Returned: {frequently_returned}")

            browser.close()
            return {"asin": asin, "title": title, "price": price, "url": url, "frequently_returned": frequently_returned}

        except Exception as e:
            print(f"❌ 爬取失败: {asin}，错误: {e}")
            browser.close()
            return None


# 直接运行 `scraper.py` 进行测试
if __name__ == "__main__":
    test_asin = "B0CN8SL6MV"  # 你可以换成任何 ASIN
    product_data = get_product_details(test_asin)

    if product_data:
        print("\n🛒 测试结果：")
        print(f"ASIN: {product_data['asin']}")
        print(f"Title: {product_data['title']}")
        print(f"Price: {product_data['price']}")
        print(f"URL: {product_data['url']}")
        print(f"Frequently Returned: {product_data['frequently_returned']}")
    else:
        print("❌ 爬取失败！")
