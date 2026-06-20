"""
Google Driveからデータをダウンロードしてoutputディレクトリに保存する
"""

import os
import sys
import requests

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def download_gdrive_file(file_id: str, dest_path: str):
    """通常のGoogle DriveファイルをDL（大容量対応）"""
    import gdown
    url = f"https://drive.google.com/uc?id={file_id}"
    gdown.download(url, dest_path, quiet=False)
    size_mb = os.path.getsize(dest_path) / 1024 / 1024
    print(f"  保存: {dest_path} ({size_mb:.1f} MB)")


def download_gsheet(sheet_id: str, dest_path: str):
    """Google SheetsファイルをxlsxとしてエクスポートDL"""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()
    total = 0
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
    size_mb = total / 1024 / 1024
    if size_mb < 0.01:
        raise RuntimeError(f"ダウンロードサイズが小さすぎます ({total} bytes) — 共有設定を確認してください")
    print(f"  保存: {dest_path} ({size_mb:.1f} MB)")


def run():
    price_file_id = os.environ.get("GDRIVE_PRICE_FILE_ID", "1tq_8ZLijqy5fFQNzT8h4K-aApvyl15-U")
    irbank_sheet_id = os.environ.get("GDRIVE_IRBANK_FILE_ID", "1-zRrPQvmxA8uKQstj600n4kzSlf-MQ7_")

    tasks = [
        (price_file_id,   f"{OUTPUT_DIR}/price_clean_valuation.csv", "株価・バリュエーションデータ", "drive"),
        (irbank_sheet_id, f"{OUTPUT_DIR}/irbank_pl.xlsx",            "IRbank PLデータ (Sheets)",    "sheets"),
    ]

    for file_id, dest, desc, kind in tasks:
        if not file_id:
            print(f"  [skip] file_id未設定: {desc}")
            continue
        if os.path.exists(dest):
            size_mb = os.path.getsize(dest) / 1024 / 1024
            print(f"  [cache] {dest} ({size_mb:.1f} MB) — スキップ")
            continue
        print(f"  ダウンロード中: {desc} ...")
        try:
            if kind == "sheets":
                download_gsheet(file_id, dest)
            else:
                download_gdrive_file(file_id, dest)
        except Exception as e:
            print(f"  [error] {desc}: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    print("=== Google Drive データダウンロード ===")
    run()
    print("完了")
