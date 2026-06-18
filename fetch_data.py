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


def _read_csv_from_bytes(data: bytes) -> pd.DataFrame:
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "cp932", "utf-8"):
        for sep in ("\t", ","):
            try:
                df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep, on_bad_lines="skip", low_memory=False)
                if len(df.columns) >= 2:
                    return df
            except Exception:
                continue
    return pd.DataFrame()


def _extract_csvs(zf: zipfile.ZipFile) -> dict[str, bytes]:
    """ZIPから全CSVを取得（ネストZIPも対応）"""
    csvs = {}
    for name in zf.namelist():
        if name.endswith(".csv"):
            csvs[name] = zf.read(name)
        elif name.endswith(".zip"):
            try:
                inner = zipfile.ZipFile(io.BytesIO(zf.read(name)))
                for inner_name in inner.namelist():
                    if inner_name.endswith(".csv"):
                        csvs[inner_name] = inner.read(inner_name)
            except Exception:
                pass
    return csvs


def fetch_financials(doc_id: str) -> dict[str, pd.DataFrame]:
    try:
        r = edinet_get(f"{EDINET_BASE}/documents/{doc_id}", {"type": 5}, stream=True)
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        all_csvs = _extract_csvs(zf)

        if not all_csvs:
            print(f"    ZIPにCSVなし: {zf.namelist()[:5]}")
            return {}

        # 有価証券報告書(asr)または四半期報告書(q1r/q2r/q3r)のCSVを優先して取得
        # EDINETのCSVは1ファイルに全財務データがXBRL形式で入っている
        target = None
        for name in all_csvs:
            if "asr-001" in name or "q1r-001" in name or "q2r-001" in name or "q3r-001" in name:
                target = name
                break

        if target is None:
            print(f"    対象CSVなし。ZIPの中身: {list(all_csvs.keys())[:5]}")
            return {}

        df = _read_csv_from_bytes(all_csvs[target])
        if df.empty:
            return {}

        return _parse_xbrl_csv(df)


def _parse_xbrl_csv(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    EDINETのXBRL CSVを BS / PL / CF に分けて返す

    EDINET CSVの構造（縦持ち）:
        要素ID, コンテキストID, 相対年度, 連結・個別, 期間・時点, ユニットID, 値, ...
    """
    # カラム名を確認して正規化
    df.columns = df.columns.str.strip()

    # 値列と要素ID列を特定
    id_col  = next((c for c in df.columns if "要素" in c or "element" in c.lower()), df.columns[0])
    val_col = next((c for c in df.columns if "値" in c or c.lower() in ("value", "amount")), None)

    if val_col is None or id_col is None:
        return {}

    # BS/PL/CF に関連するキーワード
    bs_keys = ["TotalAssets", "NetAssets", "TotalLiabilities", "Equity",
               "CashAndDeposits", "TotalLiabilitiesAndNetAssets",
               "総資産", "純資産", "負債", "現金"]
    pl_keys = ["NetSales", "OperatingIncome", "OrdinaryIncome", "ProfitLoss",
               "NetIncome", "売上", "営業利益", "経常", "純利益", "EPS",
               "EarningsPerShare", "SharesOutstanding"]
    cf_keys = ["CashFlowFrom", "CashAndCashEquivalents", "キャッシュ", "CF"]

    def match(element: str, keys: list) -> bool:
        return any(k.lower() in str(element).lower() for k in keys)

    bs_rows = df[df[id_col].apply(lambda x: match(x, bs_keys))]
    pl_rows = df[df[id_col].apply(lambda x: match(x, pl_keys))]
    cf_rows = df[df[id_col].apply(lambda x: match(x, cf_keys))]

    result = {}
    if not bs_rows.empty:
        result["bs"] = bs_rows.reset_index(drop=True)
    if not pl_rows.empty:
        result["pl"] = pl_rows.reset_index(drop=True)
    if not cf_rows.empty:
        result["cf"] = cf_rows.reset_index(drop=True)

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
