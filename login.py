import logging
from playwright.sync_api import sync_playwright
import json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("crawler.log", encoding="utf-8")
    ]
)

COOKIES_FILE = "amazon_cookies.json"

def save_amazon_cookies():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 关闭无头模式，手动登录
        page = browser.new_page()

        # **打开 Amazon 首页**
        logging.info("🔑 打开 Amazon 首页...")
        page.goto("https://www.amazon.com/", timeout=90000)

        # **点击 "Sign In" 按钮**
        logging.info("➡️ 点击登录按钮...")
        sign_in_button = page.query_selector("#nav-link-accountList")  # Amazon 登录按钮
        if sign_in_button:
            sign_in_button.click()
        else:
            logging.warning("⚠️ 没找到 'Sign In' 按钮，可能 Amazon 页面改版了")
            return

        # **等待用户手动完成登录**
        input("✅ 登录成功后，按 Enter 继续...")  # 这里等你手动登录

        # **获取登录后的 Cookies**
        cookies = page.context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f)

        logging.info("✅ 登录成功，Cookies 已保存到 `amazon_cookies.json`")
        browser.close()

if __name__ == "__main__":
    save_amazon_cookies()