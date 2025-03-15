import asyncio
import logging
from playwright.async_api import async_playwright  # 导入 Playwright 的异步 API
import json
import random
import pandas as pd  # 用于将数据保存为 CSV
import time
import re  # 用于正则表达式处理

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("crawler.log", encoding="utf-8")
    ]
)

# 定义常量
COOKIES_FILE = "amazon_cookies.json"  # Cookies 文件路径，用于模拟登录
OUTPUT_FILE = "amazon_products.csv"  # 测试模式下保存结果的 CSV 文件名
MAX_RETRIES = 5  # 最大重试次数，处理抓取失败的情况

# 获取商品变体 ASIN 的辅助函数
async def get_variants_asins(page):
    """
    从商品详情页提取所有变体 ASIN（如颜色、尺寸等变体的 ASIN）。
    
    :param page: Playwright 页面对象
    :return: list，包含变体 ASIN 的列表
    """
    variant_asins = set()  # 使用集合避免重复
    # 查找包含变体 ASIN 的元素，可能出现在不同标签中
    variant_elements = await page.query_selector_all("li[data-asin], div[data-defaultasin], div[data-csa-c-asin]")
    for elem in variant_elements:
        # 从不同属性中提取 ASIN
        asin = await elem.get_attribute("data-asin") or await elem.get_attribute("data-defaultasin") or await elem.get_attribute("data-csa-c-asin")
        if asin:  # 如果找到 ASIN，添加到集合
            variant_asins.add(asin.strip())
    return list(variant_asins)  # 返回去重后的列表

# 核心函数，抓取单个商品的详情
async def get_product_details(asin, page, retry_count=0):
    """
    从 Amazon 商品页面抓取详细信息（如标题、品牌、价格等）。
    
    :param asin: str，商品的 ASIN
    :param page: Playwright 页面对象
    :param retry_count: int，当前重试次数，默认为 0
    :return: dict，包含商品详情；若失败或非详情页，返回 None
    """
    url = f"https://www.amazon.com/dp/{asin}"  # 构造商品详情页 URL
    logging.info(f"📦 正在爬取商品详情: {url}")
    start_time = time.perf_counter()  # 记录开始时间
    try:
        # 随机延迟，模拟人类行为，降低反爬风险
        await asyncio.sleep(random.uniform(0.2, 0.8))
        # 定义常见的 User-Agent，伪装为真实浏览器
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0"
        ]
        # 设置请求头，随机选择 User-Agent
        await page.set_extra_http_headers({"User-Agent": random.choice(user_agents)})
        # 访问商品页面，等待 DOM 加载完成
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")

        # 检查是否为商品详情页
        title_element = await page.query_selector("#productTitle")  # 商品标题元素
        price_element = await page.query_selector("span.a-price") or await page.query_selector("span.a-offscreen")  # 价格元素
        if not title_element and not price_element:  # 如果标题和价格都不存在，认为是非详情页
            content = await page.content()
            logging.warning(f"⚠️ ASIN {asin} 不是商品详情页，跳过爬取。页面内容: {content[:500]}")
            return None

        # 检查是否遇到验证码
        captcha = await page.query_selector("input#captchacharacters")
        if captcha:
            logging.warning(f"❌ ASIN {asin} 遇到验证码，暂停等待手动解决...")
            await asyncio.sleep(60)  # 暂停 60 秒，等待手动解决
            await page.reload()  # 重新加载页面

        # 等待标题元素加载，确保页面完全可用
        await page.wait_for_selector("#productTitle", timeout=90000)
        title = await title_element.inner_text() if title_element else "Title not found"  # 获取标题

        # 获取品牌信息
        brand_element = await page.query_selector("#bylineInfo")
        brand = await brand_element.inner_text() if brand_element else "Brand not found"  # 获取品牌文字
        brand_link = await brand_element.get_attribute("href") if brand_element else None  # 获取品牌链接
        if "Visit the" in brand and "Store" in brand:  # 清理品牌名称中的冗余部分
            brand = brand.replace("Visit the", "").replace("Store", "").strip()
        elif "Brand:" in brand:
            brand = brand.replace("Brand:", "").strip()
        brand = re.sub(r'[^a-zA-Z0-9\s-]', '', brand).strip()  # 移除特殊字符
        if brand_link and not brand_link.startswith("http"):  # 补全品牌链接
            brand_link = f"https://www.amazon.com{brand_link}"

        # 提取价格
        price = "Price not found"
        if price_element:
            price_text = await price_element.inner_text()
            price_match = re.search(r'\$\d+\.\d{2}', price_text)  # 提取第一个合法价格
            if price_match:
                price = price_match.group(0)
            else:
                price_text = re.sub(r'[\n\r\s]+', '', price_text.strip())  # 清理文本
                if price_text:
                    price = price_text
        else:
            # 如果未找到完整价格，尝试拼接整数和小数部分
            price_whole_element = await page.query_selector("span.a-price-whole")
            price_fraction_element = await page.query_selector("span.a-price-fraction")
            whole_text = (await price_whole_element.inner_text()).strip() if price_whole_element else ""
            fraction_text = (await price_fraction_element.inner_text()).strip() if price_fraction_element else ""
            whole_text = re.sub(r'[\n\r\s.]', '', whole_text)  # 清理整数部分
            fraction_text = re.sub(r'[\n\r\s]', '', fraction_text)  # 清理小数部分
            if whole_text and fraction_text:
                price = f"${whole_text}.{fraction_text}"
            elif whole_text:
                price = f"${whole_text}"

        # 获取上月销量
        bought_element = await page.query_selector("#social-proofing-faceout-title-tk_bought .a-text-bold")
        bought = (await bought_element.inner_text()).split()[0] if bought_element else "< 50"

        # 获取面料类型
        fabric_type = None
        details_section = await page.query_selector("#productFactsDesktopExpander")
        if details_section:
            fabric_element = await details_section.query_selector("span.a-color-base:has-text('Fabric type')")
            if fabric_element:
                fabric_type_element = await fabric_element.evaluate_handle(
                    "el => el.parentElement.parentElement.nextElementSibling.querySelector('.a-color-base')"
                )
                fabric_type = await fabric_type_element.inner_text() if fabric_type_element else None

        # 检查是否为“经常退货”商品
        frequently_returned_element = await page.query_selector(
            "div#buyingOptionNostosBadge_feature_div .hrrv-badge-T2-title p span.a-text-bold"
        )
        frequently_returned = True if frequently_returned_element else False

        # 获取变体 ASIN
        variant_asins = await get_variants_asins(page)

        # 获取评分和评论数
        rating = "Rating not found"
        review_count = "Review count not found"
        rating_element = await page.query_selector("#averageCustomerReviews .a-icon-alt")
        review_count_element = await page.query_selector("#acrCustomerReviewText")
        if rating_element:
            rating_text = await rating_element.inner_text()
            rating_match = re.search(r"(\d+\.\d+|\d+)", rating_text)  # 提取评分数字
            rating = rating_match.group(0) if rating_match else "Rating not found"
        if review_count_element:
            review_text = await review_count_element.inner_text()
            review_match = re.search(r"(\d+,?\d*)", review_text)  # 提取评论数
            review_count = review_match.group(0).replace(",", "") if review_match else "Review count not found"

        # 获取“客户评价”总结
        customer_say = "Customer say not found"
        insights_section = await page.query_selector("#cr-product-insights-cards")
        if insights_section:
            summary_element = await insights_section.query_selector("#product-summary p span")
            if summary_element:
                customer_say = await summary_element.inner_text()

        # 获取负面反馈词
        negative_aspects = []
        if insights_section:
            negative_elements = await insights_section.query_selector_all("a[data-csa-c-item-id*='_NEGATIVE']")
            for elem in negative_elements:
                aspect_text = await elem.inner_text()
                aspect_cleaned = re.sub(r'[^a-zA-Z\s]', '', aspect_text).strip()  # 清理文本
                if aspect_cleaned:
                    negative_aspects.append(aspect_cleaned)

        # 如果是重试成功，提示用户
        if retry_count > 0:
            logging.info(f"🔄 ASIN {asin} 重试成功！")
        # 计算耗时并输出
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        logging.info(f"✅ 爬取成功，耗时 {elapsed_time:.2f} 秒")
        # 返回所有抓取到的数据
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
            "negative_aspects": negative_aspects,
            "customer_say": customer_say
        }
    except Exception as e:
        logging.error(f"❌ 爬取失败: {asin}，错误: {str(e)}")
        if retry_count < MAX_RETRIES:  # 如果未达到最大重试次数，继续尝试
            logging.warning(f"⚠️ ASIN {asin} 加入重试队列，重试次数: {retry_count + 1}")
            await asyncio.sleep(random.uniform(2, 5))  # 随机延迟后重试
            return await get_product_details(asin, page, retry_count + 1)
        else:
            logging.error(f"🚨 ASIN {asin} 重试次数已达上限，放弃爬取")
            return None  # 重试失败，返回 None

# 测试函数，用于单个 ASIN 的抓取和调试
async def test_scraper():
    """
    测试抓取功能，从单个 ASIN 开始，递归抓取其变体，并输出结果。
    """
    test_asin = "B0CN8SL6MV"  # 测试用的初始 ASIN
    scraped_data = {}  # 存储抓取结果
    to_scrape = [test_asin]  # 待抓取的 ASIN 队列
    seen_asins = set()  # 记录已处理的 ASIN
    start_time = time.perf_counter()  # 记录开始时间

    # 使用 Playwright 启动浏览器
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)  # 无头模式启动 Chromium
        context = await browser.new_context()  # 创建新的浏览上下文
        try:
            # 加载 Cookies 以模拟登录状态
            with open(COOKIES_FILE, "r") as f:
                cookies = json.load(f)
                await context.add_cookies(cookies)
                logging.info("✅ 已加载 Amazon 登录 Cookies")
        except:
            logging.warning("⚠️ 没有找到 Cookies，可能需要先运行 `login.py` 手动登录")
            await browser.close()
            return
        page = await context.new_page()  # 创建新页面

        # 循环处理待抓取的 ASIN
        while to_scrape:
            current_asin = to_scrape.pop(0)  # 从队列中取出一个 ASIN
            if current_asin in seen_asins:  # 如果已处理，跳过
                continue
            seen_asins.add(current_asin)  # 标记为已处理
            product_info = await get_product_details(current_asin, page)  # 抓取详情
            if product_info:  # 如果抓取成功
                scraped_data[current_asin] = product_info  # 保存结果
                # 如果有变体 ASIN，加入待抓取队列
                if "variants" in product_info:
                    for variant_asin in product_info["variants"]:
                        if variant_asin not in seen_asins and variant_asin not in to_scrape:
                            to_scrape.append(variant_asin)
        await page.close()  # 关闭页面
        await browser.close()  # 关闭浏览器

        # 计算总耗时
        end_time = time.perf_counter()
        total_time = end_time - start_time
        # 将结果保存为 CSV
        df = pd.DataFrame(scraped_data.values())
        df.to_csv(OUTPUT_FILE, index=False)
        logging.info(f"✅ 数据已保存到 {OUTPUT_FILE}")

        # 打印所有抓取到的数据，方便调试
        logging.info("🛒 爬取完成！所有数据如下：")
        for asin, data in scraped_data.items():
            logging.info("=" * 50)
            logging.info(f"ASIN: {asin}")
            for key, value in data.items():
                if key != "asin":  # ASIN 已单独打印，避免重复
                    logging.info(f"{key}: {value}")
        logging.info("=" * 50)
        logging.info(f"⏱️ 总爬取时间: {total_time:.2f} 秒")
        logging.info("=" * 50)

# 程序入口，运行测试函数
if __name__ == "__main__":
    asyncio.run(test_scraper())  # 启动异步测试流程