"""
Google Driveからデータをダウンロードしてoutputディレクトリに保存する
"""

import os
import sys
import requests

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

FILES = {
    os.environ.get("GDRIVE_PRICE_FILE_ID", "1tq_8ZLijqy5fFQNzT8h4K-aApvyl15-U"): (
        f"{OUTPUT_DIR}/price_clean_valuation.csv",
        "株価・バリュエーションデータ",
    ),
    os.environ.get("GDRIVE_IRBANK_FILE_ID", "1-zRrPQvmxA8uKQstj600n4kzSlf-MQ7_"): (
        f"{OUTPUT_DIR}/irbank_pl.xlsx",
        "IRbank 業績データ",
    ),
}


def download_from_gdrive(file_id: str, dest_path: str):
    url = "https://drive.usercontent.google.com/download"
    session = requests.Session()
    r = session.get(url, params={"id": file_id, "confirm": "t", "export": "download"}, stream=True, timeout=300)
    r.raise_for_status()
    total = 0
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
    print(f"  保存: {dest_path} ({total / 1024 / 1024:.1f} MB)")


def run():
    for file_id, (dest, desc) in FILES.items():
        if not file_id:
            print(f"  [skip] file_id未設定: {desc}")
            continue
        if os.path.exists(dest):
            size_mb = os.path.getsize(dest) / 1024 / 1024
            print(f"  [cache] {dest} ({size_mb:.1f} MB) — スキップ")
            continue
        print(f"  ダウンロード中: {desc} ...")
        try:
            download_from_gdrive(file_id, dest)
        except Exception as e:
            print(f"  [error] {desc}: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    print("=== Google Drive データダウンロード ===")
    run()
    print("完了")
