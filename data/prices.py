"""
yfinance で日本株の株価・バリュエーションを取得する

東証銘柄コードに ".T" を付けてYahoo Financeから取得。
20年以上の長期データが無料で利用可能。
"""

import pandas as pd
import yfinance as yf


def get_prices(code: str, start: str, end: str) -> pd.DataFrame:
    """
    日次株価を取得する

    Args:
        code:  証券コード（例: "7203"）
        start: 開始日 "YYYY-MM-DD"
        end:   終了日 "YYYY-MM-DD"

    Returns:
        columns: Date, Open, High, Low, Close, Volume, Dividends, Stock_Splits
    """
    ticker = yf.Ticker(f"{code}.T")
    df = ticker.history(start=start, end=end, auto_adjust=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"
    return df.reset_index()


def get_valuation(code: str) -> dict:
    """
    バリュエーション指標を取得する (最新値)

    Returns: PER, PBR, 配当利回り, 時価総額 等
    """
    ticker = yf.Ticker(f"{code}.T")
    info = ticker.info
    return {
        "trailingPE":    info.get("trailingPE"),
        "priceToBook":   info.get("priceToBook"),
        "dividendYield": info.get("dividendYield"),
        "marketCap":     info.get("marketCap"),
        "enterpriseValue": info.get("enterpriseValue"),
        "forwardPE":     info.get("forwardPE"),
        "pegRatio":      info.get("pegRatio"),
    }


if __name__ == "__main__":
    CODE = "7203"
    prices = get_prices(CODE, "2014-01-01", "2024-12-31")
    print(prices.tail())
    print("\nValuation:", get_valuation(CODE))
