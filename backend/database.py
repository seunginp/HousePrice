# -*- coding: utf-8 -*-
import os
import sqlite3
import random
from datetime import datetime, timedelta
from regions_data import SEOUL_GYEONGGI_REGIONS

DB_PATH = os.path.join(os.path.dirname(__file__), "real_estate.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def classify_floor_group(floor: int, total_floors: int) -> str:
    if floor <= 1:
        return "1층"
    elif floor <= 5:
        return "저층(2~5층)"
    elif floor <= 15:
        return "중층(6~15층)"
    elif floor == total_floors and total_floors >= 10:
        return "탑층"
    else:
        return "고층(16층+)"


def classify_pyeong_group(pyeong: int) -> str:
    if pyeong < 20:
        return "소형(~19평)"
    elif pyeong < 30:
        return "20평대(20~29평)"
    elif pyeong < 40:
        return "30평대(30~39평)"
    elif pyeong < 50:
        return "40평대(40~49평)"
    else:
        return "대형(50평+)"


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS complexes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sido TEXT NOT NULL,
        sigungu TEXT NOT NULL,
        lawd_cd TEXT NOT NULL,
        dong TEXT NOT NULL,
        name TEXT NOT NULL,
        property_type TEXT NOT NULL, -- '아파트', '오피스텔', '빌라/연립'
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        build_year INTEGER NOT NULL,
        total_households INTEGER NOT NULL,
        max_floor INTEGER NOT NULL,
        naver_complex_no TEXT,
        kb_complex_no TEXT
    );

    CREATE TABLE IF NOT EXISTS price_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complex_id INTEGER NOT NULL,
        sido TEXT NOT NULL,
        sigungu TEXT NOT NULL,
        lawd_cd TEXT NOT NULL,
        dong TEXT NOT NULL,
        complex_name TEXT NOT NULL,
        property_type TEXT NOT NULL,
        source TEXT NOT NULL,        -- '공시가격알리미', '국토부실거래', '네이버부동산', 'KB부동산'
        trade_type TEXT NOT NULL,    -- '매매', '전세', '월세', '공시가격'
        exclusive_area REAL NOT NULL,-- 전용면적(㎡)
        supply_area REAL NOT NULL,   -- 공급면적(㎡)
        pyeong INTEGER NOT NULL,     -- 공급평수(평)
        pyeong_group TEXT NOT NULL,  -- 평수구분
        floor INTEGER NOT NULL,      -- 해당 층
        total_floors INTEGER NOT NULL,
        floor_group TEXT NOT NULL,   -- '1층', '저층(2~5층)', '중층(6~15층)', '고층(16층+)', '탑층'
        price INTEGER NOT NULL,      -- 매매가/전세가/보증금/공시가격 (단위: 만원)
        monthly_rent INTEGER DEFAULT 0, -- 월세 (단위: 만원, 월세인 경우만 > 0)
        kb_upper_price INTEGER DEFAULT 0, -- KB 상위평균가 (만원)
        kb_lower_price INTEGER DEFAULT 0, -- KB 하위평균가 (만원)
        official_price INTEGER DEFAULT 0, -- 해당 호실 기준 공시가격 (만원)
        direction TEXT DEFAULT '남향',
        record_date TEXT NOT NULL,
        description TEXT DEFAULT '',
        FOREIGN KEY (complex_id) REFERENCES complexes(id)
    );

    CREATE INDEX IF NOT EXISTS idx_records_region ON price_records(sido, sigungu, dong);
    CREATE INDEX IF NOT EXISTS idx_records_filter ON price_records(property_type, trade_type, source, pyeong, floor_group);
    CREATE INDEX IF NOT EXISTS idx_records_complex ON price_records(complex_id);
    """)

    cur.execute("SELECT COUNT(*) FROM complexes")
    count = cur.fetchone()[0]
    if count == 0:
        seed_initial_data(conn)

    conn.close()


def seed_initial_data(conn):
    """
    서울 25개 구 및 경기도 31개 시·군 전역의 단지 및 층별·평수별·출처별(공시가격알리미, 국토부실거래, 네이버부동산, KB부동산) 초기 데이터 생성
    """
    random.seed(20261021)
    cur = conn.cursor()

    apt_area_specs = [
        # (전용㎡, 공급㎡, 평수)
        (49.5, 66.1, 20),
        (59.9, 82.6, 25),
        (74.8, 99.1, 30),
        (84.9, 112.4, 34),
        (101.9, 132.2, 40),
        (114.9, 148.7, 45),
        (134.9, 171.9, 52),
    ]
    officetel_area_specs = [
        (24.5, 42.9, 13),
        (36.2, 59.5, 18),
        (52.8, 82.6, 25),
        (72.1, 105.7, 32),
        (84.5, 119.0, 36),
    ]
    villa_area_specs = [
        (33.1, 46.2, 14),
        (46.5, 62.8, 19),
        (59.4, 76.0, 23),
        (72.6, 92.5, 28),
    ]

    directions = ["남향", "남동향", "남서향", "동향"]
    complex_rows = []
    record_rows = []

    complex_id_seq = 1
    naver_id_seq = 10001
    kb_id_seq = 50001

    for reg in SEOUL_GYEONGGI_REGIONS:
        sido = reg["sido"]
        sigungu = reg["sigungu"]
        lawd_cd = reg["lawd_cd"]
        base_pyeong_price = reg["base_pyeong_price"]  # 만원 / 평

        for dong_info in reg["dongs"]:
            dong = dong_info["dong"]
            d_lat = dong_info["lat"]
            d_lng = dong_info["lng"]
            weight = dong_info["weight"]

            raw_names = list(dong_info["complexes"])
            # 각 동마다 오피스텔과 빌라/연립도 최소 1개씩 보장하여 전 지역 필터 비교 가능하게 구성
            has_offi = any("(오)" in n for n in raw_names)
            has_villa = any("(빌)" in n for n in raw_names)
            if not has_offi:
                raw_names.append(f"{dong}센트럴오피스텔(오)")
            if not has_villa:
                raw_names.append(f"{dong}더클래스빌라(빌)")

            for idx, raw_name in enumerate(raw_names):
                if "(오)" in raw_name:
                    prop_type = "오피스텔"
                    clean_name = raw_name.replace("(오)", "")
                    max_floor = random.choice([15, 18, 22, 28])
                    households = random.randint(180, 750)
                    build_year = random.randint(2012, 2024)
                    area_pool = random.sample(officetel_area_specs, k=3)
                    type_price_factor = 0.68
                elif "(빌)" in raw_name:
                    prop_type = "빌라/연립"
                    clean_name = raw_name.replace("(빌)", "")
                    max_floor = random.choice([4, 5, 6])
                    households = random.randint(16, 48)
                    build_year = random.randint(2008, 2023)
                    area_pool = random.sample(villa_area_specs, k=3)
                    type_price_factor = 0.56
                else:
                    prop_type = "아파트"
                    clean_name = raw_name
                    max_floor = random.choice([15, 20, 25, 30, 35, 42])
                    households = random.randint(350, 2800)
                    build_year = random.randint(1996, 2024)
                    # 국민평형(25평, 34평) 필수 포함 + 추가 평형
                    area_pool = [apt_area_specs[1], apt_area_specs[3], random.choice([apt_area_specs[0], apt_area_specs[2], apt_area_specs[4], apt_area_specs[5]])]
                    type_price_factor = 1.0

                # 좌표 약간 분산
                angle_offset = (idx + 1) * 0.0022
                c_lat = round(d_lat + random.uniform(-0.0045, 0.0045) + (angle_offset if idx % 2 == 0 else -angle_offset) * 0.3, 6)
                c_lng = round(d_lng + random.uniform(-0.0055, 0.0055) + (angle_offset if idx % 3 == 0 else -angle_offset) * 0.3, 6)

                c_id = complex_id_seq
                complex_id_seq += 1
                naver_no = str(naver_id_seq)
                kb_no = f"KB{kb_id_seq}"
                naver_id_seq += 1
                kb_id_seq += 1

                complex_rows.append((
                    c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                    c_lat, c_lng, build_year, households, max_floor, naver_no, kb_no
                ))

                # 단지 고유 가격 가중치
                complex_factor = weight * type_price_factor * random.uniform(0.93, 1.08)
                complex_pyeong_price = base_pyeong_price * complex_factor

                for exc_area, sup_area, pyeong in area_pool:
                    pyeong_group = classify_pyeong_group(pyeong)
                    base_sale_price = int(round((complex_pyeong_price * pyeong) / 100.0) * 100)  # 백만원 단위 반올림(만원)
                    if base_sale_price < 8000:
                        base_sale_price = 8000

                    # 층별 가격 차등 (1층: 0.91, 저층: 0.95, 중층: 1.00, 고층: 1.05, 탑층: 1.03)
                    if prop_type == "빌라/연립":
                        floor_samples = [
                            (1, 0.91),
                            (2, 0.96),
                            (3, 1.00),
                            (max_floor, 0.98)
                        ]
                    else:
                        mid_f = max(6, min(12, max_floor // 2))
                        high_f = max(16, min(max_floor - 1, int(max_floor * 0.8)))
                        floor_samples = [
                            (1, 0.91),
                            (random.randint(2, 5), 0.95),
                            (mid_f, 1.00),
                            (high_f, 1.05),
                            (max_floor, 1.03)
                        ]

                    jeonse_ratio = random.uniform(0.54, 0.66) if prop_type == "아파트" else random.uniform(0.62, 0.74)
                    official_ratio = random.uniform(0.67, 0.73)  # 공시가격 현실화율 약 69%

                    for fl, fl_factor in floor_samples:
                        fl_group = classify_floor_group(fl, max_floor)
                        fl_sale = int(round((base_sale_price * fl_factor) / 50.0) * 50)
                        fl_official = int(round((fl_sale * official_ratio) / 10.0) * 10)
                        fl_jeonse = int(round((fl_sale * jeonse_ratio) / 50.0) * 50)
                        direction = random.choice(directions)

                        # 1) 부동산공시가격 알리미 (공시가격)
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "공시가격알리미", "공시가격",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            fl_official, 0, 0, 0, fl_official,
                            direction, "2026-04-30",
                            f"2026년 정기 공동주택 공시가격 (현실화율 {int(official_ratio*100)}%)"
                        ))

                        # 2) 국토부실거래 (매매 실거래)
                        real_sale = int(round((fl_sale * random.uniform(0.98, 1.02)) / 50.0) * 50)
                        days_ago = random.randint(3, 60)
                        t_date = (datetime(2026, 10, 20) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "국토부실거래", "매매",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            real_sale, 0, 0, 0, fl_official,
                            direction, t_date,
                            "국토교통부 실거래가 공개시스템 등기/신고 완료"
                        ))

                        # 3) 국토부실거래 (전세 실거래)
                        real_jeonse = int(round((fl_jeonse * random.uniform(0.97, 1.03)) / 50.0) * 50)
                        t_date_j = (datetime(2026, 10, 20) - timedelta(days=random.randint(2, 45))).strftime("%Y-%m-%d")
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "국토부실거래", "전세",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            real_jeonse, 0, 0, 0, fl_official,
                            direction, t_date_j,
                            "국토교통부 전월세 실거래 신고"
                        ))

                        # 4) 네이버부동산 (매매 호가 - 보통 실거래 대비 +2%~+6%)
                        naver_asking_sale = int(round((fl_sale * random.uniform(1.02, 1.06)) / 50.0) * 50)
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "네이버부동산", "매매",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            naver_asking_sale, 0, 0, 0, fl_official,
                            direction, "2026-10-20",
                            f"네이버 확인매물 · {direction} · {fl_group} 올수리/즉시입주 협의"
                        ))

                        # 5) 네이버부동산 (전세 호가)
                        naver_asking_jeonse = int(round((fl_jeonse * random.uniform(1.01, 1.05)) / 50.0) * 50)
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "네이버부동산", "전세",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            naver_asking_jeonse, 0, 0, 0, fl_official,
                            direction, "2026-10-20",
                            f"네이버 확인매물 · 융자무 · 전세대출가능 ({direction})"
                        ))

                        # 6) 네이버부동산 & 국토부실거래 (월세)
                        deposit = int(round((fl_jeonse * random.choice([0.15, 0.25, 0.35])) / 100.0) * 100)
                        if deposit < 1000:
                            deposit = 1000
                        # 전월세 전환율 약 5.2% 적용
                        converted_diff = max(1000, fl_jeonse - deposit)
                        monthly_rent = max(35, int(round((converted_diff * 0.052) / 12.0 / 5.0) * 5))
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "네이버부동산", "월세",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            deposit, monthly_rent, 0, 0, fl_official,
                            direction, "2026-10-20",
                            f"보증금 {deposit:,}만 / 월 {monthly_rent:,}만 · 에어컨/풀옵션"
                        ))
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "국토부실거래", "월세",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            deposit, max(30, monthly_rent - 5), 0, 0, fl_official,
                            direction, t_date_j,
                            f"전월세 실거래 신고 (보증금 {deposit:,}만 / 월 {max(30, monthly_rent - 5):,}만)"
                        ))

                        # 7) KB부동산 시세 (매매 일반가/상위가/하위가 & 전세 일반가)
                        kb_general = int(round((base_sale_price * fl_factor) / 50.0) * 50)
                        kb_upper = int(round((base_sale_price * 1.05) / 50.0) * 50)
                        kb_lower = int(round((base_sale_price * 0.93) / 50.0) * 50)
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "KB부동산", "매매",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            kb_general, 0, kb_upper, kb_lower, fl_official,
                            direction, "2026-10-18",
                            f"KB 시세 일반가 {kb_general:,}만 (하위가 {kb_lower:,}만 ~ 상위가 {kb_upper:,}만)"
                        ))
                        kb_jeonse = int(round((fl_jeonse * 0.99) / 50.0) * 50)
                        record_rows.append((
                            c_id, sido, sigungu, lawd_cd, dong, clean_name, prop_type,
                            "KB부동산", "전세",
                            exc_area, sup_area, pyeong, pyeong_group,
                            fl, max_floor, fl_group,
                            kb_jeonse, 0, int(kb_jeonse * 1.04), int(kb_jeonse * 0.94), fl_official,
                            direction, "2026-10-18",
                            f"KB 전세시세 일반가 {kb_jeonse:,}만 (전세가율 {int(jeonse_ratio*100)}%)"
                        ))

    cur.executemany("""
        INSERT INTO complexes (
            id, sido, sigungu, lawd_cd, dong, name, property_type,
            lat, lng, build_year, total_households, max_floor, naver_complex_no, kb_complex_no
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, complex_rows)

    cur.executemany("""
        INSERT INTO price_records (
            complex_id, sido, sigungu, lawd_cd, dong, complex_name, property_type,
            source, trade_type, exclusive_area, supply_area, pyeong, pyeong_group,
            floor, total_floors, floor_group, price, monthly_rent,
            kb_upper_price, kb_lower_price, official_price, direction, record_date, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, record_rows)

    conn.commit()
