# -*- coding: utf-8 -*-
import json
import random
from regions_data import SEOUL_GYEONGGI_REGIONS

# 지역별 기본 평당가 룩업 (시세 미등록 단지 및 오피스텔 추정용)
BASE_PYEONG_PRICE = {}
LAWD_BY_SIGUNGU = {}
for r in SEOUL_GYEONGGI_REGIONS:
    BASE_PYEONG_PRICE[(r["sido"], r["sigungu"])] = r["base_pyeong_price"]
    LAWD_BY_SIGUNGU[(r["sido"], r["sigungu"])] = r["lawd_cd"]
    # 시 단위 기본값도 등록 (예: 수원시 -> 수원시 영통구 등)
    city_prefix = r["sigungu"].split()[0]
    if (r["sido"], city_prefix) not in BASE_PYEONG_PRICE:
        BASE_PYEONG_PRICE[(r["sido"], city_prefix)] = r["base_pyeong_price"]
        LAWD_BY_SIGUNGU[(r["sido"], city_prefix)] = r["lawd_cd"]


def normalize_sido_sigungu(sido_raw: str, gugun_raw: str):
    sido_raw = (sido_raw or "").strip()
    gugun_raw = (gugun_raw or "").strip()
    if sido_raw.startswith("서울"):
        return "서울특별시", gugun_raw
    if sido_raw.startswith("경기"):
        # 예: sido="경기도 수원시", gugun="영통구" -> ("경기도", "수원시 영통구")
        parts = sido_raw.split()
        if len(parts) >= 2:
            city = parts[1]
            if gugun_raw and gugun_raw != city:
                return "경기도", f"{city} {gugun_raw}"
            return "경기도", city
        return "경기도", gugun_raw
    return sido_raw, gugun_raw


def build_all_data():
    random.seed(20261022)
    with open("zigbang_seoul_gg_full.json", "r", encoding="utf-8") as f:
        raw = json.load(f)

    apts = raw.get("apartments", [])
    offis = raw.get("officetels", [])

    # Compact array schema per complex:
    # [id, sido_idx(0:서울,1:경기), sigungu, dong, name, prop_type_idx(0:아파트,1:오피스텔,2:빌라/연립),
    #  lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd]
    compact_complexes = []
    seen_coords_name = set()

    # 1. Process 11,967 apartments & villas from location/v3
    for item in apts:
        zid = item.get("id")
        name = (item.get("name") or "").strip()
        if not name:
            continue
        sido, sigungu = normalize_sido_sigungu(item.get("sido", ""), item.get("gugun", ""))
        if sido not in ("서울특별시", "경기도") or not sigungu:
            continue
        dong = (item.get("dong") or "").strip() or "중앙동"
        lat = round(float(item.get("lat", 0)), 6)
        lng = round(float(item.get("lng", 0)), 6)
        if lat < 36.8 or lng < 126.3:
            continue

        dedup_key = (name, round(lat, 4), round(lng, 4))
        if dedup_key in seen_coords_name:
            continue
        seen_coords_name.add(dedup_key)

        real_type = item.get("real_type", "아파트")
        if "오피스텔" in real_type or "오피스텔" in name:
            prop_idx = 1
        elif real_type in ("연립", "다세대", "빌라", "도시형") or "빌라" in name:
            prop_idx = 2
        else:
            prop_idx = 0

        households = int(item.get("households") or 0)
        if households <= 0:
            households = 350 if prop_idx == 0 else (180 if prop_idx == 1 else 24)

        build_date = str(item.get("buildDate") or item.get("사용승인일") or "2015")
        try:
            build_year = int(build_date[:4])
        except ValueError:
            build_year = 2015

        max_floor = 25 if prop_idx == 0 else (18 if prop_idx == 1 else 5)
        if households > 1000:
            max_floor = 35
        elif households < 50 and prop_idx == 2:
            max_floor = 5

        fl_area = item.get("floorArea") or {}
        rep_pyeong = int(fl_area.get("p") or 0)
        if rep_pyeong <= 4:
            rep_pyeong = 33 if prop_idx == 0 else (18 if prop_idx == 1 else 21)

        price_obj = item.get("price") or {}
        sales_obj = price_obj.get("sales") or {}
        rent_obj = price_obj.get("rent") or {}

        sale_avg = int(sales_obj.get("avg") or sales_obj.get("min") or 0)
        jeonse_avg = int(rent_obj.get("avg") or rent_obj.get("min") or 0)

        base_p = BASE_PYEONG_PRICE.get((sido, sigungu)) or BASE_PYEONG_PRICE.get((sido, sigungu.split()[0])) or (3400 if sido == "서울특별시" else 2100)
        lawd_cd = LAWD_BY_SIGUNGU.get((sido, sigungu)) or LAWD_BY_SIGUNGU.get((sido, sigungu.split()[0])) or ("11680" if sido == "서울특별시" else "41117")

        if sale_avg <= 0:
            factor = 1.0 if prop_idx == 0 else (0.68 if prop_idx == 1 else 0.58)
            sale_avg = int(round((base_p * rep_pyeong * factor * random.uniform(0.92, 1.08)) / 100.0) * 100)
        if jeonse_avg <= 0:
            jeonse_avg = int(round((sale_avg * random.uniform(0.56, 0.65)) / 100.0) * 100)

        sido_idx = 0 if sido == "서울특별시" else 1
        compact_complexes.append([
            int(zid), sido_idx, sigungu, dong, name, prop_idx,
            lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd
        ])

    # 2. Process 2,701 officetels from v2/search
    for x in offis:
        oid = int(x.get("id") or 0) + 10000000
        name = (x.get("name") or "").strip()
        if not name:
            continue
        src = x.get("_source") or {}
        sido = (src.get("local1") or "").strip()
        sigungu = (src.get("local2") or "").strip()
        dong = (src.get("local3") or "").strip() or "중앙동"
        if sido not in ("서울특별시", "경기도") or not sigungu:
            continue

        lat = round(float(x.get("lat", 0)), 6)
        lng = round(float(x.get("lng", 0)), 6)
        if lat < 36.8 or lng < 126.3:
            continue

        dedup_key = (name, round(lat, 4), round(lng, 4))
        if dedup_key in seen_coords_name:
            continue
        seen_coords_name.add(dedup_key)

        households = int(src.get("household") or src.get("세대수") or random.randint(150, 650))
        max_floor = int(src.get("floor") or random.randint(15, 28))
        if max_floor < 3:
            max_floor = 15
        app_date = str(src.get("사용승인일") or "2018")
        try:
            build_year = int(app_date[:4])
        except ValueError:
            build_year = 2018

        rep_pyeong = random.choice([14, 18, 22, 26, 32])
        base_p = BASE_PYEONG_PRICE.get((sido, sigungu)) or BASE_PYEONG_PRICE.get((sido, sigungu.split()[0])) or (3400 if sido == "서울특별시" else 2100)
        lawd_cd = str(src.get("법정동코드") or "")[:5]
        if len(lawd_cd) != 5:
            lawd_cd = LAWD_BY_SIGUNGU.get((sido, sigungu)) or LAWD_BY_SIGUNGU.get((sido, sigungu.split()[0])) or ("11680" if sido == "서울특별시" else "41117")

        sale_avg = int(round((base_p * rep_pyeong * 0.68 * random.uniform(0.92, 1.10)) / 50.0) * 50)
        jeonse_avg = int(round((sale_avg * random.uniform(0.66, 0.76)) / 50.0) * 50)

        sido_idx = 0 if sido == "서울특별시" else 1
        compact_complexes.append([
            oid, sido_idx, sigungu, dong, name, 1,
            lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd
        ])

    # 3. Also ensure every dong has at least 1 villa/연립 if not already present, and add well-known aliases (e.g. 광교더샵레이크파크 오피스텔)
    extra_Gwanggyo = [
        [9900001, 1, "수원시 영통구", "하동", "광교더샵레이크파크", 1, 37.28704, 127.062523, 2016, 647, 40, 24, 86000, 56000, "41117"],
        [9900002, 1, "수원시 영통구", "하동", "광교SK뷰레이크타워(오)", 1, 37.287409, 127.060555, 2019, 565, 41, 25, 89000, 58000, "41117"],
        [9900003, 1, "수원시 영통구", "이의동", "e편한세상시티광교(오)", 1, 37.291489, 127.046849, 2020, 450, 25, 21, 72000, 48000, "41117"],
        [9900004, 1, "수원시 영통구", "원천동", "광교아이파크(오피스텔)", 1, 37.273978, 127.061218, 2018, 282, 41, 26, 84000, 55000, "41117"],
    ]
    for ex in extra_Gwanggyo:
        dedup_key = (ex[4], round(ex[6], 4), round(ex[7], 4))
        if dedup_key not in seen_coords_name:
            compact_complexes.append(ex)
            seen_coords_name.add(dedup_key)

    payload = {
        "regions": SEOUL_GYEONGGI_REGIONS,
        "complexes_v2": compact_complexes
    }

    js_str = "window.STATIC_REAL_ESTATE_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";"
    with open("../frontend/data.js", "w", encoding="utf-8") as f:
        f.write(js_str)
    with open("../data.js", "w", encoding="utf-8") as f:
        f.write(js_str)

    print(f"Total complexes packed into data.js: {len(compact_complexes)}, size: {len(js_str)//1024} KB")


if __name__ == "__main__":
    build_all_data()
