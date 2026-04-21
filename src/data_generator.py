"""
MMORPG 플레이 로그 합성 데이터 생성기

유저 타입별로 현실적인 이탈 패턴을 시뮬레이션합니다.
- 관찰 기간: 90일
- 이탈 라벨: 마지막 76~90일 구간에 접속 없으면 이탈(1)
"""

import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime, timedelta
import os

np.random.seed(42)

# ── 설정 ──────────────────────────────────────────────
N_USERS       = 5_000
SIM_DAYS      = 90       # 전체 관찰 기간
CHURN_WINDOW  = 14       # 마지막 N일 미접속 → 이탈
START_DATE    = datetime(2025, 1, 1)

# 유저 타입 비율 (합 = 1.0)
USER_TYPE_DIST = {
    "hardcore":             0.10,  # 매일 장시간 플레이, 낮은 이탈
    "casual":               0.30,  # 주 2~3회 플레이, 중간 이탈
    "whale":                0.05,  # 결제 많음, 낮은 이탈
    "churn_enhancement":    0.20,  # 강화 실패 → 이탈
    "churn_stagnation":     0.15,  # 구간 정체 → 이탈
    "churn_session_decline":0.12,  # 접속 시간 점진적 감소 → 이탈
    "churn_payment_dropout":0.08,  # 결제 중단 후 이탈
}

# 아이템 ID 풀
ITEM_POOL = [f"ITEM_{i:04d}" for i in range(1, 201)]
ZONE_POOL = [f"ZONE_{i:02d}" for i in range(1, 21)]


# ── 유저 타입별 행동 파라미터 ──────────────────────────
TYPE_PARAMS = {
    "hardcore": {
        "login_prob":        0.90,
        "session_min_mu":    150,
        "session_min_sigma": 50,
        "enh_attempts_mu":   6,
        "enh_fail_rate":     0.40,
        "quest_mu":          4,
        "purchase_prob":     0.05,
        "purchase_amt_mu":   5000,
        "churn_day":         None,
    },
    "casual": {
        "login_prob":        0.40,
        "session_min_mu":    55,
        "session_min_sigma": 25,
        "enh_attempts_mu":   3,
        "enh_fail_rate":     0.50,
        "quest_mu":          2,
        "purchase_prob":     0.02,
        "purchase_amt_mu":   3000,
        "churn_day":         None,
    },
    "whale": {
        "login_prob":        0.80,
        "session_min_mu":    110,
        "session_min_sigma": 35,
        "enh_attempts_mu":   8,
        "enh_fail_rate":     0.30,
        "quest_mu":          4,
        "purchase_prob":     0.28,
        "purchase_amt_mu":   50000,
        "churn_day":         None,
    },
    "churn_enhancement": {
        "login_prob":        0.65,
        "session_min_mu":    80,
        "session_min_sigma": 30,
        "enh_attempts_mu":   8,
        "enh_fail_rate":     0.75,  # 강화 실패율 높음
        "quest_mu":          2,
        "purchase_prob":     0.03,
        "purchase_amt_mu":   3000,
        "churn_day":         (40, 70),
    },
    "churn_stagnation": {
        "login_prob":        0.50,
        "session_min_mu":    65,
        "session_min_sigma": 25,
        "enh_attempts_mu":   2,
        "enh_fail_rate":     0.45,
        "quest_mu":          1,       # 퀘스트 거의 안 함
        "purchase_prob":     0.02,
        "purchase_amt_mu":   2000,
        "churn_day":         (30, 65),
    },
    "churn_session_decline": {
        "login_prob":        0.75,
        "session_min_mu":    95,
        "session_min_sigma": 30,
        "enh_attempts_mu":   4,
        "enh_fail_rate":     0.48,
        "quest_mu":          2,
        "purchase_prob":     0.02,
        "purchase_amt_mu":   2000,
        "churn_day":         (50, 80),
    },
    "churn_payment_dropout": {
        "login_prob":        0.55,
        "session_min_mu":    75,
        "session_min_sigma": 28,
        "enh_attempts_mu":   5,
        "enh_fail_rate":     0.52,
        "quest_mu":          2,
        "purchase_prob":     0.14,  # 초반엔 결제하다가 끊음
        "purchase_amt_mu":   10000,
        "churn_day":         (45, 75),
    },
}


def assign_user_types(n: int) -> list:
    types = list(USER_TYPE_DIST.keys())
    probs = list(USER_TYPE_DIST.values())
    return np.random.choice(types, size=n, p=probs).tolist()


def get_churn_day(user_type: str) -> int | None:
    """이탈 시작일 반환 (None이면 이탈 없음)"""
    params = TYPE_PARAMS[user_type]
    cd = params["churn_day"]
    if cd is None:
        return None
    return np.random.randint(cd[0], cd[1])


def simulate_user(user_id: str, user_type: str, churn_day: int | None):
    """
    단일 유저의 90일치 로그를 생성합니다.
    Returns: session_rows, action_rows, status_rows, purchase_rows
    """
    p = TYPE_PARAMS[user_type]
    session_rows  = []
    action_rows   = []
    status_rows   = []
    purchase_rows = []

    level = np.random.randint(1, 30)
    gold  = np.random.randint(1000, 50000)
    guild = np.random.choice([True, False], p=[0.4, 0.6])

    consecutive_enh_fails = 0
    stagnation_days       = 0
    prev_level            = level
    payment_stopped_day   = None  # 결제 중단일

    # payment_dropout 타입은 초반에만 결제
    if user_type == "churn_payment_dropout":
        payment_stopped_day = churn_day - 10 if churn_day else None

    for day in range(SIM_DAYS):
        current_dt = START_DATE + timedelta(days=day)

        # 이탈 이후에는 로그 없음
        if churn_day is not None and day >= churn_day:
            # 이탈 직전 며칠은 점진적으로 로그인 확률 감소
            break

        # 세션 감소 타입: 후반부로 갈수록 접속 확률 감소
        login_prob = p["login_prob"]
        session_mu = p["session_min_mu"]

        # 전체 유저에 노이즈 추가 (현실적 AUC 목표)
        login_prob = np.clip(login_prob + np.random.normal(0, 0.08), 0.01, 0.99)
        session_mu = max(5, session_mu + np.random.normal(0, 15))

        if user_type == "churn_session_decline" and churn_day:
            decay = max(0, (day - 20) / (churn_day - 20)) if day > 20 else 0
            login_prob = np.clip(p["login_prob"] * (1 - 0.6 * decay) + np.random.normal(0, 0.05), 0.01, 0.99)
            session_mu = max(5, p["session_min_mu"] * (1 - 0.5 * decay))

        # 강화 실패 누적 시 접속 확률 감소
        if consecutive_enh_fails >= 5:
            login_prob *= 0.6
            session_mu *= 0.5

        # 당일 접속 여부
        if np.random.random() > login_prob:
            # 미접속일도 status 스냅샷 기록
            status_rows.append({
                "user_id":     user_id,
                "snapshot_dt": current_dt,
                "level":       level,
                "gold":        gold,
                "guild_yn":    guild,
                "days_played": day + 1,
            })
            stagnation_days += 1
            continue

        stagnation_days = 0

        # ── 세션 생성 ──────────────────────────────────
        n_sessions = np.random.randint(1, 3)
        day_minutes = 0

        for s in range(n_sessions):
            session_minutes = max(5, int(np.random.normal(session_mu, p["session_min_sigma"])))
            login_time  = current_dt + timedelta(
                hours=np.random.randint(8, 23),
                minutes=np.random.randint(0, 59)
            )
            logout_time = login_time + timedelta(minutes=session_minutes)
            day_minutes += session_minutes

            session_rows.append({
                "user_id":         user_id,
                "session_id":      f"{user_id}_D{day:03d}_S{s}",
                "login_dt":        login_time,
                "logout_dt":       logout_time,
                "session_minutes": session_minutes,
            })

        # ── 행동 로그 생성 ─────────────────────────────
        # 강화 시도
        enh_attempts = max(0, int(np.random.poisson(p["enh_attempts_mu"])))
        for _ in range(enh_attempts):
            fail = np.random.random() < p["enh_fail_rate"]
            if fail:
                consecutive_enh_fails += 1
            else:
                consecutive_enh_fails = max(0, consecutive_enh_fails - 1)
                gold -= np.random.randint(100, 500)

            action_rows.append({
                "user_id":      user_id,
                "event_dt":     current_dt + timedelta(minutes=np.random.randint(0, day_minutes or 1)),
                "event_type":   "enhancement",
                "event_result": "fail" if fail else "success",
                "item_id":      np.random.choice(ITEM_POOL),
                "zone_id":      np.random.choice(ZONE_POOL),
            })

        # 퀘스트 클리어
        quest_count = max(0, int(np.random.poisson(p["quest_mu"])))
        for _ in range(quest_count):
            action_rows.append({
                "user_id":      user_id,
                "event_dt":     current_dt + timedelta(minutes=np.random.randint(0, day_minutes or 1)),
                "event_type":   "quest",
                "event_result": "success",
                "item_id":      np.random.choice(ITEM_POOL),
                "zone_id":      np.random.choice(ZONE_POOL),
            })
            level += np.random.choice([0, 0, 0, 1], p=[0.7, 0.15, 0.1, 0.05])
            gold  += np.random.randint(50, 300)

        # PvP
        if np.random.random() < 0.2:
            pvp_result = np.random.choice(["success", "fail"])
            action_rows.append({
                "user_id":      user_id,
                "event_dt":     current_dt + timedelta(minutes=np.random.randint(0, day_minutes or 1)),
                "event_type":   "pvp",
                "event_result": pvp_result,
                "item_id":      None,
                "zone_id":      np.random.choice(ZONE_POOL),
            })

        # ── 결제 ───────────────────────────────────────
        effective_purchase_prob = p["purchase_prob"]
        if payment_stopped_day is not None and day >= payment_stopped_day:
            effective_purchase_prob = 0.0

        if np.random.random() < effective_purchase_prob:
            item_type = np.random.choice(
                ["gacha", "battlepass", "direct"],
                p=[0.6, 0.25, 0.15]
            )
            amount = max(1000, int(np.random.normal(p["purchase_amt_mu"], p["purchase_amt_mu"] * 0.3)))
            purchase_rows.append({
                "user_id":     user_id,
                "purchase_dt": current_dt + timedelta(hours=np.random.randint(10, 22)),
                "item_type":   item_type,
                "amount_krw":  amount,
                "item_id":     np.random.choice(ITEM_POOL),
            })

        # ── 유저 상태 스냅샷 ───────────────────────────
        if day > 0 and level == prev_level:
            stagnation_days += 1
        else:
            stagnation_days = 0
        prev_level = level

        status_rows.append({
            "user_id":     user_id,
            "snapshot_dt": current_dt,
            "level":       level,
            "gold":        max(0, gold),
            "guild_yn":    guild,
            "days_played": day + 1,
        })

    return session_rows, action_rows, status_rows, purchase_rows


def generate_all(n_users: int = N_USERS) -> dict[str, pd.DataFrame]:
    user_types = assign_user_types(n_users)
    user_ids   = [f"U{i:05d}" for i in range(n_users)]

    all_sessions  = []
    all_actions   = []
    all_statuses  = []
    all_purchases = []
    user_meta     = []

    for uid, utype in tqdm(zip(user_ids, user_types), total=n_users, desc="유저 로그 생성"):
        churn_day = get_churn_day(utype)

        # 노이즈 1: 비이탈 유저 중 일부(8%)가 장기 휴식 후 복귀 (false positive 생성)
        if churn_day is None and np.random.random() < 0.08:
            churn_day = np.random.randint(55, 75)  # 로그는 끊기지만 라벨은 0
            s, a, st, p = simulate_user(uid, utype, churn_day)
            churn_label = 0  # 실제로는 이탈 아님
            churn_day = None
        # 노이즈 2: 이탈 유저 중 일부(10%)가 간헐적 복귀 (false negative 생성)
        elif churn_day is not None and np.random.random() < 0.10:
            s, a, st, p = simulate_user(uid, utype, None)  # 이탈 없이 생성
            churn_label = 1  # 라벨은 이탈
        else:
            s, a, st, p = simulate_user(uid, utype, churn_day)
            if churn_day is not None and churn_day <= (SIM_DAYS - CHURN_WINDOW):
                churn_label = 1
            else:
                churn_label = 0

        all_sessions.extend(s)
        all_actions.extend(a)
        all_statuses.extend(st)
        all_purchases.extend(p)

        user_meta.append({
            "user_id":    uid,
            "user_type":  utype,
            "churn_day":  churn_day,
            "churn_label": churn_label,
        })

    return {
        "session_logs":  pd.DataFrame(all_sessions),
        "action_logs":   pd.DataFrame(all_actions),
        "player_status": pd.DataFrame(all_statuses),
        "purchase_logs": pd.DataFrame(all_purchases),
        "user_meta":     pd.DataFrame(user_meta),
    }


def save_data(dfs: dict[str, pd.DataFrame], output_dir: str = "data/raw"):
    os.makedirs(output_dir, exist_ok=True)
    for name, df in dfs.items():
        path = os.path.join(output_dir, f"{name}.csv")
        df.to_csv(path, index=False)
        print(f"저장 완료: {path}  ({len(df):,}행)")


if __name__ == "__main__":
    print("=== MMORPG 합성 데이터 생성 시작 ===")
    dfs = generate_all()
    save_data(dfs, output_dir="data/raw")

    print("\n=== 이탈 라벨 분포 ===")
    meta = dfs["user_meta"]
    print(meta["churn_label"].value_counts())
    print(f"\n이탈율: {meta['churn_label'].mean():.1%}")

    print("\n=== 유저 타입 분포 ===")
    print(meta["user_type"].value_counts())
