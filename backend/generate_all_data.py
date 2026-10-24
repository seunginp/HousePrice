# -*- coding: utf-8 -*-
import json
import random
from datetime import datetime
from regions_data import SEOUL_GYEONGGI_REGIONS

# 지역별 기본 평당가 룩업
BASE_PYEONG_PRICE = {}
LAWD_BY_SIGUNGU = {}
for r in SEOUL_GYEONGGI_REGIONS:
    BASE_PYEONG_PRICE[(r["sido"], r["sigungu"])] = r["base_pyeong_price"]
    LAWD_BY_SIGUNGU[(r["sido"], r["sigungu"])] = r["lawd_cd"]
    city_prefix = r["sigungu"].split()[0]
    if (r["sido"], city_prefix) not in BASE_PYEONG_PRICE:
        BASE_PYEONG_PRICE[(r["sido"], city_prefix)] = r["base_pyeong_price"]
        LAWD_BY_SIGUNGU[(r["sido"], city_prefix)] = r["lawd_cd"]

# 분양가상한제 적용 지역 (강남구, 서초구, 송파구, 용산구 및 공공택지)
PRICE_CAP_SIGUNGU = {"강남구", "서초구", "송파구", "용산구", "과천시", "하남시", "성남시 수정구"}
PUBLIC_KEYWORDS = ["A-", "B-", "S-", "BL", "블록", "블럭", "토지임대", "신혼희망", "공공", "자연앤", "왕숙", "교산", "창릉", "대장", "고덕", "거모", "당수", "법조타운", "역세권"]
REDEV_KEYWORDS = ["재건축", "재개발", "정비", "구역", "리모델링", "가로주택"]


def normalize_sido_sigungu(sido_raw: str, gugun_raw: str):
    sido_raw = (sido_raw or "").strip()
    gugun_raw = (gugun_raw or "").strip()
    if sido_raw.startswith("서울"):
        return "서울특별시", gugun_raw
    if sido_raw.startswith("경기"):
        parts = sido_raw.split()
        if len(parts) >= 2:
            city = parts[1]
            if gugun_raw and gugun_raw != city:
                return "경기도", f"{city} {gugun_raw}"
            return "경기도", city
        return "경기도", gugun_raw
    return sido_raw, gugun_raw


def format_yyyymm(raw_val, default_val="2026.12 예정"):
    if not raw_val:
        return default_val
    s = str(raw_val).strip()
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    elif len(s) == 6:
        return f"{s[:4]}-{s[4:6]}"
    return s


def get_complex_pyeongs(name, prop_idx, households, rep_p, verified_reg):
    match = verified_reg.get(name)
    if not match:
        for k, v in verified_reg.items():
            if k in name or name in k:
                match = v
                break
    if match and match.get('pyeongs'):
        clean_ints = []
        for p in match['pyeongs']:
            try:
                val = int(str(p).replace('평', '').replace('A','').replace('B','').replace('C','').replace('D','').strip())
                if val not in clean_ints and val > 0:
                    clean_ints.append(val)
            except Exception:
                pass
        if clean_ints:
            return sorted(clean_ints)

    rp = rep_p or 33
    if prop_idx == 1:  # 오피스텔
        if rp <= 15:
            return [10, 14, 18]
        elif rp <= 22:
            return [15, 19, 24]
        else:
            return sorted(list(set([21, rp, rp + 7])))
    elif prop_idx == 2:  # 빌라/연립
        return sorted(list(set([max(14, rp - 6), rp, rp + 5])))
    else:  # 아파트
        if households >= 1000:
            if rp >= 45:
                return [34, 42, 45, 52, 54, 62]
            elif rp <= 25:
                return [18, 22, 25, 33, 42]
            else:
                base_mid = 35 if rp >= 34 else 33
                return [25, base_mid, 42, 45, 54]
        elif households >= 500:
            if rp >= 42:
                return [34, 42, 45, 52]
            elif rp <= 25:
                return [21, 25, 33]
            else:
                base_mid = 35 if rp >= 34 else 33
                return [25, base_mid, 42, 45]
        elif households >= 200:
            base_mid = 35 if rp >= 34 else (33 if rp >= 30 else rp)
            if rp <= 25:
                return [21, 25, 32]
            else:
                return [25, base_mid, 42]
        else:
            if rp <= 25:
                return [22, rp]
            else:
                return [25, rp, rp + 9]


def build_all_data():
    random.seed(20261022)
    verified_reg = {}
    v_path = "verified_hogang_registry.json"
    if os.path.exists(v_path):
        try:
            with open(v_path, "r", encoding="utf-8") as vf:
                verified_reg = json.load(vf)
        except Exception:
            pass

    with open("zigbang_seoul_gg_full.json", "r", encoding="utf-8") as f:
        raw = json.load(f)
        raw = json.load(f)

    apts = raw.get("apartments", [])
    offis = raw.get("officetels", [])

    # Compact array schema per complex:
    # [id, sido_idx(0:서울,1:경기), sigungu, dong, name, prop_type_idx(0:아파트,1:오피스텔,2:빌라/연립),
    #  lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd]
    compact_complexes = []
    subscriptions = []
    seen_coords_name = set()

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

        raw_max_floor = item.get('maxFloor') or item.get('최고층수') or item.get('max_floor')
        if raw_max_floor and int(raw_max_floor) > 0:
            max_floor = int(raw_max_floor)
        else:
            max_floor = 25 if prop_idx == 0 else (18 if prop_idx == 1 else 5)
            if households > 1500:
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
        offer_obj = price_obj.get("offer") or {}

        sale_avg = int(sales_obj.get("avg") or sales_obj.get("min") or 0)
        jeonse_avg = int(rent_obj.get("avg") or rent_obj.get("min") or 0)
        offer_avg = int(offer_obj.get("avg") or offer_obj.get("min") or 0)

        base_p = BASE_PYEONG_PRICE.get((sido, sigungu)) or BASE_PYEONG_PRICE.get((sido, sigungu.split()[0])) or (3400 if sido == "서울특별시" else 2100)
        lawd_cd = LAWD_BY_SIGUNGU.get((sido, sigungu)) or LAWD_BY_SIGUNGU.get((sido, sigungu.split()[0])) or ("11680" if sido == "서울특별시" else "41117")

        if sale_avg <= 0:
            if offer_avg > 0:
                sale_avg = offer_avg
            else:
                factor = 1.0 if prop_idx == 0 else (0.68 if prop_idx == 1 else 0.58)
                sale_avg = int(round((base_p * rep_pyeong * factor * random.uniform(0.92, 1.08)) / 100.0) * 100)
        if jeonse_avg <= 0:
            jeonse_avg = int(round((sale_avg * random.uniform(0.56, 0.65)) / 100.0) * 100)

        # Check verified registry for real max_floor
        v_match = verified_reg.get(name)
        if not v_match:
            for k, v in verified_reg.items():
                if k in name or name in k:
                    v_match = v
                    break
        if v_match and v_match.get("max_floor"):
            max_floor = v_match["max_floor"]

        pyeongs = get_complex_pyeongs(name, prop_idx, households, rep_pyeong, verified_reg)

        sido_idx = 0 if sido == "서울특별시" else 1
        compact_complexes.append([
            int(zid), sido_idx, sigungu, dong, name, prop_idx,
            lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd, pyeongs
        ])

        # 청약/분양 단지 추출 ('청약중', '분양임박', '분양예정', '사전청약마감', '입주예정', '청약마감')
        svc_status = item.get("서비스구분")
        if svc_status in ("청약중", "분양임박", "분양예정", "사전청약마감", "입주예정", "청약마감"):
            is_public = any(k in name for k in PUBLIC_KEYWORDS)
            is_redev = any(k in name for k in REDEV_KEYWORDS)
            if is_public:
                supply_type = "공공분양·뉴홈(택지)"
            elif is_redev:
                supply_type = "정비사업(재건축·재개발)"
            else:
                supply_type = "민간분양"

            is_price_cap = (sigungu in PRICE_CAP_SIGUNGU) or is_public

            # 주변 33평(또는 대표평형) 시세 추정
            market_price = int(round((base_p * rep_pyeong * random.uniform(0.98, 1.08)) / 100.0) * 100)
            if offer_avg > 0:
                est_offer = offer_avg
                is_confirmed_price = True
            else:
                # 분양가상한제 적용 시 시세 대비 72~82%, 일반 민간분양은 88~96% 수준 예상 분양가 산출
                discount_ratio = random.uniform(0.72, 0.82) if is_price_cap else random.uniform(0.88, 0.95)
                est_offer = int(round((market_price * discount_ratio) / 100.0) * 100)
                is_confirmed_price = False

            if market_price < est_offer:
                market_price = int(round((est_offer * (1.22 if is_price_cap else 1.08)) / 100.0) * 100)

            safety_margin = max(0, market_price - est_offer)
            offer_pyeong_price = max(500, int(round(est_offer / rep_pyeong)))

            raw_presale_ym = item.get("분양년월")
            if svc_status == "청약중":
                schedule_str = format_yyyymm(raw_presale_ym, "2026-10 (청약접수중)")
            elif svc_status == "분양임박":
                schedule_str = format_yyyymm(raw_presale_ym, "2026-11 (분양임박)")
            elif svc_status == "분양예정":
                schedule_str = format_yyyymm(raw_presale_ym, "2026 하반기~2027 예정")
            else:
                schedule_str = format_yyyymm(raw_presale_ym, "모집완료/입주예정")

            move_in_str = format_yyyymm(item.get("사용승인일"), "2028~2029년 예정")
            gen_households = max(20, int(round(households * (0.38 if is_redev else 0.65))))

            subscriptions.append({
                "id": int(zid),
                "sido": sido,
                "sigungu": sigungu,
                "dong": dong,
                "name": name,
                "status": svc_status,
                "supply_type": supply_type,
                "price_cap": is_price_cap,
                "lat": lat,
                "lng": lng,
                "households": households,
                "general_supply": gen_households,
                "rep_pyeong": rep_pyeong,
                "offer_price": est_offer,
                "is_confirmed_price": is_confirmed_price,
                "offer_pyeong_price": offer_pyeong_price,
                "market_price": market_price,
                "safety_margin": safety_margin,
                "schedule": schedule_str,
                "move_in": move_in_str,
                "brand": item.get("brand") or ("현대건설" if "디에이치" in name or "힐스테이트" in name else ("삼성물산" if "래미안" in name else ("GS건설" if "자이" in name else "메이저시공사")))
            })

    # Process 2,701 officetels
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

    # 청약 우선순위 정렬 (청약중 -> 분양임박 -> 분양예정 -> 사전청약 -> 입주예정)
    status_order = {"청약중": 0, "분양임박": 1, "분양예정": 2, "사전청약마감": 3, "입주예정": 4, "청약마감": 5}
    subscriptions.sort(key=lambda x: (status_order.get(x["status"], 9), -x["safety_margin"]))

    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {
        "updated_at": today_str,
        "regions": SEOUL_GYEONGGI_REGIONS,
        "complexes_v2": compact_complexes,
        "subscriptions": subscriptions
    }

    # Build clean Hogang preset
    clean_preset = {}
    for k, v in verified_reg.items():
        if v and v.get("name"):
            c_name = v["name"]
            if c_name not in clean_preset:
                clean_preset[c_name] = {
                    "id": v.get("hogang_id"),
                    "max_floor": v.get("max_floor"),
                    "min_floor": v.get("min_floor"),
                    "households": v.get("households"),
                    "total_dong": v.get("total_dong"),
                    "pyeongs": v.get("pyeongs"),
                    "recent_price": v.get("recent_price"),
                    "pyeong_price": v.get("pyeong_price"),
                    "url": v.get("url")
                }
            if k != c_name and k not in clean_preset:
                clean_preset[k] = clean_preset[c_name]

    js_str = "window.STATIC_REAL_ESTATE_DATA = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n\n"
    js_str += "window.HOGANGNONO_PRESET_DATA = " + json.dumps(clean_preset, ensure_ascii=False) + ";\n"
    with open("../frontend/data.js", "w", encoding="utf-8") as f:
        f.write(js_str)
    with open("../data.js", "w", encoding="utf-8") as f:
        f.write(js_str)

    print(f"Total complexes: {len(compact_complexes)}, Subscriptions: {len(subscriptions)}, size: {len(js_str)//1024} KB")


if __name__ == "__main__":
    build_all_data()
