"""
業績データの特徴量エンジニアリング

入力:  output/gyoseki_price_完全版.csv
出力:  output/features.csv
"""

import re
import gc
import unicodedata
import numpy as np
import pandas as pd

INPUT_PATH  = "output/irbank_pl.xlsx"
OUTPUT_PATH = "output/irbank_features.csv"


# ── ロード ──────────────────────────────────────────────────────────────
def load_csv(path: str, chunksize: int = 50_000) -> pd.DataFrame:
    for enc in ["utf-8-sig", "cp932", "utf-8"]:
        try:
            chunks = []
            for chunk in pd.read_csv(path, encoding=enc, dtype=str, chunksize=chunksize):
                chunk.columns = [
                    unicodedata.normalize("NFKC", c).replace(" ", "").replace("　", "").strip()
                    for c in chunk.columns
                ]
                chunks.append(chunk)
            df = pd.concat(chunks, ignore_index=True)
            del chunks
            gc.collect()
            print(f"  読み込み完了: {enc} / {len(df):,} 行 × {len(df.columns)} 列")
            return df
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"  {enc} 失敗: {e}")
    raise RuntimeError(f"読み込み失敗: {path}")


# ── 前処理 ───────────────────────────────────────────────────────────────
def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates()
    key_cols = ["コード", "年度", "区分", "提出日"]
    if all(c in df.columns for c in key_cols):
        df = df.sort_values(key_cols).drop_duplicates(subset=key_cols, keep="last")

    df = df.rename(columns={"T_EPS_g": "EPS", "T_SPS_g": "SPS", "T_発行済株式数_推定": "株式数_推定"})

    # 列が存在しない場合はNaNで初期化
    for _c in ["EPS", "SPS", "株式数_推定"]:
        if _c not in df.columns:
            df[_c] = np.nan

    num_cols = ["売上高", "営業利益", "経常利益", "当期純利益", "EPS", "SPS", "株式数_推定"]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False), errors="coerce"
            )

    df["提出日"] = pd.to_datetime(df["提出日"], errors="coerce")
    df["年度_num"] = df["年度"].str.extract(r"(\d{4})").astype(float)
    df["区分"] = df["区分"].apply(
        lambda x: unicodedata.normalize("NFKC", str(x)).strip() if pd.notna(x) else x
    )

    def extract_quarter(s):
        s = str(s)
        if re.search(r"1Q|第1四半期|Q1", s): return "1Q"
        if re.search(r"2Q|第2四半期|Q2", s): return "2Q"
        if re.search(r"3Q|第3四半期|Q3", s): return "3Q"
        if re.search(r"通期|年間|FY", s):    return "通期"
        return np.nan

    df["_四半期"] = df["区分"].apply(extract_quarter)
    return df.sort_values(["コード", "年度_num", "提出日"]).reset_index(drop=True)


# ── 基本指標 ──────────────────────────────────────────────────────────────
def calc_base_metrics(df: pd.DataFrame) -> pd.DataFrame:
    rev = df["売上高"].replace(0, np.nan)
    df["営業利益率"]   = np.where(rev.notna(), df["営業利益"] / rev, np.nan)
    df["コスト率"]     = np.where(rev.notna(), (df["売上高"] - df["営業利益"]) / rev, np.nan)
    df["営業外寄与"]   = np.where(rev.notna(), (df["経常利益"] - df["営業利益"]) / rev, np.nan)
    df["最終調整寄与"] = np.where(rev.notna(), (df["当期純利益"] - df["経常利益"]) / rev, np.nan)
    df["純利益率"]     = np.where(rev.notna(), df["当期純利益"] / rev, np.nan)

    # 株式数推定がある場合のみ計算（列が存在しない場合はスキップ）
    if "株式数_推定" in df.columns:
        valid_shares = df["株式数_推定"].notna() & (df["株式数_推定"] != 0)
        df["一株営業利益"] = np.where(valid_shares, df["営業利益"] * 1e6 / df["株式数_推定"], np.nan)
        is_actual = df["区分"].str.contains("実績", na=False)
        df["EPS_実績"] = np.where(is_actual & valid_shares, df["当期純利益"] * 1e6 / df["株式数_推定"], np.nan)
        df["SPS_実績"] = np.where(is_actual & valid_shares, df["売上高"]     * 1e6 / df["株式数_推定"], np.nan)
    else:
        df["一株営業利益"] = np.nan
        df["EPS_実績"]    = np.nan
        df["SPS_実績"]    = np.nan
    return df


# ── ガイダンス変化率 ──────────────────────────────────────────────────────
RATE_COLS = ["売上高", "営業利益", "経常利益", "当期純利益", "EPS", "SPS", "一株営業利益", "営業利益率", "コスト率"]
DIFF_COLS = ["営業外寄与", "最終調整寄与"]
QUARTERS  = ["通期", "2Q"]


def calc_guidance_change(df: pd.DataFrame) -> pd.DataFrame:
    for q in QUARTERS:
        for col in RATE_COLS:
            df[f"{col}_{q}_ガイダンス変化率"] = np.nan
            df[f"{col}_{q}_k"] = np.nan
        for col in DIFF_COLS:
            df[f"{col}_{q}_ガイダンス差分"] = np.nan

    for code, sub in df.groupby("コード"):
        sub = sub.sort_values("提出日")
        for idx in sub.index:
            row = sub.loc[idx]
            if not ("予想" in str(row["区分"]) or "修正" in str(row["区分"])):
                continue
            q = row["_四半期"]
            if q not in QUARTERS:
                continue

            if "予想" in str(row["区分"]):
                prev = sub[
                    (sub["_四半期"] == q) &
                    (~sub["区分"].str.contains("予想|修正", na=False)) &
                    (sub["年度_num"] == row["年度_num"] - 1)
                ]
                if prev.empty:
                    continue
                prev_row = prev.iloc[-1]

                for col in RATE_COLS:
                    base = prev_row["EPS_実績"] if col == "EPS" else (prev_row["SPS_実績"] if col == "SPS" else prev_row[col])
                    cur  = row[col]
                    if pd.notna(base) and pd.notna(cur) and base != 0:
                        df.at[idx, f"{col}_{q}_ガイダンス変化率"] = (cur - base) / base
                    if col in ("EPS", "SPS") and pd.notna(base) and pd.notna(cur):
                        k = (1 if cur >= base else 2) if base > 0 else (3 if cur >= base else 4)
                        df.at[idx, f"{col}_{q}_k"] = k

                for col in DIFF_COLS:
                    if pd.notna(prev_row[col]) and pd.notna(row[col]):
                        df.at[idx, f"{col}_{q}_ガイダンス差分"] = row[col] - prev_row[col]
            else:
                prev = sub[
                    (sub["_四半期"] == q) &
                    (sub["年度_num"] == row["年度_num"]) &
                    (sub["提出日"] < row["提出日"]) &
                    (sub["区分"].str.contains("予想|修正", na=False))
                ]
                if prev.empty:
                    continue
                prev_row = prev.iloc[-1]
                for col in RATE_COLS:
                    if pd.notna(prev_row[col]) and pd.notna(row[col]) and prev_row[col] != 0:
                        df.at[idx, f"{col}_{q}_ガイダンス変化率"] = (row[col] - prev_row[col]) / prev_row[col]
                for col in DIFF_COLS:
                    if pd.notna(prev_row[col]) and pd.notna(row[col]):
                        df.at[idx, f"{col}_{q}_ガイダンス差分"] = row[col] - prev_row[col]

    df = df.drop(columns=[c for c in df.columns if c.endswith("_k") and "EPS" not in c and "SPS" not in c])
    return df


# ── 修正回数 ──────────────────────────────────────────────────────────────
def calc_revision_count(df: pd.DataFrame) -> pd.DataFrame:
    df["修正回数"] = 0
    for code, sub in df.groupby("コード"):
        sub = sub.sort_values("提出日")
        counter: dict = {}
        for idx in sub.index:
            row = sub.loc[idx]
            q = row["_四半期"]
            if q not in QUARTERS:
                continue
            key = (row["年度_num"], q)
            if "修正" in str(row["区分"]):
                counter[key] = counter.get(key, 0) + 1
                df.at[idx, "修正回数"] = counter[key]
            elif "予想" in str(row["区分"]):
                counter[key] = 0

    # 実績行にも修正回数を付与
    gk = df[df["区分"].str.contains("予想|修正", na=False)][["コード", "年度_num", "提出日", "修正回数"]].copy()
    gk = gk.groupby(["コード", "年度_num", "提出日"], as_index=False)["修正回数"].max()
    gk = gk.rename(columns={"修正回数": "_同日修正回数"})
    df = df.merge(gk, on=["コード", "年度_num", "提出日"], how="left")
    mask = df["区分"].str.contains("実績", na=False)
    df.loc[mask, "修正回数"] = df.loc[mask, "_同日修正回数"]
    df.loc[mask & df["修正回数"].isna(), "修正回数"] = 0
    return df.drop(columns=["_同日修正回数"])


# ── 前年乖離 ──────────────────────────────────────────────────────────────
def calc_yoy_deviation(df: pd.DataFrame) -> pd.DataFrame:
    for code, sub in df.groupby("コード"):
        sub = sub.sort_values("提出日")
        for idx in sub.index:
            row = sub.loc[idx]
            if not ("予想" in str(row["区分"]) or "修正" in str(row["区分"])):
                continue
            q = row["_四半期"]
            if q not in QUARTERS:
                continue

            prev_sub = sub[(sub["年度_num"] == row["年度_num"] - 1) & (sub["_四半期"] == q)].sort_values("提出日")
            if prev_sub.empty:
                continue

            prev_actual = prev_sub[~prev_sub["区分"].str.contains("予想|修正", na=False)]
            if prev_actual.empty:
                continue
            prev_actual_row = prev_actual.iloc[-1]

            if "予想" in str(row["区分"]):
                prev_f = prev_sub[prev_sub["区分"].str.contains("予想", na=False)]
                if prev_f.empty:
                    continue
                target_row = prev_f.iloc[0]
            else:
                prev_r = prev_sub[prev_sub["区分"].str.contains("修正", na=False)]
                if prev_r.empty:
                    continue
                n = int(row["修正回数"]) if pd.notna(row["修正回数"]) and row["修正回数"] > 0 else 1
                target_row = prev_r.iloc[n - 1] if len(prev_r) >= n else prev_r.iloc[-1]

            for col in RATE_COLS:
                base, actual = target_row[col], prev_actual_row[col]
                if pd.notna(base) and pd.notna(actual) and base != 0:
                    df.at[idx, f"{col}_ガイダンス実績乖離率_前年"] = (actual - base) / base
            for col in DIFF_COLS:
                base, actual = target_row[col], prev_actual_row[col]
                if pd.notna(base) and pd.notna(actual):
                    df.at[idx, f"{col}_ガイダンス実績乖離差分_前年"] = actual - base
    return df


# ── 実績ベース指標 ────────────────────────────────────────────────────────
def calc_actual_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df_actual = df[~df["区分"].str.contains("予想|修正", na=False)].copy()
    df_actual = df_actual.sort_values(["コード", "提出日"])

    cols = ["売上高", "営業利益", "経常利益", "当期純利益"]
    for col in cols:
        df_actual[f"{col}_単期"] = df_actual.groupby("コード")[col].diff()
    mask_1q = df_actual["_四半期"] == "1Q"
    df_actual.loc[mask_1q, [f"{col}_単期" for col in cols]] = df_actual.loc[mask_1q, cols].values

    safe = df_actual["売上高_単期"].replace(0, np.nan)
    df_actual["営業利益率_単期"]   = df_actual["営業利益_単期"] / safe
    df_actual["営業外寄与_単期"]   = (df_actual["経常利益_単期"] - df_actual["営業利益_単期"]) / safe
    df_actual["最終調整寄与_単期"] = (df_actual["当期純利益_単期"] - df_actual["経常利益_単期"]) / safe
    df_actual["コスト率_単期"]     = 1 - df_actual["営業利益率_単期"]

    # YoY
    yoy_key = ["コード", "年度_num", "_四半期"]
    yoy_val = ["売上高", "営業利益率", "営業外寄与", "最終調整寄与", "コスト率",
               "売上高_単期", "営業利益率_単期", "営業外寄与_単期", "最終調整寄与_単期", "コスト率_単期"]

    base = df_actual[yoy_key + yoy_val].copy()
    base = base.sort_values("年度_num").drop_duplicates(subset=yoy_key, keep="last")
    base = base.rename(columns={c: f"_p_{c}" for c in yoy_val})
    base["年度_num"] = base["年度_num"] + 1
    df_actual = df_actual.merge(base, on=yoy_key, how="left")

    df_actual["売上変化率_YoY"]     = df_actual["売上高"] / df_actual["_p_売上高"] - 1
    df_actual["営業利益率_YoY"]     = df_actual["営業利益率"] / df_actual["_p_営業利益率"] - 1
    df_actual["営業外要因_YoY"]     = df_actual["営業外寄与"] - df_actual["_p_営業外寄与"]
    df_actual["純利益率_YoY"]       = df_actual["最終調整寄与"] - df_actual["_p_最終調整寄与"]
    df_actual["コスト率_YoY"]       = df_actual["コスト率"] - df_actual["_p_コスト率"]
    df_actual["売上変化率_単期YoY"] = df_actual["売上高_単期"] / df_actual["_p_売上高_単期"] - 1
    df_actual["営業利益率_単期YoY"] = df_actual["営業利益率_単期"] / df_actual["_p_営業利益率_単期"] - 1
    df_actual["営業外要因_単期YoY"] = df_actual["営業外寄与_単期"] - df_actual["_p_営業外寄与_単期"]
    df_actual["純利益率_単期YoY"]   = df_actual["最終調整寄与_単期"] - df_actual["_p_最終調整寄与_単期"]
    df_actual["コスト率_単期YoY"]   = df_actual["コスト率_単期"] - df_actual["_p_コスト率_単期"]
    df_actual = df_actual.drop(columns=[c for c in df_actual.columns if c.startswith("_p_")])

    cols_yoy = [
        "売上変化率_YoY", "営業利益率_YoY", "営業外要因_YoY", "純利益率_YoY", "コスト率_YoY",
        "売上変化率_単期YoY", "営業利益率_単期YoY", "営業外要因_単期YoY", "純利益率_単期YoY", "コスト率_単期YoY",
    ]
    for col in cols_yoy:
        df_actual[f"{col}_３年平均"] = df_actual.groupby(["コード", "_四半期"])[col].transform(
            lambda x: x.rolling(3, min_periods=2).mean()
        )
        df_actual[f"{col}_３年リスク"] = df_actual.groupby(["コード", "_四半期"])[col].transform(
            lambda x: x.rolling(3, min_periods=2).std()
        )
        df_actual[f"{col}_12Q平均"] = df_actual.groupby("コード")[col].transform(
            lambda x: x.rolling(12, min_periods=4).mean()
        )
        df_actual[f"{col}_12Qリスク"] = df_actual.groupby("コード")[col].transform(
            lambda x: x.rolling(12, min_periods=4).std()
        )

    # 単期 赤転/黒転
    term_cols = ["売上高_単期", "営業利益_単期", "経常利益_単期", "当期純利益_単期"]
    base2 = df_actual[yoy_key + term_cols].copy()
    base2 = base2.drop_duplicates(subset=yoy_key, keep="last")
    base2 = base2.rename(columns={c: f"_p_{c}" for c in term_cols})
    base2["年度_num"] = base2["年度_num"] + 1
    df_actual = df_actual.merge(base2, on=yoy_key, how="left")

    for col in term_cols:
        prev = df_actual[f"_p_{col}"]
        cur  = df_actual[col]
        df_actual[f"{col}_赤転"]    = ((prev > 0) & (cur < 0)).astype(int)
        df_actual[f"{col}_黒転"]    = ((prev < 0) & (cur >= 0)).astype(int)
        df_actual[f"{col}_YoY_abs"] = np.where(
            prev.notna() & (prev != 0), (cur - prev) / prev.abs(), np.nan
        )
        df_actual[f"{col}_YoY_abs"] = df_actual[f"{col}_YoY_abs"].clip(-5, 5)
    df_actual = df_actual.drop(columns=[c for c in df_actual.columns if c.startswith("_p_")])

    # 実績累計・単期 赤転/黒転フラグ (ループ版)
    flag_cols = ["営業利益", "当期純利益"]
    for col in flag_cols:
        for t in ["累計", "単期"]:
            df_actual[f"{col}_実績_{t}_赤転"] = np.nan
            df_actual[f"{col}_実績_{t}_黒転"] = np.nan

    for code, sub in df_actual.groupby("コード"):
        sub = sub.sort_values("提出日")
        for idx in sub.index:
            row = sub.loc[idx]
            q = row["_四半期"]
            if pd.isna(q):
                continue
            prev = sub[(sub["_四半期"] == q) & (sub["年度_num"] == row["年度_num"] - 1)]
            if prev.empty:
                continue
            prev_row = prev.iloc[-1]
            for col in flag_cols:
                bc, cc = prev_row[col], row[col]
                if pd.notna(bc) and pd.notna(cc):
                    df_actual.at[idx, f"{col}_実績_累計_赤転"] = int(bc > 0 and cc < 0)
                    df_actual.at[idx, f"{col}_実績_累計_黒転"] = int(bc < 0 and cc >= 0)
                tc = f"{col}_単期"
                bt = prev_row.get(tc, np.nan); ct = row.get(tc, np.nan)
                if pd.notna(bt) and pd.notna(ct):
                    df_actual.at[idx, f"{col}_実績_単期_赤転"] = int(bt > 0 and ct < 0)
                    df_actual.at[idx, f"{col}_実績_単期_黒転"] = int(bt < 0 and ct >= 0)

    return df, df_actual


# ── 達成率 ───────────────────────────────────────────────────────────────
def _achievement(actual, guide):
    if pd.isna(actual) or pd.isna(guide) or guide == 0:
        return np.nan, np.nan
    if guide > 0 and actual >= 0:
        return actual / guide, (1 if actual >= guide else 2)
    if guide < 0 and actual < 0:
        return -(actual / guide), (3 if actual >= guide else 4)
    if guide < 0 and actual >= 0:
        return (actual + abs(guide)) / abs(guide), 1
    return -(abs(actual) / guide + 1), 4


def calc_achievement(df: pd.DataFrame) -> pd.DataFrame:
    actual_cols = ["売上高", "営業利益", "経常利益", "当期純利益"]
    for col in actual_cols:
        for q in QUARTERS:
            df[f"{col}_達成率_累計_{q}G"] = np.nan
            df[f"{col}_達成率_単体_{q}G"] = np.nan
            df[f"{col}_達成率フラグ_{q}G"] = np.nan

    df = df.sort_values(["コード", "年度_num", "提出日"])

    for code, grp_code in df.groupby("コード"):
        for year, sub in grp_code.groupby("年度_num"):
            sub = sub.sort_values("提出日").reset_index()
            sub = sub.rename(columns={"index": "_orig"})
            orig = sub["_orig"]

            for pos, row in sub.iterrows():
                if "実績" not in str(row["区分"]):
                    continue
                for q in QUARTERS:
                    guidance = sub[
                        (sub["_四半期"] == q) &
                        (sub["提出日"] <= row["提出日"]) &
                        (sub["区分"].str.contains("予想|修正", na=False))
                    ]
                    if guidance.empty:
                        continue
                    latest = guidance.iloc[-1]
                    for col in actual_cols:
                        rate, flag = _achievement(row[col], latest[col])
                        df.at[orig.iloc[pos], f"{col}_達成率_累計_{q}G"] = rate
                        df.at[orig.iloc[pos], f"{col}_達成率フラグ_{q}G"] = flag
                        rate_t, _ = _achievement(row.get(f"{col}_単期", np.nan), latest[col])
                        df.at[orig.iloc[pos], f"{col}_達成率_単体_{q}G"] = rate_t

    # 前年達成率
    ach_cols = [c for c in df.columns if "達成率" in c]
    base = df[df["区分"].str.contains("実績", na=False)][["コード", "年度_num", "_四半期"] + ach_cols].copy()
    base = base.drop_duplicates(subset=["コード", "年度_num", "_四半期"], keep="last")
    base = base.rename(columns={c: f"{c}_前年" for c in ach_cols})
    base["年度_num"] = base["年度_num"] + 1
    df = df.merge(base, on=["コード", "年度_num", "_四半期"], how="left")
    return df


# ── ガイダンス符号変化フラグ ──────────────────────────────────────────────
def calc_guidance_sign_flags(df: pd.DataFrame) -> pd.DataFrame:
    flag_cols = ["営業利益", "当期純利益"]
    for col in flag_cols:
        for q in QUARTERS:
            df[f"{col}_ガイダンス_{q}_赤転"] = np.nan
            df[f"{col}_ガイダンス_{q}_黒転"] = np.nan

    for code, sub in df.groupby("コード"):
        sub = sub.sort_values("提出日")
        for col in flag_cols:
            for q in QUARTERS:
                gsub = sub[sub["区分"].str.contains("予想|修正", na=False) & (sub["_四半期"] == q)].sort_values("提出日")
                for idx in gsub.index:
                    row = gsub.loc[idx]
                    cur_val = row[col]
                    prev_year = row["年度_num"] - 1
                    prev_c = gsub[gsub["年度_num"] == prev_year].sort_values("提出日")
                    if prev_c.empty:
                        continue
                    if "予想" in str(row["区分"]):
                        pf = prev_c[prev_c["区分"].str.contains("予想", na=False)]
                        if pf.empty:
                            continue
                        prev_val = pf.iloc[0][col]
                    else:
                        pr = prev_c[prev_c["区分"].str.contains("修正", na=False)]
                        if pr.empty:
                            continue
                        n = int(row["修正回数"]) if pd.notna(row["修正回数"]) and row["修正回数"] > 0 else 1
                        prev_val = pr.iloc[n - 1][col] if len(pr) >= n else pr.iloc[-1][col]
                    if pd.isna(cur_val) or pd.isna(prev_val):
                        continue
                    df.at[idx, f"{col}_ガイダンス_{q}_黒転"] = int(prev_val < 0 and cur_val >= 0)
                    df.at[idx, f"{col}_ガイダンス_{q}_赤転"] = int(prev_val >= 0 and cur_val < 0)
    return df


# ── 最終マージ & 出力 ────────────────────────────────────────────────────
def assemble(df: pd.DataFrame, df_actual: pd.DataFrame) -> pd.DataFrame:
    add_cols = [c for c in df_actual.columns if any(x in c for x in [
        "YoY", "平均", "リスク", "_単期", "_実績_累計_赤転", "_実績_累計_黒転", "_実績_単期_赤転", "_実績_単期_黒転",
    ])]
    add_cols = list(dict.fromkeys(add_cols))
    merge_key = ["コード", "年度_num", "_四半期", "提出日"]

    df = df.drop(columns=[c for c in add_cols if c in df.columns and c not in merge_key], errors="ignore")
    df = df.merge(df_actual[merge_key + add_cols], on=merge_key, how="left")

    df_actual_only = df[
        (~df["区分"].str.contains("予想|修正", na=False)) &
        (df["_四半期"].isin(["1Q", "2Q", "3Q", "通期"]))
    ].copy()
    df_actual_only = df_actual_only.drop(
        columns=[c for c in df_actual_only.columns if "ガイダンス" in c], errors="ignore"
    )

    df_guidance = df[df["区分"].str.contains("予想|修正", na=False)].copy()

    guidance_rate_cols = [c for c in df_guidance.columns if "_ガイダンス変化率" in c or "_ガイダンス差分" in c or c.endswith("_k")]
    guidance_rikai_cols = [c for c in df_guidance.columns if "ガイダンス実績乖離" in c]

    df_rate = df_guidance[["コード", "年度_num", "提出日"] + guidance_rate_cols].copy()
    df_rate_minus = df_rate.copy()
    df_rate_minus["年度_num"] = df_rate_minus["年度_num"] - 1
    df_rate_all = pd.concat([df_rate, df_rate_minus]).drop_duplicates(
        subset=["コード", "年度_num", "提出日"], keep="last"
    )

    df_actual_only = df_actual_only.merge(df_rate_all, on=["コード", "年度_num", "提出日"], how="left")

    if guidance_rikai_cols:
        df_rikai = df_guidance[["コード", "年度_num", "修正回数"] + guidance_rikai_cols].copy()
        df_rikai["年度_num"] = df_rikai["年度_num"] + 1
        # 修正回数に関わらず前年の最新修正（最大修正回数）を使う
        df_rikai = df_rikai.sort_values("修正回数").drop_duplicates(subset=["コード", "年度_num"], keep="last")
        df_rikai = df_rikai.drop(columns=["修正回数"])
        df_actual_only = df_actual_only.merge(df_rikai, on=["コード", "年度_num"], how="left")

    df_actual_only = df_actual_only.drop(columns=[c for c in df_actual_only.columns if c.endswith("_k")], errors="ignore")

    price_cols     = [c for c in df_actual_only.columns if any(x in c for x in ["pre_", "post_", "T_"])]
    non_price_cols = [c for c in df_actual_only.columns if not any(x in c for x in ["pre_", "post_", "T_"])]
    return df_actual_only[non_price_cols + price_cols]


# ── エントリポイント ──────────────────────────────────────────────────────
def run(input_path: str = INPUT_PATH, output_path: str = OUTPUT_PATH):
    import os
    if not os.path.exists(input_path):
        print(f"  [error] 入力ファイルが見つかりません: {input_path}")
        return

    print(f"データ読み込み: {input_path}")
    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(input_path, dtype=str)
        df.columns = [
            __import__("unicodedata").normalize("NFKC", c).replace(" ", "").replace("　", "").strip()
            for c in df.columns
        ]
        # 証券コード → コード に統一
        if "証券コード" in df.columns and "コード" not in df.columns:
            df = df.rename(columns={"証券コード": "コード"})
        # 余分な空列を除去
        df = df[[c for c in df.columns if not c.startswith("Unnamed")]]
        print(f"  読み込み完了: {len(df):,} 行 × {len(df.columns)} 列")
        print(f"  列名: {list(df.columns)}")
    else:
        df = load_csv(input_path)

    print("前処理中...")
    df = preprocess(df)
    df = calc_base_metrics(df)

    print("ガイダンス変化率計算中...")
    df = calc_guidance_change(df)

    print("修正回数計算中...")
    df = calc_revision_count(df)

    print("前年乖離計算中...")
    df = calc_yoy_deviation(df)

    print("実績指標計算中...")
    df, df_actual = calc_actual_metrics(df)

    print("達成率計算中...")
    df = calc_achievement(df)

    print("ガイダンス符号変化フラグ計算中...")
    df = calc_guidance_sign_flags(df)

    print("最終マージ中...")
    df_final = assemble(df, df_actual)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    df_final.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n保存完了: {output_path}")
    print(f"  {len(df_final):,} 行 × {len(df_final.columns)} 列")
    return df_final


if __name__ == "__main__":
    run()
