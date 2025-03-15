import asyncio
import csv
import json
import logging
from search import search_products  # 导入搜索模块，获取 ASIN 列表
from scraper import get_product_details  # 导入抓取模块，获取商品详情
from playwright.async_api import async_playwright  # 导入 Playwright 的异步 API
import time
import os
from datetime import datetime  # 新增时间模块

# 配置日志
logging.basicConfig(
    level=logging.INFO,  # 设置默认日志级别为 INFO
    format="%(asctime)s - %(levelname)s - %(message)s",  # 日志格式：时间 - 级别 - 消息
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler("crawler.log", encoding="utf-8")  # 输出到文件
    ]
)

# 配置文件的路径
CONFIG_FILE = "config.json"
# CSV 文件保存目录
CSV_DIR = "csv"  # 直接定义，不检查和创建

# 读取配置文件，获取全局参数
with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

# 从配置文件中提取参数
SEARCH_QUERIES = config["search_query"]  # 搜索关键词列表，例如 ["toilet paper holder", "vintage apron"]
CSV_FILE_BASE = config["csv_file"]  # 保存 ASIN 列表的 CSV 文件基础名
OUTPUT_FILE_BASE = config["output_file"]  # 保存最终商品数据的 CSV 文件基础名
MAX_WORKERS = config["max_processes"]  # 最大并行任务数
MAX_PAGES = config["max_pages"]  # 搜索结果的最大翻页数
COOKIES_FILE = config["cookies_file"]  # Cookies 文件路径，用于模拟登录

# 定义工作进程函数，负责从队列中获取 ASIN 并抓取数据
async def worker(queue, context, results, seen_asins, failed_asins):
    """
    异步工作进程，从任务队列中获取 ASIN 并调用 get_product_details 抓取商品信息。
    
    :param queue: asyncio.Queue，存储待处理的 ASIN
    :param context: Playwright 浏览上下文，用于创建新页面
    :param results: list，存储抓取结果
    :param seen_asins: set，记录已处理的 ASIN，避免重复
    :param failed_asins: set，记录失败的 ASIN
    """
    while not queue.empty():  # 当队列不为空时持续处理
        try:
            asin = await queue.get()  # 从队列中获取一个 ASIN
        except asyncio.CancelledError:
            logging.warning("⚠️ 获取 ASIN 时任务被取消")
            queue.task_done()
            raise
        page = None  # 初始化 page 为 None
        try:
            if asin in seen_asins:  # 如果 ASIN 已处理过，跳过
                queue.task_done()  # 标记任务完成
                continue
            logging.info(f"🛒 任务队列领取 ASIN: {asin}")  # 显示当前处理的 ASIN
            page = await context.new_page()  # 创建新页面
            # 拦截并禁用不必要的资源请求，优化加载速度
            await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,css,woff,woff2,js,mp4,webm}", lambda route: route.abort())
            product_data = await get_product_details(asin, page)  # 抓取商品详情
            await page.close()  # 关闭页面，释放资源
            queue.task_done()  # 标记任务完成
            if product_data:  # 如果成功抓取到数据
                seen_asins.add(asin)  # 将 ASIN 标记为已处理
                results.append(product_data)  # 添加到结果列表
            else:  # 如果抓取失败
                failed_asins.add(asin)  # 记录失败的 ASIN
        except asyncio.CancelledError:
            logging.warning(f"⚠️ 任务处理 ASIN {asin} 被取消")
            if page is not None:  # 检查 page 是否已创建
                try:
                    await page.close()
                except Exception as e:
                    logging.debug(f"关闭页面 {asin} 时出错: {str(e)}")
            queue.task_done()
            raise

async def process_query(query, csv_file_base, output_file_base, browser, task_list):
    """处理单个搜索词的爬取流程"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")  # 生成时间戳，如 202503011430
    csv_file_path = os.path.join(CSV_DIR, f"{query}_{timestamp}_{csv_file_base}")
    output_file_path = os.path.join(CSV_DIR, f"{query}_{timestamp}_{output_file_base}")
    
    # 调用 search_products 获取 ASIN 列表
    asins = await search_products(query, csv_file_path, MAX_PAGES)
    if not asins:  # 如果没有找到 ASIN，跳过
        logging.warning(f"❌ 没有找到 ASIN for '{query}'，跳过！")
        return

    # 创建任务队列，用于分发 ASIN 给工作进程
    queue = asyncio.Queue()
    seen_asins = set()  # 成功抓取的 ASIN
    failed_asins = set()  # 失败的 ASIN
    # 将所有 ASIN 添加到队列中
    for asin in asins:
        await queue.put(asin)

    # 创建新的浏览上下文
    context = await browser.new_context()

    # 加载 Amazon 登录 Cookies
    try:
        with open(COOKIES_FILE, "r") as f:
            cookies = json.load(f)
            await context.add_cookies(cookies)  # 将 Cookies 添加到上下文
            logging.info(f"✅ 已加载 Amazon 登录 Cookies for '{query}'")
    except:
        logging.warning(f"⚠️ 没有找到 Cookies，可能需要先运行 `login.py` 手动登录")
        try:
            await context.close()
        except Exception as e:
            logging.debug(f"关闭上下文时出错: {str(e)}")
        return

    # 初始化结果列表
    results = []
    # 创建并行任务，数量为 ASIN 总数和 MAX_WORKERS 的较小值
    tasks = [asyncio.create_task(worker(queue, context, results, seen_asins, failed_asins)) 
             for _ in range(min(len(asins), MAX_WORKERS))]
    task_list.extend(tasks)  # 将任务添加到全局任务列表以便中断时取消

    try:
        await asyncio.gather(*tasks)  # 等待所有任务完成
    except asyncio.CancelledError:
        logging.warning(f"⚠️ 处理 '{query}' 的任务被取消")
        # 确保所有任务被取消并完成
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # 关闭上下文，不处理异常
        try:
            await context.close()
        except Exception:
            pass  # 忽略关闭时的异常
        raise

    # 正常完成时关闭上下文
    try:
        await context.close()
    except Exception as e:
        logging.debug(f"关闭上下文时出错: {str(e)}")

    # 如果没有抓取到数据，提示并返回
    if not results:
        logging.warning(f"❌ 没有爬取到数据 for '{query}'")
        return

    # 从第一个结果动态获取字段名
    fieldnames = list(results[0].keys())
    # 将结果写入 CSV 文件
    with open(output_file_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        # 排除 url 和 brand_link 字段，生成表头
        field_names = [field for field in fieldnames if field not in ["url", "brand_link"]]
        writer.writerow(field_names)  # 写入表头
        # 遍历所有抓取结果
        for product_data in results:
            # 将 ASIN 转换为超链接格式
            product_data["asin"] = f'=HYPERLINK("https://www.amazon.com/dp/{product_data["asin"]}", "{product_data["asin"]}")'
            # 如果有品牌链接，将品牌转换为超链接
            if product_data.get("brand_link"):
                product_data["brand"] = f'=HYPERLINK("{product_data["brand_link"]}", "{product_data.get("brand", "N/A")}")'
            # 写入一行数据，使用 get 方法避免字段缺失
            writer.writerow([product_data.get(field, "N/A") for field in field_names])

    # 输出抓取统计信息
    total_asins = len(asins)
    successful_asins = len(results)
    failed_count = total_asins - successful_asins
    logging.info(f"🎉 '{query}' 商品信息已保存到 `{output_file_path}`！共爬取 {total_asins} 个 ASIN，成功 {successful_asins} 个，失败 {failed_count} 个，失败的 ASIN: {list(failed_asins)}")

# 定义主函数，协调搜索和抓取流程
async def main():
    """主函数：负责循环处理所有搜索词并调用爬取流程"""
    task_list = []  # 存储所有异步任务以便中断时取消
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--disable-web-security", "--disable-dev-shm-usage", "--no-sandbox"]
        )
        try:
            for query in SEARCH_QUERIES:
                logging.info(f"=== 开始处理搜索词: {query} ===")
                await process_query(query, CSV_FILE_BASE, OUTPUT_FILE_BASE, browser, task_list)
        except KeyboardInterrupt:
            logging.warning("用户中断程序，正在清理资源...")
            # 取消所有正在运行的任务
            for task in task_list:
                if not task.done():
                    task.cancel()
            # 等待任务完成并忽略异常
            await asyncio.gather(*task_list, return_exceptions=True)
            # 关闭浏览器，不处理异常
            try:
                await browser.close()
            except Exception:
                pass  # 忽略关闭时的异常
            logging.info("程序已优雅退出")
            # 清理事件循环中的未完成任务
            loop = asyncio.get_running_loop()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return
        finally:
            # 确保浏览器在正常完成时也被关闭
            try:
                await browser.close()
            except Exception as e:
                logging.debug(f"关闭浏览器时出错: {str(e)}")

# 程序入口，运行主函数并计时
if __name__ == "__main__":
    start_time = time.perf_counter()  # 记录开始时间
    try:
        asyncio.run(main())  # 运行异步主函数
    except KeyboardInterrupt:
        logging.warning("用户中断程序，程序已退出")
    finally:
        end_time = time.perf_counter()  # 记录结束时间
        total_time = end_time - start_time  # 计算总耗时
        logging.info("=" * 50)
        logging.info(f"整个 `main.py` 运行时间: {total_time:.2f} 秒")
        logging.info("=" * 50)