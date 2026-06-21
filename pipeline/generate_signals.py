"""
直近の決算データに対してシグナルを生成する

入力:  output/features.csv, output/model_lgbm.pkl
出力:  output/signals.csv
"""

import os
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

OUTPUT_DIR  = "output"
MODEL_PATH  = f"{OUTPUT_DIR}/model_lgbm.pkl"
SIGNAL_PATH = f"{OUTPUT_DIR}/signals.csv"

TOP_N     = 30    # 上位N件を出力


def run():
    feat_path = f"{OUTPUT_DIR}/features.csv"
    if not os.path.exists(feat_path):
        print(f"[error] {feat_path} が見つかりません。")
        return
    if not os.path.exists(MODEL_PATH):
        print(f"[error] {MODEL_PATH} が見つかりません。train_model.py を先に実行してください。")
        return

    print("データ・モデル読み込み中...")
    df = pd.read_csv(feat_path, encoding="utf-8-sig", low_memory=False)

    # train_model と同様に _四半期_num を追加
    if "_四半期" in df.columns and "_四半期_num" not in df.columns:
        quarter_map = {"1Q": 1, "2Q": 2, "3Q": 3, "通期": 4}
        df["_四半期_num"] = df["_四半期"].map(quarter_map)

    with open(MODEL_PATH, "rb") as f:
        payload = pickle.load(f)
    model    = payload["model"]
    features = payload["features"]

    # 最新の決算データのみ対象
    date_col = "イベント日" if "イベント日" in df.columns else ("提出日" if "提出日" in df.columns else None)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        cutoff = datetime.now() - timedelta(days=90)   # 直近90日
        recent = df[df[date_col] >= cutoff].copy()
        if recent.empty:
            print(f"  直近90日のデータなし。全データで実行します。")
            recent = df.copy()
    else:
        recent = df.copy()

    available = [c for c in features if c in recent.columns]
    if not available:
        print("[error] 特徴量が一致しません")
        return

    X = recent[available].astype(float)
    recent["score"]  = model.predict_proba(X)[:, 1]
    threshold = recent["score"].quantile(0.8)
    threshold = max(threshold, 0.3)
    print(f"  シグナル閾値 (上位20%): {threshold:.3f}")
    recent["signal"] = (recent["score"] >= threshold).astype(int)

    # スコア上位を出力
    out = recent[recent["signal"] == 1].sort_values("score", ascending=False)

    display_cols = ["コード", "年度_num", date_col, "score", "signal",
                    "営業利益_通期_ガイダンス変化率", "当期純利益_通期_ガイダンス変化率",
                    "売上変化率_YoY", "営業利益率_YoY",
                    "営業利益_達成率_累計_通期G"]
    display_cols = [c for c in display_cols if c and c in out.columns]

    out = out[display_cols].head(TOP_N)
    out.to_csv(SIGNAL_PATH, index=False, encoding="utf-8-sig")

    print(f"\n=== 買いシグナル (上位{TOP_N}件) ===")
    print(out.to_string(index=False))
    print(f"\n保存: {SIGNAL_PATH}")
    print(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    run()
