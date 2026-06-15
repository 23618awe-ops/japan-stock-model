"""EDINET接続デバッグ用スクリプト"""
import requests

# 1日分だけ試す
date = "2024-03-29"
url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
params = {"date": date, "type": 2}

print(f"URL: {url}")
print(f"パラメータ: {params}")

try:
    r = requests.get(url, params=params, timeout=30)
    print(f"ステータス: {r.status_code}")
    print(f"レスポンス先頭: {r.text[:500]}")

    if r.status_code == 200:
        data = r.json()
        results = data.get("results", [])
        print(f"\n取得件数: {len(results)}")
        if results:
            print("カラム一覧:", list(results[0].keys()))
            # トヨタ(E02144)を探す
            toyota = [x for x in results if x.get("edinetCode") == "E02144"]
            print(f"トヨタの書類: {toyota}")
except Exception as e:
    print(f"エラー: {e}")
