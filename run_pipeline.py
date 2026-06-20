"""
パイプライン全体を順番に実行するエントリポイント

ステップ:
  1. Google Driveからデータダウンロード
  2. 特徴量エンジニアリング
  3. LightGBMモデルのトレーニング
  4. バックテスト
  5. シグナル生成
"""

import sys
import os
import argparse

# outputディレクトリを作成
os.makedirs("output", exist_ok=True)


def step(name: str, fn):
    print(f"\n{'='*60}")
    print(f"  STEP: {name}")
    print(f"{'='*60}")
    try:
        fn()
    except Exception as e:
        print(f"\n[FAILED] {name}: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description="Japan Stock ML Pipeline")
    parser.add_argument("--skip-download",   action="store_true", help="データダウンロードをスキップ")
    parser.add_argument("--skip-features",   action="store_true", help="特徴量エンジニアリング(irbank)をスキップ")
    parser.add_argument("--skip-merge",      action="store_true", help="特徴量マージ(irbank×株価)をスキップ")
    parser.add_argument("--skip-train",      action="store_true", help="モデルトレーニングをスキップ")
    parser.add_argument("--skip-backtest",   action="store_true", help="バックテストをスキップ")
    parser.add_argument("--skip-signals",    action="store_true", help="シグナル生成をスキップ")
    parser.add_argument("--signals-only",    action="store_true", help="シグナル生成のみ実行")
    args = parser.parse_args()

    from pipeline import download_data, feature_engineering, merge_features, train_model, backtest, generate_signals

    if args.signals_only:
        step("シグナル生成", generate_signals.run)
        return

    if not args.skip_download:
        step("データダウンロード (Google Drive)", download_data.run)

    if not args.skip_features:
        step("特徴量エンジニアリング (irbank)", feature_engineering.run)

    if not args.skip_merge:
        step("特徴量マージ (irbank × 株価)", merge_features.run)

    if not args.skip_train:
        step("モデルトレーニング (LightGBM)", train_model.run)

    if not args.skip_backtest:
        step("バックテスト", backtest.run)

    if not args.skip_signals:
        step("シグナル生成", generate_signals.run)

    print("\n" + "="*60)
    print("  パイプライン完了!")
    print("="*60)
    print("\n出力ファイル:")
    for fname in ["features.csv", "model_lgbm.pkl", "feature_importance.csv",
                  "backtest_result.csv", "backtest_summary.csv", "signals.csv"]:
        path = f"output/{fname}"
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  ✓ {path} ({size:,} bytes)")
        else:
            print(f"  - {path} (未生成)")


if __name__ == "__main__":
    main()
