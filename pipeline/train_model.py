"""
LightGBMモデルのトレーニング

入力:  output/features.csv
出力:  output/model_lgbm.pkl, output/feature_importance.csv

目的変数: 決算発表翌日〜5営業日の株価変化率が5%以上上昇(=1), それ以外(=0)
"""

import os
import pickle
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, classification_report

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    print("[warning] lightgbm未インストール。pip install lightgbm")

OUTPUT_DIR = "output"
MODEL_PATH  = f"{OUTPUT_DIR}/model_lgbm.pkl"
FEAT_IMP_PATH = f"{OUTPUT_DIR}/feature_importance.csv"

# ── 特徴量定義 ────────────────────────────────────────────────────────────
FEATURE_COLS = [
    # ガイダンス変化率（通期）
    "売上高_通期_ガイダンス変化率",
    "営業利益_通期_ガイダンス変化率",
    "経常利益_通期_ガイダンス変化率",
    "当期純利益_通期_ガイダンス変化率",
    "EPS_通期_ガイダンス変化率",
    "営業利益率_通期_ガイダンス変化率",
    "コスト率_通期_ガイダンス変化率",
    # ガイダンス変化率（2Q）
    "売上高_2Q_ガイダンス変化率",
    "営業利益_2Q_ガイダンス変化率",
    "当期純利益_2Q_ガイダンス変化率",
    # 前年乖離
    "売上高_ガイダンス実績乖離率_前年",
    "営業利益_ガイダンス実績乖離率_前年",
    "当期純利益_ガイダンス実績乖離率_前年",
    # YoY実績
    "売上変化率_YoY",
    "営業利益率_YoY",
    "コスト率_YoY",
    "売上変化率_単期YoY",
    "営業利益率_単期YoY",
    # 3年平均・リスク
    "売上変化率_YoY_３年平均",
    "営業利益率_YoY_３年平均",
    "売上変化率_YoY_３年リスク",
    "営業利益率_YoY_３年リスク",
    # 達成率
    "売上高_達成率_累計_通期G",
    "営業利益_達成率_累計_通期G",
    "当期純利益_達成率_累計_通期G",
    "売上高_達成率_累計_2QG",
    "営業利益_達成率_累計_2QG",
    # 修正回数
    "修正回数",
    # 赤転/黒転フラグ
    "営業利益_単期_赤転",
    "営業利益_単期_黒転",
    "当期純利益_単期_赤転",
    "当期純利益_単期_黒転",
    "営業利益_実績_累計_赤転",
    "当期純利益_実績_累計_黒転",
    # 収益構造
    "営業利益率",
    "コスト率",
    "営業外寄与",
    "最終調整寄与",
]

TARGET_COL = "target_20d_up10pct"


def build_target(df: pd.DataFrame) -> pd.DataFrame:
    """post_20d (20営業日後株価) / pre_close で10%超上昇を目的変数に"""
    if "post_20d" in df.columns and "pre_close" in df.columns:
        ret = (df["post_20d"] / df["pre_close"].replace(0, np.nan) - 1)
    elif "post_5d" in df.columns and "pre_close" in df.columns:
        print("  [warning] post_20d が見つかりません。post_5d で代用します。")
        ret = (df["post_5d"] / df["pre_close"].replace(0, np.nan) - 1)
    else:
        print("  [warning] 株価列が見つかりません。ダミー目的変数を使用。")
        np.random.seed(42)
        df[TARGET_COL] = (np.random.rand(len(df)) > 0.95).astype(int)
        return df

    df[TARGET_COL] = (ret >= 0.10).astype(int)
    print(f"  目的変数分布: {df[TARGET_COL].value_counts().to_dict()}")
    return df


QUARTER_MAP = {"1Q": 1, "2Q": 2, "3Q": 3, "通期": 4}


def select_features(df: pd.DataFrame) -> list[str]:
    # _四半期を数値化してFEATURE_COLSに追加
    if "_四半期" in df.columns:
        df["_四半期_num"] = df["_四半期"].map(QUARTER_MAP)
    available = [c for c in FEATURE_COLS if c in df.columns]
    if "_四半期_num" in df.columns:
        available = ["_四半期_num"] + available
    print(f"  利用可能な特徴量: {len(available)} / {len(FEATURE_COLS) + 1}")
    return available


def train(df: pd.DataFrame):
    if not HAS_LIGHTGBM:
        print("[error] lightgbmをインストールしてください: pip install lightgbm")
        return

    df = build_target(df)

    # 時系列split: train<=2022, val=2023, test>=2024
    if "年度_num" in df.columns:
        train_df = df[df["年度_num"] <= 2022]
        val_df   = df[df["年度_num"] == 2023]
        test_df  = df[df["年度_num"] >= 2024]
    else:
        n = len(df)
        train_df = df.iloc[:int(n * 0.7)]
        val_df   = df.iloc[int(n * 0.7):int(n * 0.85)]
        test_df  = df.iloc[int(n * 0.85):]

    print(f"  train: {len(train_df)}, val: {len(val_df)}, test: {len(test_df)}")

    features = select_features(df)
    if not features:
        print("[error] 特徴量が見つかりません")
        return

    X_train = train_df[features].astype(float)
    y_train = train_df[TARGET_COL].astype(int)
    X_val   = val_df[features].astype(float)
    y_val   = val_df[TARGET_COL].astype(int)
    X_test  = test_df[features].astype(float)
    y_test  = test_df[TARGET_COL].astype(int)

    pos_rate = y_train.mean()
    scale_pos = (1 - pos_rate) / pos_rate if pos_rate > 0 else 1.0

    params = {
        "objective":        "binary",
        "metric":           "auc",
        "num_leaves":       63,
        "learning_rate":    0.05,
        "n_estimators":     500,
        "min_child_samples": 20,
        "subsample":        0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": scale_pos,
        "random_state":     42,
        "verbose":          -1,
    }

    model = lgb.LGBMClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)],
    )

    # 評価
    if len(y_val) > 0 and y_val.nunique() > 1:
        val_auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])
        print(f"\n  Val AUC: {val_auc:.4f}")
    if len(y_test) > 0 and y_test.nunique() > 1:
        test_auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
        print(f"  Test AUC: {test_auc:.4f}")
        print(classification_report(y_test, model.predict(X_test)))

    # 保存
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "features": features}, f)
    print(f"\n  モデル保存: {MODEL_PATH}")

    # 特徴量重要度
    imp = pd.DataFrame({
        "feature":   features,
        "importance": model.feature_importances_,
    }).sort_values("importance", ascending=False)
    imp.to_csv(FEAT_IMP_PATH, index=False, encoding="utf-8-sig")
    print(f"  特徴量重要度: {FEAT_IMP_PATH}")
    print(imp.head(15).to_string(index=False))

    return model, features


def run():
    path = f"{OUTPUT_DIR}/features.csv"
    if not os.path.exists(path):
        print(f"[error] {path} が見つかりません。feature_engineering.py を先に実行してください。")
        return

    print(f"データ読み込み: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    print(f"  {len(df):,} 行 × {len(df.columns)} 列")

    train(df)


if __name__ == "__main__":
    run()
