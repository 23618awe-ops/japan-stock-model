"""トヨタの業績データ取得デバッグスクリプト"""
import io, zipfile, requests, os, sys
import pandas as pd

EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"
API_KEY = os.environ.get("EDINET_API_KEY", "")

def get(url, params, stream=False):
    if API_KEY:
        params["Subscription-Key"] = API_KEY
    r = requests.get(url, params=params, stream=stream, timeout=30)
    r.raise_for_status()
    return r

def read_csv_robust(data: bytes) -> pd.DataFrame:
    """あらゆるエンコード・形式に対応してCSVを読む"""
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        for sep in (",", "\t"):
            try:
                df = pd.read_csv(
                    io.BytesIO(data),
                    encoding=enc,
                    sep=sep,
                    on_bad_lines="skip",
                    low_memory=False,
                )
                if len(df.columns) >= 2:
                    print(f"  読み込み成功: encoding={enc}, sep={'TAB' if sep == chr(9) else 'COMMA'}")
                    return df
            except Exception:
                continue
    # 最終手段: 生テキストを確認
    print("  全エンコード失敗。先頭バイトを確認:")
    print("  hex:", data[:100].hex())
    print("  raw:", data[:200])
    return pd.DataFrame()

# Step1: 書類検索
print("=== Step1: トヨタの有報を検索 ===")
doc = None
for date in ["2024-06-25","2024-06-26","2024-06-27","2024-06-28","2024-06-29","2024-06-30"]:
    r = get(f"{EDINET_BASE}/documents.json", {"date": date, "type": 2})
    results = r.json().get("results", [])
    found = [d for d in results if d.get("edinetCode") == "E02144" and d.get("docTypeCode") == "120"]
    if found:
        doc = found[0]
        print(f"発見: {date} / docID={doc['docID']} / {doc['filerName']} / {doc['periodEnd']}")
        break

if not doc:
    print("見つかりませんでした")
    sys.exit(1)

# Step2: ZIPダウンロード
print("\n=== Step2: ZIPダウンロード ===")
r = get(f"{EDINET_BASE}/documents/{doc['docID']}", {"type": 5}, stream=True)
raw = r.content
print(f"ZIPサイズ: {len(raw):,} bytes")

zf = zipfile.ZipFile(io.BytesIO(raw))
print("ZIPの中身:")
for name in zf.namelist():
    size = zf.getinfo(name).file_size
    print(f"  {name}  ({size:,} bytes)")

# Step3: 有報CSVを読む
print("\n=== Step3: CSVを読む ===")
target = next((n for n in zf.namelist() if "asr-001" in n and n.endswith(".csv")), None)
if not target:
    print("有報CSVなし")
    sys.exit(1)

raw_csv = zf.read(target)
print(f"CSVサイズ: {len(raw_csv):,} bytes")
df = read_csv_robust(raw_csv)

if df.empty:
    sys.exit(1)

print(f"行数: {len(df)}, カラム数: {len(df.columns)}")
print("カラム名:", df.columns.tolist()[:8])
print("\n先頭3行:")
print(df.head(3).to_string())

# Step4: 財務項目を抽出
print("\n=== Step4: 主要財務項目 ===")
id_col  = df.columns[0]
val_col = next((c for c in df.columns if "値" in str(c) or str(c).lower() in ("value","amount")), df.columns[-2])
print(f"要素ID列: '{id_col}', 値列: '{val_col}'")

keywords = {
    "売上高":   ["NetSales", "売上高", "RevenueFromContractWithCustomer"],
    "営業利益": ["OperatingIncome", "OperatingProfit", "営業利益"],
    "純利益":   ["ProfitLoss", "NetIncome", "当期純利益"],
    "総資産":   ["TotalAssets", "総資産"],
    "純資産":   ["NetAssets", "TotalNetAssets", "純資産"],
    "営業CF":   ["CashFlowFromOperatingActivities", "営業活動"],
}

found_any = False
for label, kws in keywords.items():
    for kw in kws:
        rows = df[df[id_col].astype(str).str.contains(kw, case=False, na=False)]
        rows = rows[pd.to_numeric(rows[val_col], errors="coerce").notna()]
        if not rows.empty:
            val = rows[val_col].iloc[0]
            print(f"  {label:8s}: {val:>20s}  ({rows[id_col].iloc[0]})")
            found_any = True
            break

if not found_any:
    print("財務項目が見つかりませんでした。全カラム名を表示:")
    print(df.columns.tolist())
    print("\nユニークな要素ID（先頭30件）:")
    print(df[id_col].dropna().unique()[:30].tolist())

print("\n=== 完了 ===")
