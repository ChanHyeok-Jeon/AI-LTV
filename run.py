"""
전체 파이프라인 실행 스크립트

실행 순서:
  1. 합성 데이터 생성
  2. Feature Engineering
  3. 이탈 예측 모델 학습
  4. NPC 시나리오 계획 생성
  5. A/B 테스트 시뮬레이션
"""

import sys
import os
sys.path.insert(0, "src")

from src.data_generator import generate_all, save_data
from src.preprocessing  import load_raw, build_features
from src.model          import train, predict_with_features
from src.scenario_engine import build_intervention_plan, print_sample_interventions
from src.simulation     import run_simulation, print_summary, visualize

os.makedirs("models",  exist_ok=True)
os.makedirs("reports", exist_ok=True)


def main():
    print("\n" + "="*55)
    print("  에이전틱 AI LTV 극대화 파이프라인")
    print("="*55)

    # Step 1. 데이터 생성
    print("\n[1/5] 합성 데이터 생성...")
    dfs = generate_all()
    save_data(dfs, output_dir="data/raw")

    # Step 2. Feature Engineering
    print("\n[2/5] Feature Engineering...")
    features = build_features(dfs)
    os.makedirs("data/processed", exist_ok=True)
    features.to_csv("data/processed/features.csv", index=False)
    print(f"  유저 수: {len(features):,}명  |  이탈율: {features['churn_label'].mean():.1%}")

    # Step 3. 모델 학습
    print("\n[3/5] 이탈 예측 모델 학습...")
    model, auc, f1 = train(features)
    print(f"  AUC: {auc:.4f}  |  F1: {f1:.4f}")

    # Step 4. 예측 + NPC 시나리오 생성
    print("\n[4/5] NPC 개입 시나리오 생성...")
    predictions = predict_with_features(features)
    plan        = build_intervention_plan(predictions)
    print_sample_interventions(plan, n=3)

    # Step 5. A/B 테스트 시뮬레이션
    print("\n[5/5] A/B 테스트 시뮬레이션...")
    results = run_simulation(predictions, plan)
    print_summary(results)
    visualize(results)

    print("\n" + "="*55)
    print("  파이프라인 완료")
    print("  reports/ 폴더에서 결과 차트를 확인하세요.")
    print("="*55 + "\n")


if __name__ == "__main__":
    main()
