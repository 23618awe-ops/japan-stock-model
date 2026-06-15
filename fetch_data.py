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
):
    """
    指定したEDINETコードの財務データを期間内で取得してCSV保存

    Args:
        edinet_codes: ["E02144", "E02362", ...]
        start_date:   "YYYY-MM-DD"
        end_date:     "YYYY-MM-DD"
    """
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

    print("\n=== 株価データ取得 ===")
    # EDINETコード→証券コードのマッピングがあれば株価も取得
    codes_csv = load_edinet_codes()
    if not codes_csv.empty:
        # カラム名を確認して証券コード列を特定
        print("EDINETコード一覧のカラム:", codes_csv.columns.tolist())


if __name__ == "__main__":
    # ── 取得対象（EDINETコード） ──────────────────────────────────
    TARGETS = [
        "E02144",  # トヨタ自動車
        "E04425",  # ソニーグループ
        "E01777",  # 三菱UFJフィナンシャル
        "E02362",  # キーエンス
        "E02513",  # 任天堂
    ]

    START = "2023-04-01"
    END   = "2024-03-31"

    run(TARGETS, START, END)
