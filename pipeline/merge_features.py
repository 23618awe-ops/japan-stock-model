"""
irbank特徴量とプライスデータをマージして features.csv を生成する

入力:
  output/irbank_features.csv  (feature_engineering.py の出力)
  output/price_clean_valuation.csv  (Google Driveからダウンロード)

出力:
  output/features.csv  (train_model.py への入力)

処理内容:
  - イベント（実績発表 / ガイダンス修正）ごとに1行を生成
  - 各イベント時点の「最新実績」+「最新ガイダンス」を紐づけ
  - ガイダンス修正のみのイベントでは直前実績を複製
  - 翌営業日の始値→終値リターンを目的変数に
  - 時価総額/終値から株数を推定し EPS/SPS を算出
"""

import gc
import unicodedata
import numpy as np
import pandas as pd

IRBANK_FEATURES = "output/irbank_features.csv"
PRICE_CSV       = "output/price_clean_valuation.csv"
OUTPUT_PATH     = "output/features.csv"

CODE_CANDIDATES  = ["コード", "証券コード", "銘柄コード", "code", "Code", "ticker", "銘柄", "stock_code"]
DATE_CANDIDATES  = ["日付", "Date", "date", "取引日", "営業日", "trading_date"]
CLOSE_CANDIDATES = ["終値", "Close", "close", "adj_close", "Adj Close", "adjusted_close"]
OPEN_CANDIDATES  = ["始値", "Open", "open"]
MCAP_CANDIDATES  = ["時価総額", "marketCap", "market_cap", "MarketCap", "時価総額(円)", "時価総額_円", "MarketCap"]


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
    print(f"プライスデータ読み込み中: {path}")

    for enc in ["utf-8-sig", "cp932", "utf-8"]:
        try:
            sample = pd.read_csv(path, encoding=enc, nrows=3, dtype=str)
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"  {enc} 失敗: {e}")
    else:
        raise RuntimeError(f"プライスデータ読み込み失敗: {path}")

    cols = list(sample.columns)
    print(f"  列数: {len(cols)}, 列名: {cols}")

    col_code  = detect_col(cols, CODE_CANDIDATES)
    col_date  = detect_col(cols, DATE_CANDIDATES)
    col_close = detect_col(cols, CLOSE_CANDIDATES)
    col_open  = detect_col(cols, OPEN_CANDIDATES)
    col_mcap  = detect_col(cols, MCAP_CANDIDATES)

    print(f"  検出: code='{col_code}', date='{col_date}', open='{col_open}', close='{col_close}', mcap='{col_mcap}'")

    missing = [name for name, col in [("code", col_code), ("date", col_date), ("close", col_close)]
               if col is None]
    if missing:
        raise RuntimeError(f"必須列が見つかりません: {missing}\n実際の列名: {cols}")

    use_cols = [c for c in [col_code, col_date, col_open, col_close, col_mcap] if c is not None]

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
        "open":  normalize(col_open) if col_open else None,
        "mcap":  normalize(col_mcap) if col_mcap else None,
    }
    print(f"  読み込み完了: {len(df):,} 行")
    return df, col_map


def prepare_price(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    cn = col_map["code"]
    dn = col_map["date"]
    cl = col_map["close"]
    op = col_map["open"]
    mc = col_map["mcap"]

    df[dn] = pd.to_datetime(df[dn], errors="coerce")
    df[cl] = pd.to_numeric(df[cl], errors="coerce")
    if op:
        df[op] = pd.to_numeric(df[op], errors="coerce")
    if mc:
        df[mc] = pd.to_numeric(df[mc], errors="coerce")

    df[cn] = df[cn].astype(str).str.strip().str.extract(r"(\d{4})", expand=False)
    df = df.dropna(subset=[cn, dn, cl])
    df = df.sort_values([cn, dn]).reset_index(drop=True)
    return df


def build_event_rows(irbank: pd.DataFrame, price: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    イベントごとに1行生成:
      - 実績発表: 新しい実績 + その時点の最新ガイダンス
      - ガイダンス修正（実績なし同日）: 直前実績を複製 + 新しいガイダンス
      - 翌営業日の始値→終値リターンを目的変数
    """
    cn = col_map["code"]
    dn = col_map["date"]
    cl = col_map["close"]
    op = col_map["open"]
    mc = col_map["mcap"]

    irbank = irbank.copy()
    irbank["提出日"] = pd.to_datetime(irbank["提出日"], errors="coerce")
    irbank["コード4"] = irbank["コード"].astype(str).str.strip().str.extract(r"(\d{4})", expand=False)

    # irbank の行を実績 / ガイダンス に分類
    is_actual_mask   = ~irbank["区分"].str.contains("予想|修正", na=False)
    is_guidance_mask = irbank["区分"].str.contains("予想|修正", na=False)

    result_rows = []

    for code in irbank["コード4"].dropna().unique():
        sub = irbank[irbank["コード4"] == code].sort_values("提出日")
        if sub.empty:
            continue

        # 株価データ
        price_sub = price[price[cn] == code].sort_values(dn).reset_index(drop=True)
        if price_sub.empty:
            continue
        trading_days = price_sub[dn].values
        closes = price_sub[cl].values
        opens = price_sub[op].values if op else np.full(len(price_sub), np.nan)
        mcaps = price_sub[mc].values if mc else np.full(len(price_sub), np.nan)

        # 実績行と予想/修正行を分離
        actuals  = sub[is_actual_mask.loc[sub.index]].copy()
        guidance = sub[is_guidance_mask.loc[sub.index]].copy()

        # 全イベント日（提出日）を収集
        event_dates = sub["提出日"].dropna().unique()
        event_dates = np.sort(event_dates)

        # 最新の実績を追跡するための状態
        latest_actual = None

        for evt_date in event_dates:
            evt_rows = sub[sub["提出日"] == evt_date]
            actual_on_date  = evt_rows[is_actual_mask.loc[evt_rows.index]]
            guidance_on_date = evt_rows[is_guidance_mask.loc[evt_rows.index]]

            # 実績があれば更新
            if not actual_on_date.empty:
                latest_actual = actual_on_date.iloc[-1]

            if latest_actual is None:
                continue

            # 最新ガイダンスを取得（この日以前の最新）
            past_guidance = guidance[guidance["提出日"] <= evt_date]
            latest_guidance = past_guidance.iloc[-1] if not past_guidance.empty else None

            # 翌営業日を見つける
            pos = np.searchsorted(trading_days, np.datetime64(pd.Timestamp(evt_date) + pd.Timedelta(days=1)), side="left")
            if pos >= len(trading_days):
                continue

            # 1行生成: 実績データ + ガイダンスデータ + 株価データ
            row_data = latest_actual.to_dict()

            # ガイダンス情報をマージ（列名衝突を避ける）
            if latest_guidance is not None:
                for col_name in latest_guidance.index:
                    if "ガイダンス" in col_name or col_name.endswith("_k"):
                        row_data[col_name] = latest_guidance[col_name]
                # ガイダンスの区分・年度情報も保持
                row_data["ガイダンス区分"] = latest_guidance["区分"]
                row_data["ガイダンス年度_num"] = latest_guidance.get("年度_num", np.nan)
                row_data["ガイダンス提出日"] = latest_guidance["提出日"]

            # イベント日を記録（実績提出日ではなくイベント発生日）
            row_data["イベント日"] = evt_date
            row_data["イベント種別"] = "実績" if not actual_on_date.empty else "ガイダンス修正"

            # 株価データ
            row_data["event_open"]  = opens[pos]
            row_data["event_close"] = closes[pos]
            row_data["event_date"]  = trading_days[pos]
            row_data["event_mcap"]  = mcaps[pos]

            # 目的変数: 翌営業日の始値→終値リターン
            if not np.isnan(opens[pos]) and opens[pos] != 0:
                row_data["target_return"] = closes[pos] / opens[pos] - 1
            else:
                row_data["target_return"] = np.nan

            result_rows.append(row_data)

    if not result_rows:
        print("  [warning] イベント行が1つも生成されませんでした")
        return pd.DataFrame()

    df_out = pd.DataFrame(result_rows)
    df_out = df_out.drop(columns=["コード4"], errors="ignore")
    print(f"  イベント行生成: {len(df_out):,} 行")
    print(f"  イベント種別: {df_out['イベント種別'].value_counts().to_dict()}")
    return df_out


def compute_eps_sps(df: pd.DataFrame) -> pd.DataFrame:
    if "event_mcap" not in df.columns or df["event_mcap"].isna().all():
        print("  [warning] 時価総額データなし。EPS/SPS はスキップ。")
        return df

    if "event_close" not in df.columns or df["event_close"].isna().all():
        print("  [warning] 終値データなし。EPS/SPS はスキップ。")
        return df

    ratio = df["event_mcap"] / df["event_close"].replace(0, np.nan)
    median_ratio = ratio.median()
    print(f"  時価総額/終値 中央値: {median_ratio:,.0f}")

    if median_ratio < 1e4:
        shares = df["event_mcap"] * 1e6 / df["event_close"].replace(0, np.nan)
        print("  時価総額単位: 百万円 と判定")
    else:
        shares = df["event_mcap"] / df["event_close"].replace(0, np.nan)
        print("  時価総額単位: 円 と判定")

    valid = shares.notna() & (shares > 0)

    if "当期純利益" in df.columns:
        df["EPS_計算"] = np.where(valid, pd.to_numeric(df["当期純利益"], errors="coerce") * 1e6 / shares, np.nan)
    if "売上高" in df.columns:
        df["SPS_計算"] = np.where(valid, pd.to_numeric(df["売上高"], errors="coerce") * 1e6 / shares, np.nan)
    if "営業利益" in df.columns:
        df["OPPS_計算"] = np.where(valid, pd.to_numeric(df["営業利益"], errors="coerce") * 1e6 / shares, np.nan)
    df["株数_推定"] = np.where(valid, shares, np.nan)

    print(f"  EPS/SPS/OPPS 算出: {valid.sum():,} 行")
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

    print("イベント行生成中...")
    df = build_event_rows(irbank, price_df, col_map)
    del price_df
    gc.collect()

    if df.empty:
        print("[error] イベント行が生成されませんでした")
        return

    print("EPS/SPS 計算中...")
    df = compute_eps_sps(df)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n保存完了: {output_path}")
    print(f"  {len(df):,} 行 × {len(df.columns)} 列")

    valid = df["target_return"].notna()
    print(f"  目的変数(始値→終値)有効率: {valid.mean():.1%} ({valid.sum():,} / {len(df):,})")
    if valid.any():
        r = df.loc[valid, "target_return"]
        print(f"  リターン平均: {r.mean():.4f}, 中央値: {r.median():.4f}")

    return df


if __name__ == "__main__":
    run()
