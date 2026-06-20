"""
データファイルの中身を確認するスクリプト
ローカルで実行して結果を共有してください
"""

import pandas as pd
import os

# ここにファイルのパスを入れてください
PRICE_CSV   = "price_clean_valuation.csv"   # Google DriveからDLしたCSV
IRBANK_XLSX = "irbank_pl_統合.xlsx"          # Google DriveからDLしたExcel


def inspect(path):
    print(f"\n{'='*60}")
    print(f"ファイル: {path}")
    if not os.path.exists(path):
        print("  ファイルが見つかりません")
        return

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".csv":
            for enc in ["utf-8-sig", "cp932", "utf-8"]:
                try:
                    df = pd.read_csv(path, encoding=enc, nrows=3, dtype=str)
                    break
                except UnicodeDecodeError:
                    continue
        else:
            df = pd.read_excel(path, nrows=3, dtype=str)

        print(f"  行数(概算): {sum(1 for _ in open(path, errors='ignore')) if ext=='.csv' else '?'}")
        print(f"  列数: {len(df.columns)}")
        print(f"\n  列名一覧:")
        for i, col in enumerate(df.columns):
            print(f"    [{i:03d}] {col}")
        print(f"\n  先頭3行:")
        print(df.to_string(index=False))
    except Exception as e:
        print(f"  読み込みエラー: {e}")


inspect(PRICE_CSV)
inspect(IRBANK_XLSX)
