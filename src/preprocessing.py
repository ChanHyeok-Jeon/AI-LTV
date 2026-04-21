"""
Feature Engineering — 유저별 7일치 로그 → 모델 입력 피처

관찰 기간: day 0~75 (76~90일은 이탈 판정 구간)
피처 기준일: day 69~75 (마지막 7일)
"""

import pandas as pd
import numpy as np
import os


FEATURE_WINDOW = 7    # 피처 집계 기간 (일)
OBS_END_DAY    = 76   # 관찰 종료일 (이후는 라벨 구간)
START_DATE     = pd.Timestamp("2025-01-01")


def load_raw(data_dir: str = "data/raw") -> dict[str, pd.DataFrame]:
    tables = ["session_logs", "action_logs", "player_status", "purchase_logs", "user_meta"]
    dfs = {}
    for t in tables:
        path = os.path.join(data_dir, f"{t}.csv")
        dfs[t] = pd.read_csv(path, parse_dates=True)
    return dfs


def _to_dt(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def build_features(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    각 유저에 대해 마지막 7일치 로그를 집계하여 피처를 생성합니다.
    Returns: user_id별 피처 DataFrame
    """
    sessions  = _to_dt(dfs["session_logs"].copy(),  ["login_dt", "logout_dt"])
    actions   = _to_dt(dfs["action_logs"].copy(),   ["event_dt"])
    status    = _to_dt(dfs["player_status"].copy(), ["snapshot_dt"])
    purchases = _to_dt(dfs["purchase_logs"].copy(), ["purchase_dt"])
    meta      = dfs["user_meta"].copy()

    window_start = START_DATE + pd.Timedelta(days=OBS_END_DAY - FEATURE_WINDOW)
    window_end   = START_DATE + pd.Timedelta(days=OBS_END_DAY)

    # ── 세션 피처 ─────────────────────────────────────
    sess_w = sessions[
        (sessions["login_dt"] >= window_start) &
        (sessions["login_dt"] <  window_end)
    ]

    sess_feat = sess_w.groupby("user_id").agg(
        session_count_7d    = ("session_id", "count"),
        avg_session_min_7d  = ("session_minutes", "mean"),
        total_session_min_7d= ("session_minutes", "sum"),
    ).reset_index()

    # 세션 추세: 후반 3일 평균 / 전반 4일 평균 (1보다 작으면 감소)
    mid = window_start + pd.Timedelta(days=4)
    sess_early = sess_w[sess_w["login_dt"] < mid].groupby("user_id")["session_minutes"].mean().rename("sess_early")
    sess_late  = sess_w[sess_w["login_dt"] >= mid].groupby("user_id")["session_minutes"].mean().rename("sess_late")
    sess_trend = (sess_late / (sess_early + 1e-9)).rename("session_trend").reset_index()
    sess_trend.columns = ["user_id", "session_trend"]

    # 마지막 접속 이후 경과일
    last_login = sessions.groupby("user_id")["login_dt"].max().reset_index()
    last_login["days_since_last_login"] = (window_end - last_login["login_dt"]).dt.days
    last_login = last_login[["user_id", "days_since_last_login"]]

    # ── 행동 피처 ─────────────────────────────────────
    act_w = actions[
        (actions["event_dt"] >= window_start) &
        (actions["event_dt"] <  window_end)
    ]

    enh_w = act_w[act_w["event_type"] == "enhancement"]
    enh_feat = enh_w.groupby("user_id").agg(
        enhancement_attempts_7d = ("event_result", "count"),
        enhancement_fails_7d    = ("event_result", lambda x: (x == "fail").sum()),
    ).reset_index()
    enh_feat["enhancement_fail_rate"] = (
        enh_feat["enhancement_fails_7d"] / enh_feat["enhancement_attempts_7d"].clip(lower=1)
    )

    quest_feat = act_w[act_w["event_type"] == "quest"].groupby("user_id").agg(
        quest_clear_7d = ("event_result", "count")
    ).reset_index()

    pvp_feat = act_w[act_w["event_type"] == "pvp"].groupby("user_id").agg(
        pvp_count_7d = ("event_result", "count")
    ).reset_index()

    # ── 성장 피처 ─────────────────────────────────────
    stat_w = status[
        (status["snapshot_dt"] >= window_start) &
        (status["snapshot_dt"] <  window_end)
    ]

    stat_feat = stat_w.groupby("user_id").agg(
        level_max   = ("level", "max"),
        level_min   = ("level", "min"),
        guild_yn    = ("guild_yn", "max"),
        days_played = ("days_played", "max"),
    ).reset_index()
    stat_feat["level_gain_7d"] = stat_feat["level_max"] - stat_feat["level_min"]

    # 구간 정체: 레벨이 전혀 오르지 않은 날 수
    level_by_day = stat_w.sort_values("snapshot_dt").groupby("user_id").apply(
        lambda df: (df["level"].diff() == 0).sum(), include_groups=False
    ).reset_index()
    level_by_day.columns = ["user_id", "stage_stagnation_days"]

    # ── 결제 피처 ─────────────────────────────────────
    pur_w = purchases[
        (purchases["purchase_dt"] >= window_start) &
        (purchases["purchase_dt"] <  window_end)
    ]

    pur_feat = pur_w.groupby("user_id").agg(
        purchase_count_7d  = ("amount_krw", "count"),
        purchase_amount_7d = ("amount_krw", "sum"),
    ).reset_index()

    last_purchase = purchases.groupby("user_id")["purchase_dt"].max().reset_index()
    last_purchase["last_purchase_days_ago"] = (window_end - last_purchase["purchase_dt"]).dt.days
    last_purchase = last_purchase[["user_id", "last_purchase_days_ago"]]

    # ── 전체 병합 ──────────────────────────────────────
    base = meta[["user_id", "churn_label"]].copy()

    for df in [
        sess_feat, sess_trend, last_login,
        enh_feat, quest_feat, pvp_feat,
        stat_feat, level_by_day,
        pur_feat, last_purchase,
    ]:
        base = base.merge(df, on="user_id", how="left")

    # 결측치 처리 (접속/행동 없는 유저 → 0)
    fill_zero = [
        "session_count_7d", "avg_session_min_7d", "total_session_min_7d",
        "enhancement_attempts_7d", "enhancement_fails_7d", "enhancement_fail_rate",
        "quest_clear_7d", "pvp_count_7d",
        "level_gain_7d", "stage_stagnation_days",
        "purchase_count_7d", "purchase_amount_7d",
    ]
    base[fill_zero] = base[fill_zero].fillna(0)

    # 세션 추세 미접속자 = 0 (감소로 간주)
    base["session_trend"] = base["session_trend"].fillna(0)

    # 마지막 접속/결제 경과일 미접속자 = 90 (최대값)
    base["days_since_last_login"]   = base["days_since_last_login"].fillna(90)
    base["last_purchase_days_ago"]  = base["last_purchase_days_ago"].fillna(90)

    # 길드, 레벨
    base["guild_yn"]    = base["guild_yn"].fillna(False).astype(int)
    base["level_max"]   = base["level_max"].fillna(1)
    base["days_played"] = base["days_played"].fillna(0)

    # 불필요 컬럼 제거
    base.drop(columns=["level_min", "enhancement_fails_7d"], inplace=True, errors="ignore")

    return base


FEATURE_COLS = [
    # 세션
    "session_count_7d", "avg_session_min_7d", "total_session_min_7d",
    "session_trend", "days_since_last_login",
    # 행동
    "enhancement_attempts_7d", "enhancement_fail_rate",
    "quest_clear_7d", "pvp_count_7d",
    # 성장
    "level_max", "level_gain_7d", "stage_stagnation_days",
    "guild_yn", "days_played",
    # 결제
    "purchase_count_7d", "purchase_amount_7d", "last_purchase_days_ago",
]


def get_xy(features: pd.DataFrame):
    X = features[FEATURE_COLS].values
    y = features["churn_label"].values
    return X, y


if __name__ == "__main__":
    dfs = load_raw("data/raw")
    features = build_features(dfs)

    out_path = "data/processed/features.csv"
    os.makedirs("data/processed", exist_ok=True)
    features.to_csv(out_path, index=False)

    print(f"피처 저장 완료: {out_path}  ({len(features):,}명)")
    print(f"\n이탈율: {features['churn_label'].mean():.1%}")
    print(f"\n피처 컬럼 ({len(FEATURE_COLS)}개):")
    print(features[FEATURE_COLS].describe().round(2))
