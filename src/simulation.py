"""
A/B 테스트 시뮬레이션

개입군(NPC 시나리오 적용) vs 대조군(개입 없음)의
- 세션 유지율
- 이탈 방지율
- LTV 추정치
를 비교합니다.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'AppleGothic'
matplotlib.rcParams['axes.unicode_minus'] = False
import os

np.random.seed(42)

# 시나리오별 개입 효과 (이탈 방지 확률)
# 근거: MDPI 2022 (비개인화 개입 효과 없음) 반면교사
#       Playio 사례 (맞춤 개입 시 리텐션 개선)
INTERVENTION_EFFECT = {
    "강화_실패":  0.35,   # 강화 보조 아이템 → 명확한 동기부여
    "구간_정체":  0.28,   # 파티 매칭 → 사회적 연결
    "접속_감소":  0.22,   # 복귀 보상 → 복귀 유도
    "결제_이탈":  0.20,   # 할인 제안 → 재결제 유도
    "일반_피로":  0.12,   # 소모성 보상 → 단기 유지
    "normal":     0.00,   # 개입 없음
}

# 시나리오별 결제 전환율 (CVR)
PURCHASE_CVR = {
    "강화_실패":  0.12,
    "구간_정체":  0.08,
    "접속_감소":  0.06,
    "결제_이탈":  0.15,   # 할인 효과
    "일반_피로":  0.04,
    "normal":     0.0,
}

# 시나리오별 상품 가격 (원)
PRODUCT_PRICE = {
    "강화_실패":  2900,
    "구간_정체":  4900,
    "접속_감소":  1900,
    "결제_이탈":  2450,
    "일반_피로":   990,
    "normal":        0,
}

# 유저 평균 일일 과금액 (잔존 유저 기준)
AVG_DAILY_SPEND_KRW = 300


def estimate_ltv(retained: bool, days: int = 30, daily_spend: float = AVG_DAILY_SPEND_KRW) -> float:
    """간단한 LTV 추정: 잔존 시 30일치 평균 소비"""
    return days * daily_spend if retained else 0.0


def run_simulation(
    prediction_df: pd.DataFrame,
    plan_df: pd.DataFrame,
    n_simulations: int = 1000,
) -> dict:
    """
    고위험군 유저를 대상으로 A/B 테스트를 시뮬레이션합니다.

    Parameters:
        prediction_df: 전체 유저 예측 결과
        plan_df:       개입 계획 (scenario_engine 출력)

    Returns:
        결과 딕셔너리
    """
    high_risk = prediction_df[prediction_df["churn_risk"] == "high"].copy()
    n_high    = len(high_risk)

    # A/B 그룹 분배 (50:50)
    shuffled  = high_risk.sample(frac=1, random_state=42).reset_index(drop=True)
    treatment = shuffled.iloc[:n_high // 2].copy()
    control   = shuffled.iloc[n_high // 2:].copy()

    # 개입군: product_price만 plan_df에서 가져옴 (churn_reason은 이미 있음)
    treatment = treatment.merge(
        plan_df[["user_id", "product_price"]],
        on="user_id", how="left"
    )
    treatment["product_price"] = treatment["product_price"].fillna(0)

    treatment["intervention_effect"] = treatment["churn_reason"].map(INTERVENTION_EFFECT)
    treatment["purchase_cvr"]        = treatment["churn_reason"].map(PURCHASE_CVR)

    # 잔존 여부 시뮬레이션
    treatment["retained"] = np.random.random(len(treatment)) < treatment["intervention_effect"]
    control["retained"]   = np.random.random(len(control)) < 0.12  # 대조군: ~12% 자연 복귀

    # 결제 시뮬레이션
    treatment["purchased"] = (
        treatment["retained"] &
        (np.random.random(len(treatment)) < treatment["purchase_cvr"])
    )
    treatment["revenue"] = (
        treatment["purchased"] * treatment["product_price"] +
        treatment["retained"]  * (AVG_DAILY_SPEND_KRW * 30)
    )

    control["purchased"] = False
    control["revenue"]   = control["retained"] * (AVG_DAILY_SPEND_KRW * 30)

    # ── 결과 집계 ──────────────────────────────────────
    results = {
        "n_treatment":           len(treatment),
        "n_control":             len(control),

        # 이탈 방지율
        "treatment_retention":   treatment["retained"].mean(),
        "control_retention":     control["retained"].mean(),
        "retention_lift":        treatment["retained"].mean() - control["retained"].mean(),
        "retention_lift_pct":    (treatment["retained"].mean() - control["retained"].mean()) * 100,  # 절대값 %p

        # 결제
        "treatment_cvr":         treatment["purchased"].mean(),
        "control_cvr":           0.0,
        "cvr_lift":              treatment["purchased"].mean(),

        # LTV (1인당 평균)
        "treatment_ltv":         treatment["revenue"].mean(),
        "control_ltv":           control["revenue"].mean(),
        "ltv_lift_pct":          (treatment["revenue"].mean() - control["revenue"].mean()) / max(control["revenue"].mean(), 1e-9) * 100,

        # 총 매출 기여
        "treatment_total_revenue": treatment["revenue"].sum(),
        "control_total_revenue":   control["revenue"].sum(),

        "treatment_df": treatment,
        "control_df":   control,
    }

    return results


def visualize(results: dict, output_dir: str = "reports"):
    os.makedirs(output_dir, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("A/B 테스트 시뮬레이션 결과", fontsize=14, fontweight="bold")

    # 1. 잔존율 비교
    groups   = ["대조군", "개입군"]
    ret_vals = [results["control_retention"], results["treatment_retention"]]
    bars = axes[0].bar(groups, [v * 100 for v in ret_vals], color=["#aec6cf", "#4a90d9"], width=0.4)
    axes[0].set_title("세션 유지율 (잔존율)")
    axes[0].set_ylabel("%")
    axes[0].set_ylim(0, max(ret_vals) * 100 * 1.4)
    for bar, val in zip(bars, ret_vals):
        axes[0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                     f"{val:.1%}", ha="center", fontsize=11, fontweight="bold")
    axes[0].annotate(
        f"{results['retention_lift_pct']:+.1f}%p",
        xy=(0.5, max(ret_vals) * 100 * 1.2), ha="center", color="#c0392b", fontsize=11, fontweight="bold"
    )

    # 2. CVR 비교
    cvr_vals = [results["control_cvr"], results["treatment_cvr"]]
    bars2 = axes[1].bar(groups, [v * 100 for v in cvr_vals], color=["#aec6cf", "#e8a838"], width=0.4)
    axes[1].set_title("맞춤 상품 구매 전환율 (CVR)")
    axes[1].set_ylabel("%")
    axes[1].set_ylim(0, max(cvr_vals) * 100 * 1.6 + 1)
    for bar, val in zip(bars2, cvr_vals):
        axes[1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                     f"{val:.1%}", ha="center", fontsize=11, fontweight="bold")

    # 3. LTV 비교
    ltv_vals = [results["control_ltv"], results["treatment_ltv"]]
    bars3 = axes[2].bar(groups, ltv_vals, color=["#aec6cf", "#5cb85c"], width=0.4)
    axes[2].set_title("1인당 추정 LTV (원)")
    axes[2].set_ylabel("원")
    axes[2].set_ylim(0, max(ltv_vals) * 1.4)
    for bar, val in zip(bars3, ltv_vals):
        axes[2].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 10,
                     f"{val:,.0f}", ha="center", fontsize=10, fontweight="bold")
    axes[2].annotate(
        f"+{results['ltv_lift_pct']:.1f}%",
        xy=(0.5, max(ltv_vals) * 1.25), ha="center", color="#c0392b", fontsize=11
    )

    plt.tight_layout()
    path = os.path.join(output_dir, "ab_test_results.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"A/B 테스트 차트 저장: {path}")


def print_summary(results: dict):
    print(f"\n{'='*55}")
    print("  A/B 테스트 시뮬레이션 결과 요약")
    print(f"{'='*55}")
    print(f"  대상 유저 (고위험군)")
    print(f"    개입군:  {results['n_treatment']:,}명")
    print(f"    대조군:  {results['n_control']:,}명")
    print(f"\n  세션 유지율 (이탈 방지)")
    print(f"    대조군:  {results['control_retention']:.1%}")
    print(f"    개입군:  {results['treatment_retention']:.1%}")
    print(f"    개선폭:  {results['retention_lift_pct']:+.1f}%p (절대값)  ← 목표 +10%p")
    print(f"\n  맞춤 상품 CVR")
    print(f"    대조군:  {results['control_cvr']:.1%}")
    print(f"    개입군:  {results['treatment_cvr']:.1%}")
    print(f"    개선폭:  +{results['cvr_lift']:.1%}  ← 목표 +3%p")
    print(f"\n  1인당 LTV 추정")
    print(f"    대조군:  {results['control_ltv']:,.0f}원")
    print(f"    개입군:  {results['treatment_ltv']:,.0f}원")
    print(f"    개선율:  {results['ltv_lift_pct']:+.1f}%  ← 목표 +15%")
    print(f"\n  총 매출 기여")
    print(f"    대조군:  {results['control_total_revenue']:,.0f}원")
    print(f"    개입군:  {results['treatment_total_revenue']:,.0f}원")
    print(f"{'='*55}")

    # Go/No-Go 판정
    go = results["retention_lift_pct"] >= 10
    print(f"\n  Go/No-Go 판정: {'✅ GO' if go else '❌ NO-GO'}")
    print(f"  (세션 유지율 대조군 대비 +{results['retention_lift_pct']:.1f}%p, 기준: +10%p)")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")

    from preprocessing import load_raw, build_features
    from model import predict_with_features
    from scenario_engine import build_intervention_plan

    print("=== 전체 파이프라인 실행 ===")

    dfs         = load_raw("data/raw")
    features    = build_features(dfs)
    predictions = predict_with_features(features)
    plan        = build_intervention_plan(predictions)

    print(f"\n전체 유저: {len(predictions):,}명")
    print(f"고위험군:  {(predictions['churn_risk'] == 'high').sum():,}명")

    results = run_simulation(predictions, plan)
    print_summary(results)
    visualize(results)

    plan.to_csv("data/processed/intervention_plan.csv", index=False)
    print(f"\n개입 계획 저장: data/processed/intervention_plan.csv")
