"""
irbank特徴量とプライスデータをマージして features.csv を生成する

入力:
  output/irbank_features.csv  (feature_engineering.py の出力)
  output/price_clean_valuation.csv  (Google Driveからダウンロード)

出力:
  output/features.csv  (train_model.py への入力)

処理内容:
  - 決算提出日の翌営業日の株価・時価総額を取得
  - 株数 = 時価総額 / 終値 で算出
  - EPS = 当期純利益 × 1e6 / 株数
  - SPS = 売上高 × 1e6 / 株数  (irbank数値は百万円単位)
  - pre_close = 提出日翌営業日の終値
  - post_5d   = 提出日翌営業日+5営業日の終値  (目的変数用)
"""

import gc
import unicodedata
import numpy as np
import pandas as pd

IRBANK_FEATURES = "output/irbank_features.csv"
PRICE_CSV       = "output/price_clean_valuation.csv"
OUTPUT_PATH     = "output/features.csv"

# ── 列名候補 ─────────────────────────────────────────────────────────────────
CODE_CANDIDATES  = ["コード", "証券コード", "銘柄コード", "code", "Code", "ticker", "銘柄", "stock_code"]
DATE_CANDIDATES  = ["日付", "Date", "date", "取引日", "営業日", "trading_date"]
CLOSE_CANDIDATES = ["終値", "Close", "close", "adj_close", "Adj Close", "adjusted_close"]
MCAP_CANDIDATES  = ["時価総額", "marketCap", "market_cap", "MarketCap", "時価総額(円)", "時価総額_円"]


def normalize(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s)).replace(" ", "").replace("　", "").strip()


def detect_col(cols: list[str], candidates: list[str]) -> str | None:
    norm_cols = {normalize(c): c for c in cols}
    for cand in candidates:
        nc = normalize(cand)
        if nc in norm_cols:
            return norm_cols[nc]
    for cand in candidates:
        for col in cols:
            if cand.lower() in col.lower():
                return col
    return None


def load_price_data(path: str) -> tuple[pd.DataFrame, dict]:
    """プライスデータを読み込み、列名マッピングを返す"""
    print(f"プライスデータ読み込み中: {path}")
    print("  (2GB超の大きなファイルです。しばらくお待ちください...)")

    for enc in ["utf-8-sig", "cp932", "utf-8"]:
        try:
            # まず先頭1行だけ読んで列名確認
            sample = pd.read_csv(path, encoding=enc, nrows=3, dtype=str)
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"  {enc} 失敗: {e}")
    else:
        raise RuntimeError(f"プライスデータ読み込み失敗: {path}")

    cols = list(sample.columns)
    print(f"  列数: {len(cols)}")
    print(f"  列名: {cols}")

    col_code  = detect_col(cols, CODE_CANDIDATES)
    col_date  = detect_col(cols, DATE_CANDIDATES)
    col_close = detect_col(cols, CLOSE_CANDIDATES)
    col_mcap  = detect_col(cols, MCAP_CANDIDATES)

    print(f"  検出: code='{col_code}', date='{col_date}', close='{col_close}', 時価総額='{col_mcap}'")

    missing = [name for name, col in [("code", col_code), ("date", col_date), ("close", col_close)]
               if col is None]
    if missing:
        raise RuntimeError(
            f"必須列が見つかりません: {missing}\n"
            f"実際の列名: {cols}\n"
            f"CODE_CANDIDATES, DATE_CANDIDATES, CLOSE_CANDIDATES を更新してください"
        )

    use_cols = [c for c in [col_code, col_date, col_close, col_mcap] if c is not None]

    chunks = []
    for chunk in pd.read_csv(path, encoding=enc, dtype=str, usecols=use_cols,
                              chunksize=500_000, low_memory=False):
        chunk.columns = [normalize(c) for c in chunk.columns]
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    del chunks
    gc.collect()

    col_map = {
        "code":  normalize(col_code),
        "date":  normalize(col_date),
        "close": normalize(col_close),
        "mcap":  normalize(col_mcap) if col_mcap else None,
    }
    print(f"  読み込み完了: {len(df):,} 行")
    return df, col_map


def prepare_price(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """プライスデータを整理"""
    cn = col_map["code"]
    dn = col_map["date"]
    cl = col_map["close"]
    mc = col_map["mcap"]

    df[dn] = pd.to_datetime(df[dn], errors="coerce")
    df[cl] = pd.to_numeric(df[cl], errors="coerce")
    if mc:
        df[mc] = pd.to_numeric(df[mc], errors="coerce")

    # 証券コードを4桁文字列に統一
    df[cn] = df[cn].astype(str).str.strip().str.extract(r"(\d{4})", expand=False)
    df = df.dropna(subset=[cn, dn, cl])
    df = df.sort_values([cn, dn]).reset_index(drop=True)
    return df


def build_event_prices(irbank: pd.DataFrame, price: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    irbank の各行に対して提出日翌営業日の pre_close と
    さらに5営業日後の post_5d をアタッチする
    """
    cn = col_map["code"]
    dn = col_map["date"]
    cl = col_map["close"]
    mc = col_map["mcap"]

    irbank = irbank.copy()
    irbank["提出日"] = pd.to_datetime(irbank["提出日"], errors="coerce")
    irbank["コード4"] = irbank["コード"].astype(str).str.strip().str.extract(r"(\d{4})", expand=False)

    pre_rows    = []
    post5_rows  = []
    post20_rows = []

    for code, grp in price.groupby(cn):
        grp = grp.sort_values(dn).reset_index(drop=True)
        trading_days = grp[dn].values
        closes       = grp[cl].values
        mcaps        = grp[mc].values if mc else np.full(len(grp), np.nan)

        sub_irbank = irbank[irbank["コード4"] == str(code)]
        if sub_irbank.empty:
            continue

        for idx, row in sub_irbank.iterrows():
            t0 = row["提出日"]
            if pd.isna(t0):
                continue

            # 翌営業日以降の最初の取引日
            pos = np.searchsorted(trading_days, np.datetime64(t0 + pd.Timedelta(days=1)), side="left")
            if pos >= len(trading_days):
                continue

            pre_rows.append({
                "_irbank_idx": idx,
                "pre_close":   closes[pos],
                "pre_date":    trading_days[pos],
                "pre_mcap":    mcaps[pos],
            })

            # +5営業日
            pos5 = pos + 5
            if pos5 < len(trading_days):
                post5_rows.append({"_irbank_idx": idx, "post_5d": closes[pos5]})

            # +20営業日
            pos20 = pos + 20
            if pos20 < len(trading_days):
                post20_rows.append({"_irbank_idx": idx, "post_20d": closes[pos20]})

    pre_df   = pd.DataFrame(pre_rows).set_index("_irbank_idx")
    post_df  = pd.DataFrame(post5_rows).set_index("_irbank_idx")
    post20_df = pd.DataFrame(post20_rows).set_index("_irbank_idx")

    irbank = irbank.join(pre_df,   how="left")
    irbank = irbank.join(post_df,  how="left")
    irbank = irbank.join(post20_df, how="left")
    irbank = irbank.drop(columns=["コード4"])
    return irbank


def compute_eps_sps(df: pd.DataFrame) -> pd.DataFrame:
    """
    株数 = 時価総額 / 終値 から EPS・SPS を算出
    irbank の金額は百万円単位
    時価総額の単位が 百万円 の場合: 株数 = 時価総額 * 1e6 / 終値
    時価総額の単位が 円 の場合:     株数 = 時価総額 / 終値
    → 時価総額を終値で割った結果が 株数として妥当かどうか判断する
    """
    if "pre_mcap" not in df.columns or df["pre_mcap"].isna().all():
        print("  [warning] 時価総額データなし。EPS/SPS はスキップ。")
        return df

    if "pre_close" not in df.columns or df["pre_close"].isna().all():
        print("  [warning] 終値データなし。EPS/SPS はスキップ。")
        return df

    # 時価総額の単位判定（中央値で判定）
    ratio = df["pre_mcap"] / df["pre_close"].replace(0, np.nan)
    median_ratio = ratio.median()
    print(f"  時価総額/終値 中央値: {median_ratio:,.0f}")

    if median_ratio < 1e4:
        # 小さすぎる → 時価総額が百万円単位
        shares = df["pre_mcap"] * 1e6 / df["pre_close"].replace(0, np.nan)
        print("  時価総額単位: 百万円 と判定")
    else:
        # 時価総額が円単位
        shares = df["pre_mcap"] / df["pre_close"].replace(0, np.nan)
        print("  時価総額単位: 円 と判定")

    valid = shares.notna() & (shares > 0)

    # irbank の当期純利益・売上高は百万円単位
    if "当期純利益" in df.columns:
        df["EPS_計算"] = np.where(valid, df["当期純利益"] * 1e6 / shares, np.nan)
    if "売上高" in df.columns:
        df["SPS_計算"] = np.where(valid, df["売上高"] * 1e6 / shares, np.nan)
    df["株数_推定"] = np.where(valid, shares, np.nan)

    print(f"  EPS/SPS 算出: {valid.sum():,} 行")
    return df


def run(
    irbank_path: str = IRBANK_FEATURES,
    price_path:  str = PRICE_CSV,
    output_path: str = OUTPUT_PATH,
):
    import os
    if not os.path.exists(irbank_path):
        print(f"[error] {irbank_path} が見つかりません。feature_engineering.py を先に実行してください。")
        return
    if not os.path.exists(price_path):
        print(f"[error] {price_path} が見つかりません。download_data.py を先に実行してください。")
        return

    print(f"irbank特徴量読み込み: {irbank_path}")
    irbank = pd.read_csv(irbank_path, encoding="utf-8-sig", low_memory=False)
    print(f"  {len(irbank):,} 行 × {len(irbank.columns)} 列")

    price_df, col_map = load_price_data(price_path)
    price_df = prepare_price(price_df, col_map)

    print("イベント株価アタッチ中...")
    df = build_event_prices(irbank, price_df, col_map)
    del price_df
    gc.collect()

    print("EPS/SPS 計算中...")
    df = compute_eps_sps(df)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n保存完了: {output_path}")
    print(f"  {len(df):,} 行 × {len(df.columns)} 列")

    # 目的変数の確認
    if "pre_close" in df.columns and "post_5d" in df.columns:
        valid = df["pre_close"].notna() & df["post_5d"].notna()
        print(f"  株価マッチ率: {valid.mean():.1%} ({valid.sum():,} / {len(df):,})")

    return df


if __name__ == "__main__":
    run()
