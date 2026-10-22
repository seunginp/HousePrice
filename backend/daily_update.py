# -*- coding: utf-8 -*-
"""
매일 자동 실행되는 서울·경기 전체 단지 시세 및 청약/분양 일정 업데이트 스크립트
(GitHub Actions Daily Cron 및 로컬 스케줄러에서 실행)
"""
from build_full_dataset import collect_all_seoul_gyeonggi
from generate_all_data import build_all_data

if __name__ == "__main__":
    print("[1/2] 서울·경기 전체 아파트·오피스텔·연립 시세 및 청약/분양 데이터 최신 수집 시작...")
    collect_all_seoul_gyeonggi()
    print("[2/2] data.js 통합 데이터셋 재생성 시작...")
    build_all_data()
    print("✅ 일일 데이터 자동 업데이트 완료!")
