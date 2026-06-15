# japan-stock-model

日本株の株価・バリュエーション・財務データ(BS/PL/CF)取得ツール

## セットアップ

```bash
pip install -r requirements.txt
```

## データソース構成

| データ | ソース | 費用 | 期間 |
|---|---|---|---|
| 株価・バリュエーション | yfinance (Yahoo Finance) | 無料 | 20年以上 |
| 財務諸表 BS/PL/CF (詳細) | EDINET API (金融庁公式) | 無料 | 有報提出分全期間 |

## EDINETのセットアップ

1. [https://disclosure2.edinet-fsa.go.jp/](https://disclosure2.edinet-fsa.go.jp/) でAPIキー登録（無料）
2. 環境変数を設定:

```bash
export EDINET_API_KEY=your_api_key
```

3. [EDINETコード一覧](https://disclosure.edinet-fsa.go.jp) から `edinet_code_list.csv` をダウンロードして `data/` に配置

## 使い方

```python
from data import get_prices, get_valuation, find_docs, get_financials

# 株価（20年分）
prices = get_prices("7203", "2014-01-01", "2024-12-31")

# バリュエーション（最新）
val = get_valuation("7203")

# 財務諸表 BS/PL/CF（EDINETコードで検索）
docs = find_docs("E02144", "2023-04-01", "2024-03-31", doc_type_codes=["120"])
fins = get_financials(docs.iloc[0]["docID"])
bs = fins["bs"]  # 貸借対照表
pl = fins["pl"]  # 損益計算書
cf = fins["cf"]  # キャッシュフロー計算書
```

## ファイル構成

```
data/
  prices.py   # yfinance: 株価・バリュエーション
  edinet.py   # EDINET API: BS/PL/CF 詳細財務データ
```