"""
J-Quants API クライアント
JPX公式APIで日本株の株価・バリュエーション・財務データ(BS/PL/CF)を取得する

事前準備:
  1. https://jpx-jquants.com/ でアカウント登録（無料）
  2. メールアドレスとパスワードを環境変数に設定:
       export JQUANTS_EMAIL=your@email.com
       export JQUANTS_PASSWORD=yourpassword

インストール:
  pip install jquants-api-client pandas

使い方:
  python jquants_client.py
"""

import os
import pandas as pd
import jquantsapi

# ── 認証 ────────────────────────────────────────────────────────────────────

def get_client() -> jquantsapi.Client:
    email = os.environ.get("JQUANTS_EMAIL")
    password = os.environ.get("JQUANTS_PASSWORD")
    if not email or not password:
        raise EnvironmentError(
            "環境変数 JQUANTS_EMAIL と JQUANTS_PASSWORD を設定してください"
        )
    return jquantsapi.Client(mail_address=email, password=password)


# ── 株価・バリュエーション ───────────────────────────────────────────────────

def get_prices(
    client: jquantsapi.Client,
    code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    日次株価とバリュエーション指標を取得する

    Returns columns:
        Date, Code, Open, High, Low, Close, Volume,
        AdjustmentFactor, AdjustmentClose,
        MorningClose, AfternoonClose,
        PER, PBR, DividendYield
    """
    df = client.get_price_range(
        code=code,
        start_dt=start_date,
        end_dt=end_date,
    )
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


# ── 財務データ (BS / PL / CF) ────────────────────────────────────────────────

def get_financials(
    client: jquantsapi.Client,
    code: str,
) -> pd.DataFrame:
    """
    財務諸表データを取得する (BS / PL / CF 全項目含む)

    主要 columns:
        DisclosureDate, FiscalYear, FiscalQuarterType,
        -- PL --
        NetSales, OperatingProfit, OrdinaryProfit, NetIncome,
        -- BS --
        TotalAssets, TotalLiabilities, TotalNetAssets,
        -- CF --
        CashFlowFromOperatingActivities,
        CashFlowFromInvestingActivities,
        CashFlowFromFinancingActivities,
        CashAndCashEquivalents
    """
    df = client.get_statements_range(code=code)
    if df.empty:
        return df
    df["DisclosureDate"] = pd.to_datetime(df["DisclosureDate"])
    return df.sort_values("DisclosureDate").reset_index(drop=True)


# ── 上場銘柄一覧 ─────────────────────────────────────────────────────────────

def get_listed_info(client: jquantsapi.Client) -> pd.DataFrame:
    """全上場銘柄の基本情報を取得する"""
    return client.get_listed_info()


# ── サンプル実行 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli = get_client()

    TARGET_CODE = "7203"   # トヨタ自動車
    START = "2023-01-01"
    END   = "2024-12-31"

    print(f"=== 株価・バリュエーション ({TARGET_CODE}) ===")
    prices = get_prices(cli, TARGET_CODE, START, END)
    print(prices[["Date", "Close", "PER", "PBR", "DividendYield"]].tail(10).to_string(index=False))

    print(f"\n=== 財務データ BS/PL/CF ({TARGET_CODE}) ===")
    fins = get_financials(cli, TARGET_CODE)
    pl_cols = ["DisclosureDate", "FiscalYear", "NetSales", "OperatingProfit", "NetIncome"]
    bs_cols = ["DisclosureDate", "TotalAssets", "TotalLiabilities", "TotalNetAssets"]
    cf_cols = [
        "DisclosureDate",
        "CashFlowFromOperatingActivities",
        "CashFlowFromInvestingActivities",
        "CashFlowFromFinancingActivities",
    ]

    available = fins.columns.tolist()
    print("\n--- PL ---")
    print(fins[[c for c in pl_cols if c in available]].tail(5).to_string(index=False))
    print("\n--- BS ---")
    print(fins[[c for c in bs_cols if c in available]].tail(5).to_string(index=False))
    print("\n--- CF ---")
    print(fins[[c for c in cf_cols if c in available]].tail(5).to_string(index=False))

    # CSV保存
    prices.to_csv(f"prices_{TARGET_CODE}.csv", index=False)
    fins.to_csv(f"financials_{TARGET_CODE}.csv", index=False)
    print(f"\nCSV保存完了: prices_{TARGET_CODE}.csv / financials_{TARGET_CODE}.csv")
