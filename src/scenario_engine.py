"""
NPC 시나리오 엔진

이탈 원인 분류 결과를 바탕으로:
  - 어떤 NPC가 트리거될지
  - NPC 대사 (유저 행동 데이터를 참조)
  - 제안할 퀘스트/상품
을 결정합니다.
"""

import pandas as pd
import numpy as np
import random

random.seed(42)


# ── 시나리오 정의 ──────────────────────────────────────
SCENARIOS = {
    "강화_실패": {
        "npc": "대장장이 로스반",
        "dialogues": [
            "요즘 강화가 잘 안 풀리는 것 같군... 마침 내게 특별한 재료가 생겼는데, 한번 써보겠나?",
            "이 재료를 쓰면 성공률이 달라질 걸세. 며칠 전부터 자네 무기 상태가 신경 쓰이던 참이었지.",
            "강화에 계속 실패하면 기운이 빠지지. 내가 도움이 될 수 있을 것 같은데.",
        ],
        "quest": {
            "name": "대장장이의 비법 재료",
            "description": "로스반에게서 강화 성공률 증가 재료를 받아 무기를 강화하라.",
            "reward": "강화 성공률 +30% 아이템 x3",
        },
        "product": {
            "name": "강화의 축복 패키지",
            "type": "direct",
            "price": 2900,
            "contents": "강화 성공률 +50% x5 + 강화 보호석 x2",
        },
    },

    "구간_정체": {
        "npc": "용사 길드장 에리아",
        "dialogues": [
            "혼자 하기 버거운 구간이지. 마침 같이 도전할 만한 동료를 알고 있는데, 소개해줄까?",
            "이 구간은 파티를 짜면 훨씬 수월해. 내가 도움이 될 동료들을 연결해줄 수 있어.",
            "벽에 막혀 있구나. 잠깐 다른 방향으로 힘을 키우는 건 어떨까? 특별 임무가 하나 있는데.",
        ],
        "quest": {
            "name": "길드장의 특별 의뢰",
            "description": "에리아가 추천한 파티원과 함께 현재 구간의 보스를 처치하라.",
            "reward": "경험치 +50% 버프 24시간 + 장비 강화 재료",
        },
        "product": {
            "name": "성장 가속 배틀패스",
            "type": "battlepass",
            "price": 4900,
            "contents": "30일 경험치 +30% + 주간 특별 퀘스트 + 전용 스킨",
        },
    },

    "접속_감소": {
        "npc": "여관 주인 마르타",
        "dialogues": [
            "오랜만이군요, 모험가님. 자리를 비운 사이 마을에 새로운 소식이 많이 생겼답니다.",
            "요즘 바쁘셨나요? 오늘 오신 걸 환영해요. 특별히 준비한 게 있어요.",
            "다시 뵙게 되어 반가워요. 오늘 하루는 여관에서 특별 버프를 드릴게요.",
        ],
        "quest": {
            "name": "복귀 모험가를 위한 특별 의뢰",
            "description": "마르타의 부탁으로 마을 인근 퀘스트 3개를 완료하라.",
            "reward": "복귀 보상 상자 (랜덤 장비) + 골드 5,000",
        },
        "product": {
            "name": "복귀 환영 패키지",
            "type": "direct",
            "price": 1900,
            "contents": "소비형 버프 아이템 세트 + 경험치 부스터 7일",
        },
    },

    "결제_이탈": {
        "npc": "모험가 협회장 드레이크",
        "dialogues": [
            "자네 실력이라면 이 특별 임무에 딱 맞아. 협회에서 전폭 지원을 해줄 수도 있는데.",
            "오랫동안 활약을 지켜봤네. 이번에 협회 멤버십을 업그레이드하면 특별 혜택이 있어.",
            "훌륭한 모험가에게는 그에 맞는 장비가 필요하지. 마침 특별 가격에 드릴 수 있는 물건이 있네.",
        ],
        "quest": {
            "name": "협회 특급 의뢰",
            "description": "드레이크의 비밀 임무를 수행하고 협회 최고 등급 보상을 받아라.",
            "reward": "고급 장비 상자 + 협회 전용 칭호",
        },
        "product": {
            "name": "시즌 패스 (첫 구매 50% 할인)",
            "type": "battlepass",
            "price": 2450,
            "contents": "30일 시즌 패스 전체 혜택 (정가 4,900원에서 50% 할인)",
        },
    },

    "일반_피로": {
        "npc": "여관 주인 마르타",
        "dialogues": [
            "오늘은 좀 쉬다 가는 건 어떨까요? 특별히 오늘 하루만 쓸 수 있는 걸 드릴게요.",
            "모험가님, 피곤해 보이세요. 여관에서 잠깐 쉬고 가세요. 작은 선물도 있어요.",
            "가끔은 쉬는 것도 힘이 된답니다. 오늘 로그인 보상이 조금 특별하게 준비되어 있어요.",
        ],
        "quest": {
            "name": "마을 축제 참여",
            "description": "마을 축제에서 미니게임 3종을 즐겨라. 부담 없이 즐길 수 있어요.",
            "reward": "소모성 버프 아이템 x5 + 코스튬 조각",
        },
        "product": {
            "name": "일일 특별 보상 패키지",
            "type": "direct",
            "price": 990,
            "contents": "오늘 하루 한정 소비형 아이템 꾸러미",
        },
    },
}


def build_intervention_plan(prediction_df: pd.DataFrame) -> pd.DataFrame:
    """
    예측 결과 DataFrame을 받아 개입 계획을 생성합니다.

    Parameters:
        prediction_df: model.predict_with_features() 결과
            필수 컬럼: user_id, churn_prob, churn_risk, churn_reason,
                       enhancement_fail_rate, enhancement_attempts_7d,
                       stage_stagnation_days, session_trend, session_count_7d

    Returns:
        개입 대상 유저별 시나리오 DataFrame
    """
    # 고위험군만 개입 대상
    targets = prediction_df[prediction_df["churn_risk"] == "high"].copy()

    rows = []
    for _, user in targets.iterrows():
        reason   = user["churn_reason"]
        scenario = SCENARIOS.get(reason, SCENARIOS["일반_피로"])

        dialogue = random.choice(scenario["dialogues"])
        dialogue = _personalize_dialogue(dialogue, user)

        rows.append({
            "user_id":         user["user_id"],
            "churn_prob":      round(user["churn_prob"], 3),
            "churn_reason":    reason,
            "npc_name":        scenario["npc"],
            "npc_dialogue":    dialogue,
            "quest_name":      scenario["quest"]["name"],
            "quest_desc":      scenario["quest"]["description"],
            "quest_reward":    scenario["quest"]["reward"],
            "product_name":    scenario["product"]["name"],
            "product_type":    scenario["product"]["type"],
            "product_price":   scenario["product"]["price"],
            "product_contents":scenario["product"]["contents"],
        })

    return pd.DataFrame(rows)


def _personalize_dialogue(dialogue: str, user: pd.Series) -> str:
    """대사에 유저 실제 데이터를 반영합니다."""
    fail_count = int(user.get("enhancement_fails_7d", 0)) if "enhancement_fails_7d" in user.index else 0
    stagnation = int(user.get("stage_stagnation_days", 0))
    days_away  = int(user.get("days_since_last_login", 0))

    if fail_count > 0 and "강화" in dialogue:
        dialogue = dialogue.replace(
            "강화가 잘 안 풀리는 것 같군",
            f"요 며칠 강화를 {fail_count}번이나 실패했군"
        )
    if stagnation > 3 and "구간" in dialogue:
        dialogue = dialogue.replace(
            "버거운 구간이지",
            f"{stagnation}일째 같은 구간에서 고생하고 있구나"
        )
    if days_away > 3 and "오랜만" in dialogue:
        dialogue = dialogue.replace(
            "오랜만이군요",
            f"{days_away}일 만이군요"
        )

    return dialogue


def print_sample_interventions(plan: pd.DataFrame, n: int = 5):
    """개입 계획 샘플 출력"""
    print(f"\n{'='*60}")
    print(f"  개입 대상 유저: {len(plan):,}명")
    print(f"{'='*60}")

    for _, row in plan.head(n).iterrows():
        print(f"\n유저: {row['user_id']}  |  이탈 확률: {row['churn_prob']:.1%}  |  원인: {row['churn_reason']}")
        print(f"  NPC:  {row['npc_name']}")
        print(f"  대사: \"{row['npc_dialogue']}\"")
        print(f"  퀘스트: {row['quest_name']} → {row['quest_reward']}")
        print(f"  상품: {row['product_name']} ({row['product_price']:,}원)")

    print(f"\n{'='*60}")
    print("이탈 원인 분포:")
    print(plan["churn_reason"].value_counts().to_string())


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")

    from preprocessing import load_raw, build_features
    from model import predict_with_features

    print("=== 데이터 로드 ===")
    dfs      = load_raw("data/raw")
    features = build_features(dfs)

    print("=== 이탈 예측 ===")
    predictions = predict_with_features(features)

    print("=== NPC 개입 계획 생성 ===")
    plan = build_intervention_plan(predictions)

    print_sample_interventions(plan)

    plan.to_csv("data/processed/intervention_plan.csv", index=False)
    print(f"\n개입 계획 저장: data/processed/intervention_plan.csv")
