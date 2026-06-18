"""トヨタ1社の最新有報だけ取得して業績データを確認するテスト"""
import io, zipfile, requests, os

EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"
API_KEY = os.environ.get("EDINET_API_KEY", "")


def get(url, params, stream=False):
    if API_KEY:
        params["Subscription-Key"] = API_KEY
    r = requests.get(url, params=params, stream=stream, timeout=30)
    r.raise_for_status()
    return r


# Step1: 2024-06-28 前後でトヨタの有報を探す
print("=== Step1: 書類を検索 ===")
for date in ["2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28", "2024-06-29", "2024-06-30"]:
    r = get(f"{EDINET_BASE}/documents.json", {"date": date, "type": 2})
    results = r.json().get("results", [])
    toyota = [d for d in results if d.get("edinetCode") == "E02144" and d.get("docTypeCode") == "120"]
    if toyota:
        doc = toyota[0]
        print(f"発見: {date} / docID={doc['docID']} / {doc['filerName']} / {doc['periodEnd']}")
        break
else:
    print("見つからず。別の日付を試してください。")
    exit()

# Step2: ZIPダウンロード
print("\n=== Step2: ZIPダウンロード ===")
r = get(f"{EDINET_BASE}/documents/{doc['docID']}", {"type": 5}, stream=True)
zf = zipfile.ZipFile(io.BytesIO(r.content))
print("ZIPの中身:")
for name in zf.namelist():
    print(f"  {name}")

# Step3: 有報CSVを読む
import pandas as pd
target = next((n for n in zf.namelist() if "asr-001" in n and n.endswith(".csv")), None)
if not target:
    print("有報CSVが見つかりません")
    exit()

print(f"\n=== Step3: CSVを読む ({target}) ===")
for enc in ("utf-8-sig", "cp932", "utf-8"):
    try:
        df = pd.read_csv(io.BytesIO(zf.read(target)), encoding=enc)
        break
    except Exception:
        continue

print(f"行数: {len(df)}, カラム: {df.columns.tolist()[:5]}")
print(df.head(3).to_string())

# Step4: 主要財務項目を抽出
print("\n=== Step4: 主要財務項目 ===")
id_col = df.columns[0]
val_col = next((c for c in df.columns if "値" in c or c.lower() == "value"), df.columns[-1])

keywords = ["NetSales", "OperatingIncome", "ProfitLoss", "TotalAssets",
            "NetAssets", "CashFlow", "売上", "営業利益", "純資産", "総資産"]

for kw in keywords:
    rows = df[df[id_col].astype(str).str.contains(kw, case=False, na=False)]
    if not rows.empty:
        print(f"\n[{kw}]")
        print(rows[[id_col, val_col]].head(3).to_string(index=False))
