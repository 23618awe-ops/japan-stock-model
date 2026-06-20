import pandas as pd

df = pd.read_csv(
    "output/features.csv",
    encoding="utf-8-sig",
    usecols=["年度_num", "提出日", "_四半期"],
    low_memory=False,
)
df["提出日"] = pd.to_datetime(df["提出日"], errors="coerce")
df["提出年"] = df["提出日"].dt.year

print("=== 年度_num ごとの提出日の年の分布（通期のみ） ===")
通期 = df[df["_四半期"] == "通期"]
cross = pd.crosstab(通期["年度_num"], 通期["提出年"])
print(cross.tail(10).to_string())

print()
print("=== train/val/test の提出日範囲 ===")
for label, mask in [
    ("train(≤2022)", df["年度_num"] <= 2022),
    ("val(2023)", df["年度_num"] == 2023),
    ("test(≥2024)", df["年度_num"] >= 2024),
]:
    sub = df[mask]["提出日"].dropna()
    if len(sub) > 0:
        print(f"{label}: {sub.min().date()} 〜 {sub.max().date()} ({len(sub):,}件)")
    else:
        print(f"{label}: データなし")
