"""
EDINET API で日本株の財務諸表 (BS / PL / CF) を取得する

金融庁公式API。有価証券報告書・四半期報告書の全科目が取得可能。
APIキーの取得: https://disclosure2.edinet-fsa.go.jp/WEEE0010.aspx (無料登録)

環境変数:
    EDINET_API_KEY: EDINETのAPIキー
"""

import io
import os
import time
import zipfile
from datetime import datetime, timedelta

import pandas as pd
import requests

EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"


def _api_key() -> str:
    key = os.environ.get("EDINET_API_KEY", "")
    return key


def _get(url: str, params: dict, stream: bool = False) -> requests.Response:
    if _api_key():
        params["Subscription-Key"] = _api_key()
    r = requests.get(url, params=params, stream=stream, timeout=30)
    r.raise_for_status()
    return r


# ── 書類一覧取得 ─────────────────────────────────────────────────────────────

def get_doc_list(date: str, doc_type: int = 2) -> pd.DataFrame:
    """
    指定日に提出された書類一覧を取得する

    Args:
        date:     "YYYY-MM-DD"
        doc_type: 1=有報, 2=有報+決算短信等

    Returns:
        columns: docID, filerName, edinetCode, docTypeCode, periodEnd, ...
    """
    r = _get(f"{EDINET_BASE}/documents.json", {"date": date, "type": doc_type})
    results = r.json().get("results", [])
    return pd.DataFrame(results)


def find_docs(
    edinet_code: str,
    start_date: str,
    end_date: str,
    doc_type_codes: list[str] | None = None,
) -> pd.DataFrame:
    """
    指定銘柄の書類一覧を期間で検索する

    Args:
        edinet_code:    EDINETコード (例: "E02144" はトヨタ)
        start_date:     "YYYY-MM-DD"
        end_date:       "YYYY-MM-DD"
        doc_type_codes: ["120"]=有価証券報告書, ["140"]=四半期報告書
                        None で全種類

    Returns:
        書類一覧 DataFrame
    """
    if doc_type_codes is None:
        doc_type_codes = ["120", "140", "150"]  # 有報・四半期報・半期報

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end   = datetime.strptime(end_date,   "%Y-%m-%d")
    docs  = []
    current = start

    while current <= end:
        try:
            df = get_doc_list(current.strftime("%Y-%m-%d"))
            if not df.empty:
                mask = (df["edinetCode"] == edinet_code) & \
                       (df["docTypeCode"].isin(doc_type_codes))
                docs.append(df[mask])
        except Exception:
            pass
        current += timedelta(days=1)
        time.sleep(0.1)  # レート制限対策

    return pd.concat(docs, ignore_index=True) if docs else pd.DataFrame()


# ── 財務データ抽出 ───────────────────────────────────────────────────────────

def get_financials(doc_id: str) -> dict[str, pd.DataFrame]:
    """
    書類IDからBS/PL/CFのCSVを取得して返す

    Returns:
        {
          "bs": DataFrame,  # 貸借対照表
          "pl": DataFrame,  # 損益計算書
          "cf": DataFrame,  # キャッシュフロー計算書
        }
    """
    r = _get(
        f"{EDINET_BASE}/documents/{doc_id}",
        params={"type": 5},  # CSVファイル
        stream=True,
    )
    zf = zipfile.ZipFile(io.BytesIO(r.content))

    result = {}
    keyword_map = {
        "bs": ["貸借対照表", "BalanceSheet", "BS"],
        "pl": ["損益計算書", "IncomeStatement", "PL", "StatementOfIncome"],
        "cf": ["キャッシュ", "CashFlow", "CF"],
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


# ── EDINETコード検索ユーティリティ ──────────────────────────────────────────

def search_edinet_code(company_name: str) -> pd.DataFrame:
    """
    会社名からEDINETコードを検索する (部分一致)

    EDINETコード一覧CSV: https://disclosure.edinet-fsa.go.jp/E01EW/BLMainController.jsp?uji.verb=W1E62071EdinetCodeListInfo
    事前に edinet_code_list.csv をダウンロードして同ディレクトリに配置してください。
    """
    csv_path = os.path.join(os.path.dirname(__file__), "edinet_code_list.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            "edinet_code_list.csv が見つかりません。\n"
            "https://disclosure.edinet-fsa.go.jp からダウンロードしてください。"
        )
    df = pd.read_csv(csv_path, encoding="cp932", skiprows=1)
    return df[df["提出者名"].str.contains(company_name, na=False)]


# ── サンプル実行 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # トヨタ自動車のEDINETコード: E02144
    EDINET_CODE = "E02144"
    START = "2023-04-01"
    END   = "2024-03-31"

    print(f"書類一覧を検索中: {EDINET_CODE} ({START} ~ {END})")
    docs = find_docs(EDINET_CODE, START, END, doc_type_codes=["120"])
    print(docs[["docID", "filerName", "docTypeCode", "periodEnd"]].to_string(index=False))

    if not docs.empty:
        doc_id = docs.iloc[0]["docID"]
        print(f"\n財務データ取得中: {doc_id}")
        fins = get_financials(doc_id)
        for key, df in fins.items():
            print(f"\n--- {key.upper()} ---")
            print(df.head(10).to_string(index=False))
