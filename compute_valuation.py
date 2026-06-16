"""
株価（yfinance）× EDINET財務データからバリュエーション時系列を計算する

計算式:
    時価総額     = 株価 × 発行済株数
    PBR          = 株価 ÷ BPS  (BPS = 純資産 ÷ 発行済株数)
    PER          = 株価 ÷ EPS  (EPS = 当期純利益 ÷ 発行済株数)
    EV           = 時価総額 + 有利子負債 - 現金及び現金同等物
    EV/EBITDA    = EV ÷ EBITDA (EBITDA = 営業利益 + 減価償却費)

入力:
    output/prices.csv  - 日次株価 (yfinanceで取得)
    output/bs.csv      - 貸借対照表 (EDINETで取得)
    output/pl.csv      - 損益計算書 (EDINETで取得)

出力:
    output/valuation_history.csv
"""

import pandas as pd
import numpy as np
import os

OUTPUT_DIR = "output"


def load_prices() -> pd.DataFrame:
    path = f"{OUTPUT_DIR}/prices.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values(["code", "Date"]).reset_index(drop=True)
    return df


def load_financials() -> tuple[pd.DataFrame, pd.DataFrame]:
    bs = pd.read_csv(f"{OUTPUT_DIR}/bs.csv")
    pl = pd.read_csv(f"{OUTPUT_DIR}/pl.csv")
    return bs, pl


def extract_bs_metrics(bs: pd.DataFrame) -> pd.DataFrame:
    """
    貸借対照表から必要な指標を抽出する

    Returns columns: edinetCode, periodEnd, NetAssets, TotalDebt, Cash, SharesOutstanding
    """
    # EDINETのXBRLタグ名は企業によって微妙に異なる場合がある
    # 主要なタグ名のパターンを複数チェックする
    col_candidates = {
        "NetAssets": [
            "NetAssets", "純資産合計", "EquityAttributableToOwnersOfParent",
            "TotalNetAssets",
        ],
        "TotalDebt": [
            "BorrowingsNoncurrent", "LongTermLoansPayable", "有利子負債合計",
            "InterestBearingLiabilities",
        ],
        "Cash": [
            "CashAndCashEquivalents", "現金及び現金同等物", "CashAndDeposits",
        ],
        "SharesOutstanding": [
            "NumberOfSharesOutstanding", "IssuedSharesNumber",
            "発行済株式総数", "IssuedAndOutstandingSharesTotal",
        ],
    }

    rows = []
    for _, grp in bs.groupby(["edinetCode", "periodEnd"]):
        row = {
            "edinetCode": grp["edinetCode"].iloc[0],
            "periodEnd":  grp["periodEnd"].iloc[0],
        }
        for metric, candidates in col_candidates.items():
            val = None
            for col in candidates:
                if col in grp.columns:
                    v = grp[col].dropna()
                    if not v.empty:
                        val = pd.to_numeric(v.iloc[0], errors="coerce")
                        break
            row[metric] = val
        rows.append(row)

    result = pd.DataFrame(rows)
    result["periodEnd"] = pd.to_datetime(result["periodEnd"], errors="coerce")
    return result


def extract_pl_metrics(pl: pd.DataFrame) -> pd.DataFrame:
    """
    損益計算書から必要な指標を抽出する

    Returns columns: edinetCode, periodEnd, NetIncome, OperatingIncome, EPS
    """
    col_candidates = {
        "NetIncome": [
            "ProfitLossAttributableToOwnersOfParent",
            "NetIncome", "当期純利益", "ProfitAttributableToOwnersOfParent",
        ],
        "OperatingIncome": [
            "OperatingIncome", "営業利益", "OperatingProfitLoss",
        ],
        "EPS": [
            "BasicEarningsLossPerShare", "EarningsPerShare",
            "一株当たり当期純利益",
        ],
    }

    rows = []
    for _, grp in pl.groupby(["edinetCode", "periodEnd"]):
        row = {
            "edinetCode": grp["edinetCode"].iloc[0],
            "periodEnd":  grp["periodEnd"].iloc[0],
        }
        for metric, candidates in col_candidates.items():
            val = None
            for col in candidates:
                if col in grp.columns:
                    v = grp[col].dropna()
                    if not v.empty:
                        val = pd.to_numeric(v.iloc[0], errors="coerce")
                        break
            row[metric] = val
        rows.append(row)

    result = pd.DataFrame(rows)
    result["periodEnd"] = pd.to_datetime(result["periodEnd"], errors="coerce")
    return result


def merge_and_compute(
    prices: pd.DataFrame,
    bs_metrics: pd.DataFrame,
    pl_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """
    株価と財務データをマージしてバリュエーションを計算する

    財務データは決算期末時点の値を、次の決算期末まで forward-fill する
    """
    # EDINETコード → 証券コードのマッピング（prices.csvのcode列を使用）
    code_map = prices[["edinetCode", "code"]].drop_duplicates()

    bs_m = bs_metrics.merge(code_map, on="edinetCode", how="left")
    pl_m = pl_metrics.merge(code_map, on="edinetCode", how="left")

    results = []
    for code, price_df in prices.groupby("code"):
        edinet_code = price_df["edinetCode"].iloc[0]
        price_df = price_df.sort_values("Date").copy()

        bs_c = bs_m[bs_m["code"] == code].sort_values("periodEnd")
        pl_c = pl_m[pl_m["code"] == code].sort_values("periodEnd")

        if bs_c.empty and pl_c.empty:
            results.append(price_df)
            continue

        # 財務データを日次にマージ（as_of join: 決算日以降の株価に適用）
        price_df = pd.merge_asof(
            price_df.sort_values("Date"),
            bs_c[["periodEnd", "NetAssets", "TotalDebt", "Cash", "SharesOutstanding"]]
              .rename(columns={"periodEnd": "Date"}),
            on="Date",
            direction="backward",
        )
        price_df = pd.merge_asof(
            price_df.sort_values("Date"),
            pl_c[["periodEnd", "NetIncome", "OperatingIncome", "EPS"]]
              .rename(columns={"periodEnd": "Date"}),
            on="Date",
            direction="backward",
        )

        # バリュエーション計算
        price_df["MarketCap"] = price_df["Close"] * price_df["SharesOutstanding"]

        # BPS, PBR
        price_df["BPS"] = price_df["NetAssets"] / price_df["SharesOutstanding"]
        price_df["PBR"] = price_df["Close"] / price_df["BPS"]

        # EPS, PER
        # EPSが直接あればそれを使う、なければNetIncomeから計算
        eps = price_df["EPS"].where(
            price_df["EPS"].notna(),
            price_df["NetIncome"] / price_df["SharesOutstanding"],
        )
        price_df["EPS_calc"] = eps
        price_df["PER"] = price_df["Close"] / eps.replace(0, np.nan)

        # EV = 時価総額 + 有利子負債 - 現金
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
    bs, pl = load_financials()
    print(f"  BS: {len(bs):,} 行 / PL: {len(pl):,} 行")

    print("財務指標を抽出中...")
    bs_metrics = extract_bs_metrics(bs)
    pl_metrics = extract_pl_metrics(pl)

    print("バリュエーション計算中...")
    valuation = merge_and_compute(prices, bs_metrics, pl_metrics)

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
