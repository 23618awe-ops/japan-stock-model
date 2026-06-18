"""
株価（yfinance）× EDINET財務データからバリュエーション時系列を計算する

入力:
    output/prices.csv      - 日次株価 (yfinanceで取得)
    output/financials.csv  - EDINET全財務項目（縦持ちXBRL）

出力:
    output/valuation_history.csv
"""

import pandas as pd
import numpy as np
import os

OUTPUT_DIR = "output"

# XBRL要素IDのキーワードマッピング
METRIC_KEYWORDS = {
    "NetAssets": [
        "NetAssets", "TotalNetAssets", "純資産合計",
        "EquityAttributableToOwnersOfParent",
    ],
    "TotalDebt": [
        "BorrowingsNoncurrent", "LongTermLoansPayable",
        "InterestBearingLiabilities", "有利子負債",
    ],
    "Cash": [
        "CashAndCashEquivalents", "CashAndDeposits", "現金及び現金同等物",
    ],
    "SharesOutstanding": [
        "NumberOfSharesOutstanding", "IssuedSharesNumber",
        "IssuedAndOutstandingSharesTotal", "発行済株式総数",
    ],
    "NetIncome": [
        "ProfitLossAttributableToOwnersOfParent",
        "NetIncome", "当期純利益",
        "ProfitAttributableToOwnersOfParent",
    ],
    "OperatingIncome": [
        "OperatingIncome", "営業利益", "OperatingProfitLoss",
    ],
    "EPS": [
        "BasicEarningsLossPerShare", "EarningsPerShare", "一株当たり当期純利益",
    ],
}


def load_prices() -> pd.DataFrame:
    path = f"{OUTPUT_DIR}/prices.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    return df.sort_values(["code", "Date"]).reset_index(drop=True)


def load_financials() -> pd.DataFrame:
    path = f"{OUTPUT_DIR}/financials.csv"
    if not os.path.exists(path):
        print(f"  警告: {path} が見つかりません")
        return pd.DataFrame()
    return pd.read_csv(path)


def extract_metrics(fin: pd.DataFrame) -> pd.DataFrame:
    """縦持ちXBRL DataFrameから主要指標を抽出して横持ちに変換"""
    if fin.empty:
        return pd.DataFrame()

    # 要素ID列と値列を特定
    id_col  = next((c for c in fin.columns if "要素" in c or c.lower() == "element_id"), fin.columns[0])
    val_col = next((c for c in fin.columns if "値" in c or c.lower() in ("value", "amount")), None)

    if val_col is None:
        return pd.DataFrame()

    rows = []
    for (edinet_code, period_end), grp in fin.groupby(["edinetCode", "periodEnd"]):
        row = {"edinetCode": edinet_code, "periodEnd": period_end}

        for metric, keywords in METRIC_KEYWORDS.items():
            val = None
            for kw in keywords:
                mask = grp[id_col].astype(str).str.contains(kw, case=False, na=False)
                candidates = grp[mask]
                if not candidates.empty:
                    numeric = pd.to_numeric(candidates[val_col], errors="coerce").dropna()
                    if not numeric.empty:
                        val = numeric.iloc[0]
                        break
            row[metric] = val
        rows.append(row)

    result = pd.DataFrame(rows)
    result["periodEnd"] = pd.to_datetime(result["periodEnd"], errors="coerce")
    return result


def merge_and_compute(prices: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    code_map = prices[["edinetCode", "code"]].drop_duplicates()
    metrics_m = metrics.merge(code_map, on="edinetCode", how="left")

    results = []
    for code, price_df in prices.groupby("code"):
        price_df = price_df.sort_values("Date").copy()
        m = metrics_m[metrics_m["code"] == code].sort_values("periodEnd")

        if m.empty:
            results.append(price_df)
            continue

        for col in ["NetAssets", "TotalDebt", "Cash", "SharesOutstanding",
                    "NetIncome", "OperatingIncome", "EPS"]:
            if col not in m.columns:
                m[col] = np.nan

        price_df = pd.merge_asof(
            price_df,
            m[["periodEnd", "NetAssets", "TotalDebt", "Cash",
               "SharesOutstanding", "NetIncome", "OperatingIncome", "EPS"]]
              .rename(columns={"periodEnd": "Date"}),
            on="Date",
            direction="backward",
        )

        price_df["MarketCap"] = price_df["Close"] * price_df["SharesOutstanding"]
        price_df["BPS"] = price_df["NetAssets"] / price_df["SharesOutstanding"]
        price_df["PBR"] = price_df["Close"] / price_df["BPS"].replace(0, np.nan)

        eps = price_df["EPS"].where(
            price_df["EPS"].notna(),
            price_df["NetIncome"] / price_df["SharesOutstanding"],
        )
        price_df["EPS_calc"] = eps
        price_df["PER"] = price_df["Close"] / eps.replace(0, np.nan)

        price_df["EV"] = (
            price_df["MarketCap"]
            + price_df["TotalDebt"].fillna(0)
            - price_df["Cash"].fillna(0)
        )
        results.append(price_df)

    return pd.concat(results, ignore_index=True)


def run():
    print("株価データ読み込み中...")
    prices = load_prices()
    print(f"  {len(prices):,} 行")

    print("財務データ読み込み中...")
    fin = load_financials()
    print(f"  {len(fin):,} 行")

    if fin.empty:
        print("財務データなし。株価データのみ保存します。")
        prices.to_csv(f"{OUTPUT_DIR}/valuation_history.csv", index=False, encoding="utf-8-sig")
        return

    print("財務指標を抽出中...")
    metrics = extract_metrics(fin)
    print(f"  {len(metrics):,} 件の決算データ")

    print("バリュエーション計算中...")
    valuation = merge_and_compute(prices, metrics)

    out_cols = [
        "Date", "edinetCode", "code",
        "Close", "Volume",
        "MarketCap", "EV",
        "PER", "PBR",
        "EPS_calc", "BPS",
        "NetAssets", "NetIncome", "OperatingIncome",
    ]
    out = valuation[[c for c in out_cols if c in valuation.columns]]
    path = f"{OUTPUT_DIR}/valuation_history.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n保存: {path} ({len(out):,} 行)")
    print(out.tail(10).to_string(index=False))


if __name__ == "__main__":
    run()
