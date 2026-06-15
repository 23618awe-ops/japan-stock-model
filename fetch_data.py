"""
全銘柄の財務データ・株価を自動取得してCSVに保存するスクリプト
GitHub Actionsから実行される
"""

import os
import time
import zipfile
import io
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"
API_KEY = os.environ.get("EDINET_API_KEY", "")
OUTPUT_DIR = "output"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def edinet_get(url, params, stream=False):
    if API_KEY:
        params["Subscription-Key"] = API_KEY
    r = requests.get(url, params=params, stream=stream, timeout=30)
    r.raise_for_status()
    return r


def fetch_doc_list(date: str) -> list:
    try:
        r = edinet_get(f"{EDINET_BASE}/documents.json", {"date": date, "type": 2})
        return r.json().get("results", [])
    except Exception as e:
        print(f"  [skip] {date}: {e}")
        return []


def fetch_financials(doc_id: str) -> dict[str, pd.DataFrame]:
    try:
        r = edinet_get(f"{EDINET_BASE}/documents/{doc_id}", {"type": 5}, stream=True)
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        result = {}
        keyword_map = {
            "bs": ["貸借対照表", "BalanceSheet"],
            "pl": ["損益計算書", "IncomeStatement"],
            "cf": ["キャッシュ", "CashFlow"],
        }
        for name in zf.namelist():
            if not name.endswith(".csv"):
                continue
            for key, keywords in keyword_map.items():
                if any(kw.lower() in name.lower() for kw in keywords):
                    with zf.open(name) as f:
                        try:
                            df = pd.read_csv(f, encoding="utf-8-sig")
                        except UnicodeDecodeError:
                            df = pd.read_csv(f, encoding="cp932")
                    result[key] = df
                    break
        return result
    except Exception as e:
        print(f"  [skip] 財務取得失敗 {doc_id}: {e}")
        return {}


def load_edinet_codes(csv_path="data/edinet_code_list.csv") -> pd.DataFrame:
    """EDINETコード一覧を読み込む（証券コードとの対応表）"""
    if not os.path.exists(csv_path):
        print(f"Warning: {csv_path} がありません。EDINETコードを直接指定してください。")
        return pd.DataFrame()
    df = pd.read_csv(csv_path, encoding="cp932", skiprows=1)
    return df


def run(
    edinet_codes: list[str],
    start_date: str,
    end_date: str,
    ticker_map: dict[str, str] | None = None,
):
    """
    指定したEDINETコードの財務データ・株価を取得してCSV保存

    Args:
        edinet_codes: ["E02144", "E02362", ...]
        start_date:   "YYYY-MM-DD"
        end_date:     "YYYY-MM-DD"
        ticker_map:   {"E02144": "7203", ...} EDINETコード→証券コード
    """
    if ticker_map is None:
        ticker_map = {}
    print(f"=== 財務データ取得開始 ({start_date} ~ {end_date}) ===")
    print(f"対象銘柄数: {len(edinet_codes)}")

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end   = datetime.strptime(end_date,   "%Y-%m-%d")
    current = start

    # 日付ループで書類を収集
    all_docs = []
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        docs = fetch_doc_list(date_str)
        matched = [d for d in docs
                   if d.get("edinetCode") in edinet_codes
                   and d.get("docTypeCode") in ["120", "140", "150"]]
        if matched:
            print(f"{date_str}: {len(matched)} 件")
            all_docs.extend(matched)
        current += timedelta(days=1)
        time.sleep(0.1)

    print(f"\n合計 {len(all_docs)} 件の書類を発見")

    # 財務データを取得
    bs_all, pl_all, cf_all = [], [], []
    for doc in all_docs:
        doc_id   = doc["docID"]
        edinet_c = doc.get("edinetCode", "")
        filer    = doc.get("filerName", "")
        period   = doc.get("periodEnd", "")
        print(f"  取得中: {filer} ({period}) ...")

        fins = fetch_financials(doc_id)
        for key, df in fins.items():
            df["edinetCode"] = edinet_c
            df["filerName"]  = filer
            df["periodEnd"]  = period
            df["docID"]      = doc_id
            if key == "bs":
                bs_all.append(df)
            elif key == "pl":
                pl_all.append(df)
            elif key == "cf":
                cf_all.append(df)
        time.sleep(0.3)

    # CSV保存
    for name, rows in [("bs", bs_all), ("pl", pl_all), ("cf", cf_all)]:
        if rows:
            out = pd.concat(rows, ignore_index=True)
            path = f"{OUTPUT_DIR}/{name}.csv"
            out.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"保存: {path} ({len(out)} 行)")

    print("\n=== 株価・バリュエーション取得 (yfinance) ===")
    fetch_prices(ticker_map, start_date, end_date)


def fetch_prices(
    ticker_map: dict[str, str],
    start_date: str,
    end_date: str,
):
    """
    株価・時価総額・バリュエーションをyfinanceで取得してCSV保存

    Args:
        ticker_map: {"E02144": "7203", ...}  EDINETコード→証券コード
        start_date: "YYYY-MM-DD"
        end_date:   "YYYY-MM-DD"
    """
    prices_all = []
    valuation_rows = []

    for edinet_code, code in ticker_map.items():
        ticker_symbol = f"{code}.T"
        print(f"  {ticker_symbol} ...")
        try:
            ticker = yf.Ticker(ticker_symbol)

            # 株価履歴
            hist = ticker.history(start=start_date, end=end_date, auto_adjust=True)
            if not hist.empty:
                hist = hist.reset_index()
                hist["Date"] = pd.to_datetime(hist["Date"]).dt.tz_localize(None)
                hist["edinetCode"] = edinet_code
                hist["code"] = code
                prices_all.append(hist[["Date", "edinetCode", "code",
                                        "Open", "High", "Low", "Close", "Volume"]])

            # バリュエーション（最新）
            info = ticker.info
            valuation_rows.append({
                "edinetCode":    edinet_code,
                "code":          code,
                "name":          info.get("longName", ""),
                "marketCap":     info.get("marketCap"),
                "trailingPE":    info.get("trailingPE"),
                "forwardPE":     info.get("forwardPE"),
                "priceToBook":   info.get("priceToBook"),
                "dividendYield": info.get("dividendYield"),
                "enterpriseValue": info.get("enterpriseValue"),
                "EV_EBITDA":     info.get("enterpriseToEbitda"),
                "fetchedAt":     datetime.now().strftime("%Y-%m-%d"),
            })
        except Exception as e:
            print(f"    [skip] {ticker_symbol}: {e}")
        time.sleep(0.5)

    if prices_all:
        df = pd.concat(prices_all, ignore_index=True)
        path = f"{OUTPUT_DIR}/prices.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"保存: {path} ({len(df)} 行)")

    if valuation_rows:
        df = pd.DataFrame(valuation_rows)
        path = f"{OUTPUT_DIR}/valuation.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"保存: {path} ({len(df)} 行)")
        print(df[["code", "name", "marketCap", "trailingPE", "priceToBook"]].to_string(index=False))


if __name__ == "__main__":
    # ── EDINETコード → 証券コード のマッピング ───────────────────
    TICKER_MAP = {
        "E02144": "7203",  # トヨタ自動車
        "E04425": "6758",  # ソニーグループ
        "E01777": "8306",  # 三菱UFJフィナンシャル
        "E02362": "6861",  # キーエンス
        "E02513": "7974",  # 任天堂
    }

    START = "2015-01-01"
    END   = "2024-12-31"

    run(list(TICKER_MAP.keys()), START, END, ticker_map=TICKER_MAP)
