1. 删除旧的 myenv
rm -rf myenv

2. 创建新的虚拟环境
python3 -m venv myenv

3. 激活虚拟环境
source myenv/bin/activate

4. 升级 pip
python3 -m pip install --upgrade pip

5. 安装 Playwright
pip install playwright
playwright install