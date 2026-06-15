# japan-stock-model

日本株の株価・バリュエーション・財務データ(BS/PL/CF)取得ツール

## セットアップ

```bash
pip install -r requirements.txt
```

### J-Quants APIアカウント登録（無料）

1. [https://jpx-jquants.com/](https://jpx-jquants.com/) でアカウント登録
2. 環境変数を設定:

```bash
export JQUANTS_EMAIL=your@email.com
export JQUANTS_PASSWORD=yourpassword
```

## 使い方

```bash
python jquants_client.py
```

## 取得できるデータ

| データ | 内容 |
|---|---|
| 株価 | 始値・高値・安値・終値・出来高・調整済み株価 |
| バリュエーション | PER・PBR・配当利回り |
| PL | 売上高・営業利益・経常利益・純利益 |
| BS | 総資産・総負債・純資産 |
| CF | 営業CF・投資CF・財務CF・現金残高 |

## 主要関数

- `get_prices(client, code, start, end)` → 株価・バリュエーション
- `get_financials(client, code)` → 財務諸表 (BS/PL/CF)
- `get_listed_info(client)` → 全上場銘柄一覧