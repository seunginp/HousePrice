# -*- coding: utf-8 -*-
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def collect_all_seoul_gyeonggi():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    # 1. Build 0.10 x 0.12 degree grid covering all of Seoul & Gyeonggi-do (lat 36.90~38.10, lng 126.55~127.75)
    tiles = []
    lat = 36.90
    while lat < 38.10:
        lng = 126.55
        while lng < 127.75:
            tiles.append((round(lat, 3), round(lat + 0.10, 3), round(lng, 3), round(lng + 0.12, 3)))
            lng += 0.12
        lat += 0.10

    print(f"Scanning {len(tiles)} grid tiles across Seoul & Gyeonggi-do...")
    complexes_by_id = {}

    def fetch_tile(t):
        s, n, w, e = t
        url = f"https://apis.zigbang.com/property/apartments/location/v3?e={e}&n={n}&s={s}&w={w}"
        for _ in range(3):
            try:
                r = session.get(url, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    return data.get("filtered", []) + data.get("unfiltered", [])
            except Exception:
                time.sleep(0.2)
        return []

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(fetch_tile, t) for t in tiles]
        for f in as_completed(futures):
            for item in f.result():
                cid = f"apt_{item.get('id')}"
                sido_raw = str(item.get("sido", ""))
                if not ("서울" in sido_raw or "경기" in sido_raw):
                    continue
                complexes_by_id[cid] = item

    print(f"Collected {len(complexes_by_id)} apartments & villas from location/v3 grid!")

    # 2. Collect officetels across Seoul & Gyeonggi-do
    # Extract all unique dong names + major area/brand keywords
    dong_names = set()
    for item in complexes_by_id.values():
        d = item.get("dong")
        if d:
            dong_names.add(d)
            if d.endswith("동") or d.endswith("읍") or d.endswith("면"):
                dong_names.add(d[:-1])

    extra_keywords = [
        "광교", "판교", "분당", "일산", "동탄", "마곡", "여의도", "강남", "서초", "송파", "잠실",
        "역삼", "선릉", "논현", "신사", "압구정", "청담", "마포", "공덕", "홍대", "신촌", "구로",
        "가산", "영등포", "당산", "종로", "광화문", "을지로", "충무로", "성수", "건대", "왕십리",
        "청량리", "천호", "길동", "미사", "하남", "위례", "수원", "인계", "광명", "안양", "평촌",
        "인덕원", "범계", "산본", "부천", "중동", "상동", "김포", "운정", "파주", "별내", "다산",
        "구리", "의정부", "평택", "고덕", "지제", "안산", "고잔", "배곧", "시흥", "기흥", "수지",
        "죽전", "오피스텔", "타워", "시티", "스테이트", "자이", "푸르지오", "아이파크", "더샵",
        "롯데캐슬", "센트럴", "파크", "빌", "하우스", "스위트", "플래티넘", "아크로", "포레나",
        "디오빌", "대우", "현대", "삼성", "효성", "SK", "두산", "위브", "해링턴", "리버", "레이크",
        "스카이", "팰리스", "프라자", "밸리", "더리브", "엘포트", "월드마크", "에비뉴", "어반", "메트로"
    ]
    search_queries = sorted(dong_names.union(extra_keywords))
    print(f"Scanning {len(search_queries)} queries for Officetels in Seoul & Gyeonggi...")

    officetels_by_id = {}

    def fetch_offi(q):
        url = f"https://apis.zigbang.com/v2/search?leaseYn=N&q={q}&serviceType=오피스텔"
        try:
            r = session.get(url, timeout=8)
            if r.status_code == 200:
                return [x for x in r.json().get("items", []) if x.get("type") == "officetel"]
        except Exception:
            pass
        return []

    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = [ex.submit(fetch_offi, q) for q in search_queries]
        for f in as_completed(futures):
            for x in f.result():
                src = x.get("_source", {})
                loc1 = str(src.get("local1", ""))
                if loc1 not in ("서울특별시", "경기도"):
                    continue
                oid = f"offi_{x.get('id')}"
                officetels_by_id[oid] = x

    print(f"Collected {len(officetels_by_id)} officetels in Seoul & Gyeonggi!")

    with open("zigbang_seoul_gg_full.json", "w", encoding="utf-8") as f:
        json.dump({
            "apartments": list(complexes_by_id.values()),
            "officetels": list(officetels_by_id.values())
        }, f, ensure_ascii=False)
    print("Saved zigbang_seoul_gg_full.json successfully!")

if __name__ == "__main__":
    collect_all_seoul_gyeonggi()
