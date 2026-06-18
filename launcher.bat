@echo off
echo GitHubから最新コードを取得して実行します...
pip install requests pandas -q
python -c "import requests; exec(requests.get('https://raw.githubusercontent.com/23618awe-ops/japan-stock-model/main/test_edinet.py').text)"
pause
