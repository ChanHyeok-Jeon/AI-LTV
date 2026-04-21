"""
이탈 예측 모델 — XGBoost 기반

출력:
  - 이탈 확률 (0~1)
  - 이탈 원인 분류 (rule-based 후처리)
  - 모델 평가 리포트 (AUC, F1, Classification Report)
  - SHAP Feature Importance 시각화
"""

import pandas as pd
import numpy as np
import os
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'AppleGothic'
matplotlib.rcParams['axes.unicode_minus'] = False

from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import (
    roc_auc_score, f1_score, classification_report,
    confusion_matrix, ConfusionMatrixDisplay, RocCurveDisplay
)
from xgboost import XGBClassifier
import shap
import joblib

from preprocessing import FEATURE_COLS, build_features, load_raw


# ── 이탈 원인 분류 (Rule-based) ────────────────────────
def classify_churn_reason(row: pd.Series) -> str:
    """이탈 고위험 유저에 대해 원인을 분류합니다."""
    if row["churn_prob"] < 0.5:
        return "normal"

    # 점수 방식: 각 원인의 고유 신호만 사용 (접속_감소는 다른 원인에 해당 안 될 때 최후 판단)
    scores = {
        "강화_실패": 0,
        "구간_정체": 0,
        "결제_이탈": 0,
        "접속_감소": 0,
        "일반_피로": 0,
    }

    # 강화 실패 고유 신호 (강화를 시도했으나 실패율이 높음)
    if row["enhancement_attempts_7d"] >= 2:
        if row["enhancement_fail_rate"] > 0.65:
            scores["강화_실패"] += 3
        elif row["enhancement_fail_rate"] > 0.55:
            scores["강화_실패"] += 2

    # 구간 정체 고유 신호 (접속은 하지만 성장이 없음)
    if row["session_count_7d"] >= 2:  # 접속은 하고 있음
        if row["level_gain_7d"] == 0 and row["stage_stagnation_days"] >= 3:
            scores["구간_정체"] += 3
        elif row["quest_clear_7d"] <= 1 and row["stage_stagnation_days"] >= 2:
            scores["구간_정체"] += 2

    # 결제 이탈 고유 신호 (과거 결제 이력 있으나 최근 중단)
    if row["last_purchase_days_ago"] > 25 and row["purchase_count_7d"] == 0:
        if row["last_purchase_days_ago"] > 40:
            scores["결제_이탈"] += 3
        else:
            scores["결제_이탈"] += 2

    # 접속 감소 (세션 추세가 뚜렷하게 감소)
    if row["session_trend"] < 0.5 and row["session_count_7d"] <= 2:
        scores["접속_감소"] += 3
    elif row["session_trend"] < 0.7 and row["session_count_7d"] <= 3:
        scores["접속_감소"] += 1

    # 가장 높은 점수의 원인 반환 (동점이면 일반_피로)
    top_score = max(scores.values())
    if top_score == 0:
        return "일반_피로"
    top = max(scores, key=scores.get)
    return top


# ── 모델 학습 ─────────────────────────────────────────
def train(features: pd.DataFrame, output_dir: str = "models"):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    X = features[FEATURE_COLS].values
    y = features["churn_label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = XGBClassifier(
        n_estimators     = 300,
        max_depth        = 5,
        learning_rate    = 0.05,
        subsample        = 0.8,
        colsample_bytree = 0.8,
        scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum(),
        eval_metric      = "auc",
        random_state     = 42,
        verbosity        = 0,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # ── 평가 ──────────────────────────────────────────
    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    auc = roc_auc_score(y_test, y_prob)
    f1  = f1_score(y_test, y_pred)

    print(f"\n{'='*45}")
    print(f"  AUC : {auc:.4f}   |   F1 : {f1:.4f}")
    print(f"{'='*45}")
    print(classification_report(y_test, y_pred, target_names=["잔존", "이탈"]))

    # ── 시각화 저장 ────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # ROC Curve
    RocCurveDisplay.from_predictions(y_test, y_prob, ax=axes[0])
    axes[0].set_title(f"ROC Curve  (AUC={auc:.3f})")

    # Confusion Matrix
    ConfusionMatrixDisplay(
        confusion_matrix(y_test, y_pred),
        display_labels=["잔존", "이탈"]
    ).plot(ax=axes[1])
    axes[1].set_title("Confusion Matrix")

    plt.tight_layout()
    plt.savefig("reports/model_evaluation.png", dpi=150)
    plt.close()
    print("평가 차트 저장: reports/model_evaluation.png")

    # ── SHAP Feature Importance ────────────────────────
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    plt.figure(figsize=(8, 6))
    shap.summary_plot(
        shap_values, X_test,
        feature_names=FEATURE_COLS,
        plot_type="bar",
        show=False,
    )
    plt.title("Feature Importance (SHAP)")
    plt.tight_layout()
    plt.savefig("reports/shap_importance.png", dpi=150)
    plt.close()
    print("SHAP 차트 저장: reports/shap_importance.png")

    # ── 모델 저장 ──────────────────────────────────────
    model_path = os.path.join(output_dir, "churn_model.pkl")
    joblib.dump(model, model_path)
    print(f"모델 저장: {model_path}")

    return model, auc, f1


# ── 예측 (배치) ────────────────────────────────────────
def predict(features: pd.DataFrame, model_path: str = "models/churn_model.pkl") -> pd.DataFrame:
    model  = joblib.load(model_path)
    X      = features[FEATURE_COLS].values
    probs  = model.predict_proba(X)[:, 1]

    result = features[["user_id"]].copy()
    result["churn_prob"]   = probs
    result["churn_risk"]   = pd.cut(
        probs,
        bins=[-0.001, 0.3, 0.6, 1.001],
        labels=["low", "medium", "high"]
    )
    result["churn_reason"] = result.apply(
        lambda row: classify_churn_reason(
            pd.concat([row, features.loc[features["user_id"] == row["user_id"]].iloc[0][FEATURE_COLS]])
        ),
        axis=1
    )

    return result


def predict_with_features(features: pd.DataFrame, model_path: str = "models/churn_model.pkl") -> pd.DataFrame:
    """피처 DataFrame과 예측 결과를 합쳐서 반환 (시나리오 엔진용)"""
    model = joblib.load(model_path)
    X     = features[FEATURE_COLS].values
    probs = model.predict_proba(X)[:, 1]

    result = features.copy()
    result["churn_prob"] = probs
    result["churn_risk"] = pd.cut(
        probs,
        bins=[-0.001, 0.3, 0.6, 1.001],
        labels=["low", "medium", "high"]
    )
    result["churn_reason"] = result.apply(classify_churn_reason, axis=1)

    return result


if __name__ == "__main__":
    print("=== 데이터 로드 및 피처 생성 ===")
    dfs      = load_raw("data/raw")
    features = build_features(dfs)

    print(f"전체 유저: {len(features):,}명  |  이탈율: {features['churn_label'].mean():.1%}")

    print("\n=== 모델 학습 ===")
    model, auc, f1 = train(features)

    print("\n=== 배치 예측 예시 (상위 10명) ===")
    result = predict_with_features(features)
    high_risk = result[result["churn_risk"] == "high"].sort_values("churn_prob", ascending=False)
    print(high_risk[["user_id", "churn_prob", "churn_reason"]].head(10).to_string(index=False))

    print(f"\n고위험군 유저 수: {(result['churn_risk'] == 'high').sum():,}명")
    print("\n이탈 원인 분포:")
    print(result[result["churn_risk"] == "high"]["churn_reason"].value_counts())
