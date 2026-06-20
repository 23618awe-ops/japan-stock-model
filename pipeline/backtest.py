"""
バックテスト: モデルのシグナルに基づいた仮想取引のリターン計算

入力:  output/features.csv, output/model_lgbm.pkl
出力:  output/backtest_result.csv, output/backtest_summary.csv
"""

import os
import pickle
import numpy as np
import pandas as pd

OUTPUT_DIR = "output"
MODEL_PATH = f"{OUTPUT_DIR}/model_lgbm.pkl"

THRESHOLD   = 0.5   # シグナル閾値
HOLD_DAYS   = 5     # 保有日数
TOP_N       = 20    # 上位N銘柄シグナル


def run():
    feat_path = f"{OUTPUT_DIR}/features.csv"
    if not os.path.exists(feat_path):
        print(f"[error] {feat_path} が見つかりません。")
        return
    if not os.path.exists(MODEL_PATH):
        print(f"[error] {MODEL_PATH} が見つかりません。train_model.py を先に実行してください。")
        return

    print("データ読み込み中...")
    df = pd.read_csv(feat_path, encoding="utf-8-sig", low_memory=False)

    print("モデル読み込み中...")
    with open(MODEL_PATH, "rb") as f:
        payload = pickle.load(f)
    model    = payload["model"]
    features = payload["features"]

    available = [c for c in features if c in df.columns]
    if not available:
        print("[error] 特徴量が一致しません")
        return

    X = df[available].astype(float)
    df["score"] = model.predict_proba(X)[:, 1]
    df["signal"] = (df["score"] >= THRESHOLD).astype(int)

    # リターン計算（20営業日後を優先）
    if "post_20d" in df.columns and "pre_close" in df.columns:
        df["actual_return"] = df["post_20d"] / df["pre_close"].replace(0, np.nan) - 1
    elif "post_5d" in df.columns and "pre_close" in df.columns:
        df["actual_return"] = df["post_5d"] / df["pre_close"].replace(0, np.nan) - 1
    elif "T_post_5d" in df.columns and "T_pre_close" in df.columns:
        df["actual_return"] = df["T_post_5d"] / df["T_pre_close"].replace(0, np.nan) - 1
    else:
        print("[warning] 株価リターン列が見つかりません。スコアのみ出力します。")
        df["actual_return"] = np.nan

    # テスト期間のみバックテスト
    date_col = "提出日" if "提出日" in df.columns else None
    if date_col and "年度_num" in df.columns:
        test_df = df[df["年度_num"] >= 2024].copy()
    else:
        test_df = df.copy()

    test_df = test_df.sort_values(date_col or df.columns[0])

    # シグナル銘柄のリターン集計
    signal_df = test_df[test_df["signal"] == 1].copy()
    no_signal_df = test_df[test_df["signal"] == 0].copy()

    def summarize(sub, label):
        if sub.empty or sub["actual_return"].isna().all():
            return {"group": label, "count": len(sub), "avg_return": np.nan, "win_rate": np.nan, "sharpe": np.nan}
        r = sub["actual_return"].dropna()
        return {
            "group":      label,
            "count":      len(r),
            "avg_return": r.mean(),
            "median_return": r.median(),
            "win_rate":   (r > 0).mean(),
            "up10pct_rate": (r >= 0.10).mean(),
            "sharpe":     r.mean() / r.std() if r.std() > 0 else np.nan,
            "max":        r.max(),
            "min":        r.min(),
        }

    summary = pd.DataFrame([
        summarize(signal_df, "signal=1 (買いシグナル)"),
        summarize(no_signal_df, "signal=0 (非シグナル)"),
        summarize(test_df, "全体"),
    ])

    # 月次累積リターン（シグナルあり）
    if date_col and not signal_df.empty:
        signal_df[date_col] = pd.to_datetime(signal_df[date_col])
        monthly = signal_df.groupby(signal_df[date_col].dt.to_period("M"))["actual_return"].mean()
        monthly = monthly.reset_index()
        monthly.columns = ["month", "avg_return"]
        monthly["cumulative"] = (1 + monthly["avg_return"].fillna(0)).cumprod() - 1
        monthly_path = f"{OUTPUT_DIR}/backtest_monthly.csv"
        monthly.to_csv(monthly_path, index=False, encoding="utf-8-sig")
        print(f"  月次リターン: {monthly_path}")

    # 結果保存
    out_cols = ["コード", "年度_num", date_col, "score", "signal", "actual_return"] if date_col else ["コード", "年度_num", "score", "signal", "actual_return"]
    out_cols = [c for c in out_cols if c and c in test_df.columns]
    test_df[out_cols].to_csv(f"{OUTPUT_DIR}/backtest_result.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(f"{OUTPUT_DIR}/backtest_summary.csv", index=False, encoding="utf-8-sig")

    print(f"\n=== バックテスト結果 ===")
    print(summary.to_string(index=False))
    print(f"\n保存: {OUTPUT_DIR}/backtest_result.csv, {OUTPUT_DIR}/backtest_summary.csv")


if __name__ == "__main__":
    run()
