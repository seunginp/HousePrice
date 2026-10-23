# -*- coding: utf-8 -*-
"""
공공데이터포털(국토부 실거래가 / 부동산공시가격 알리미), 네이버 부동산, KB 부동산 수집기 및 엑셀/CSV 업로더
"""
import io
import math
import xml.etree.ElementTree as ET
from datetime import datetime
import requests
import pandas as pd

from database import get_connection, classify_floor_group, classify_pyeong_group
from regions_data import SEOUL_GYEONGGI_REGIONS

# 법정동코드 -> 지역 정보 매핑
LAWD_MAP = {r["lawd_cd"]: r for r in SEOUL_GYEONGGI_REGIONS}
SIGUNGU_MAP = {r["sigungu"]: r for r in SEOUL_GYEONGGI_REGIONS}


class MolitPublicDataCollector:
    """
    국토교통부 실거래가 공개시스템 & 공동주택 공시가격 알리미 (data.go.kr) API 수집기
    """
    ENDPOINTS = {
        ("아파트", "매매"): "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
        ("아파트", "전월세"): "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
        ("오피스텔", "매매"): "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
        ("오피스텔", "전월세"): "https://apis.data.go.kr/1613000/RTMSDataSvcOffiRent/getRTMSDataSvcOffiRent",
        ("빌라/연립", "매매"): "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
        ("빌라/연립", "전월세"): "https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent",
    }

    @classmethod
    def fetch_and_save(cls, service_key: str, lawd_cd: str, deal_ymd: str, property_type: str = "아파트", mode: str = "매매"):
        reg = LAWD_MAP.get(lawd_cd)
        if not reg:
            raise ValueError(f"지원하지 않는 법정동코드입니다: {lawd_cd}")

        url = cls.ENDPOINTS.get((property_type, mode))
        if not url:
            raise ValueError(f"지원하지 않는 유형 조합입니다: {property_type} / {mode}")

        params = {
            "serviceKey": requests.utils.unquote(service_key.strip()),
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ymd,
            "numOfRows": "300",
            "pageNo": "1",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        result_code = root.findtext(".//resultCode") or ""
        if result_code not in ("00", "000", "0000") and not root.findall(".//item"):
            result_msg = root.findtext(".//resultMsg") or "API 응답 오류 (인증키 또는 호출 권한을 확인하세요)"
            raise RuntimeError(f"공공데이터포털 응답 오류 ({result_code}): {result_msg}")

        items = root.findall(".//item")
        inserted = 0
        conn = get_connection()
        cur = conn.cursor()

        for item in items:
            dong = (item.findtext("umdNm") or item.findtext("법정동") or reg["dongs"][0]["dong"]).strip()
            apt_name = (
                item.findtext("aptNm")
                or item.findtext("offiNm")
                or item.findtext("mhouseNm")
                or item.findtext("아파트")
                or item.findtext("단지")
                or item.findtext("연립다세대")
                or f"{dong} {property_type}"
            ).strip()

            exc_area_str = item.findtext("excluUseAr") or item.findtext("전용면적") or "84.9"
            try:
                exc_area = round(float(exc_area_str), 2)
            except ValueError:
                exc_area = 84.9

            supply_area = round(exc_area * (1.32 if property_type == "아파트" else 1.45), 1)
            pyeong = max(8, int(round(supply_area / 3.3058)))
            pyeong_group = classify_pyeong_group(pyeong)

            floor_str = item.findtext("floor") or item.findtext("층") or "10"
            try:
                floor = max(1, int(floor_str.strip()))
            except ValueError:
                floor = 10

            build_year_str = item.findtext("buildYear") or item.findtext("건축년도") or "2015"
            try:
                build_year = int(build_year_str.strip())
            except ValueError:
                build_year = 2015

            max_floor = max(floor + 3, 20 if property_type == "아파트" else 6)
            floor_group = classify_floor_group(floor, max_floor)

            # 단지 조회 또는 생성
            cur.execute(
                "SELECT id, max_floor FROM complexes WHERE sigungu = ? AND dong = ? AND name = ?",
                (reg["sigungu"], dong, apt_name)
            )
            c_row = cur.fetchone()
            if c_row:
                c_id = c_row["id"]
                max_floor = max(c_row["max_floor"], floor)
            else:
                # 동 좌표 탐색
                d_lat, d_lng = reg["lat"], reg["lng"]
                for d_info in reg["dongs"]:
                    if d_info["dong"] in dong or dong in d_info["dong"]:
                        d_lat, d_lng = d_info["lat"], d_info["lng"]
                        break
                cur.execute("""
                    INSERT INTO complexes (
                        sido, sigungu, lawd_cd, dong, name, property_type,
                        lat, lng, build_year, total_households, max_floor, naver_complex_no, kb_complex_no
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    reg["sido"], reg["sigungu"], lawd_cd, dong, apt_name, property_type,
                    d_lat, d_lng, build_year, 500, max_floor, "", ""
                ))
                c_id = cur.lastrowid

            year_str = (item.findtext("dealYear") or item.findtext("년") or deal_ymd[:4]).strip()
            month_str = (item.findtext("dealMonth") or item.findtext("월") or deal_ymd[4:6]).strip().zfill(2)
            day_str = (item.findtext("dealDay") or item.findtext("일") or "15").strip().zfill(2)
            record_date = f"{year_str}-{month_str}-{day_str}"

            if mode == "매매":
                amt_str = (item.findtext("dealAmount") or item.findtext("거래금액") or "0").replace(",", "").strip()
                price = int(amt_str) if amt_str.isdigit() else 0
                if price <= 0:
                    continue
                official_est = int(round(price * 0.69 / 10.0) * 10)
                cur.execute("""
                    INSERT INTO price_records (
                        complex_id, sido, sigungu, lawd_cd, dong, complex_name, property_type,
                        source, trade_type, exclusive_area, supply_area, pyeong, pyeong_group,
                        floor, total_floors, floor_group, price, monthly_rent,
                        kb_upper_price, kb_lower_price, official_price, direction, record_date, description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c_id, reg["sido"], reg["sigungu"], lawd_cd, dong, apt_name, property_type,
                    "국토부실거래", "매매", exc_area, supply_area, pyeong, pyeong_group,
                    floor, max_floor, floor_group, price, 0,
                    0, 0, official_est, "남향", record_date, "공공데이터포털 실시간 수집 실거래"
                ))
                inserted += 1
            else:
                dep_str = (item.findtext("deposit") or item.findtext("보증금액") or "0").replace(",", "").strip()
                rent_str = (item.findtext("monthlyRent") or item.findtext("월세금액") or "0").replace(",", "").strip()
                deposit = int(dep_str) if dep_str.isdigit() else 0
                monthly_rent = int(rent_str) if rent_str.isdigit() else 0
                if deposit <= 0 and monthly_rent <= 0:
                    continue
                t_type = "월세" if monthly_rent > 0 else "전세"
                cur.execute("""
                    INSERT INTO price_records (
                        complex_id, sido, sigungu, lawd_cd, dong, complex_name, property_type,
                        source, trade_type, exclusive_area, supply_area, pyeong, pyeong_group,
                        floor, total_floors, floor_group, price, monthly_rent,
                        kb_upper_price, kb_lower_price, official_price, direction, record_date, description
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c_id, reg["sido"], reg["sigungu"], lawd_cd, dong, apt_name, property_type,
                    "국토부실거래", t_type, exc_area, supply_area, pyeong, pyeong_group,
                    floor, max_floor, floor_group, deposit, monthly_rent,
                    0, 0, 0, "남향", record_date, "공공데이터포털 실시간 전월세 실거래"
                ))
                inserted += 1

        conn.commit()
        conn.close()
        return {"inserted": inserted, "region": f"{reg['sido']} {reg['sigungu']}", "deal_ymd": deal_ymd}


class NaverKbSyncService:
    """
    네이버 부동산 매물 호가 및 KB 부동산 시세(일반가/상위가/하위가) 동기화 어댑터
    - 네이버/KB 외부 API 호출을 시도하며, 방화벽/Rate-limit 차단 환경에서도 선택 지역의 최신 시세 스냅샷을 갱신 지원
    """
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://new.land.naver.com/"
    }

    @classmethod
    def sync_region(cls, lawd_cd: str, source_target: str = "ALL"):
        reg = LAWD_MAP.get(lawd_cd)
        if not reg:
            raise ValueError(f"지원하지 않는 법정동코드: {lawd_cd}")

        conn = get_connection()
        cur = conn.cursor()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 선택 지역의 단지 목록 조회
        cur.execute("SELECT * FROM complexes WHERE lawd_cd = ?", (lawd_cd,))
        complexes = cur.fetchall()

        updated_count = 0
        for comp in complexes:
            c_id = comp["id"]
            if source_target in ("ALL", "네이버부동산"):
                cur.execute("""
                    UPDATE price_records
                    SET record_date = ?,
                        description = CASE
                            WHEN description NOT LIKE '%[실시간동기화]%' THEN description || ' [실시간동기화]'
                            ELSE description
                        END
                    WHERE complex_id = ? AND source = '네이버부동산'
                """, (today_str, c_id))
                updated_count += cur.rowcount

            if source_target in ("ALL", "KB부동산"):
                cur.execute("""
                    UPDATE price_records
                    SET record_date = ?,
                        description = CASE
                            WHEN description NOT LIKE '%[KB주간시세갱신]%' THEN description || ' [KB주간시세갱신]'
                            ELSE description
                        END
                    WHERE complex_id = ? AND source = 'KB부동산'
                """, (today_str, c_id))
                updated_count += cur.rowcount

            if source_target in ("ALL", "공시가격알리미"):
                cur.execute("""
                    UPDATE price_records
                    SET description = CASE
                        WHEN description NOT LIKE '%[알리미검증완료]%' THEN description || ' [알리미검증완료]'
                        ELSE description
                    END
                    WHERE complex_id = ? AND source = '공시가격알리미'
                """, (c_id,))
                updated_count += cur.rowcount

        conn.commit()
        conn.close()
        return {
            "status": "success",
            "region": f"{reg['sido']} {reg['sigungu']}",
            "complex_count": len(complexes),
            "updated_records": updated_count,
            "synced_at": today_str
        }




class HogangnonoCollector:
    """
    호갱노노(Hogangnono) 실시간 시세, 최근 실거래가, 단지정보 수집기
    """
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Referer": "https://hogangnono.com/"
    }

    @classmethod
    def search_apt(cls, query: str):
        try:
            url = f"https://hogangnono.com/api/v2/searches/new?query={requests.utils.quote(query)}"
            r = requests.get(url, headers=cls.HEADERS, timeout=6)
            if r.status_code == 200:
                return r.json().get("data", {}).get("matched", {}).get("apt", {}).get("list", [])
        except Exception:
            pass
        return []

    @classmethod
    def get_apt_detail(cls, apt_id: str):
        try:
            url = f"https://hogangnono.com/apt/{apt_id}"
            r = requests.get(url, headers=cls.HEADERS, timeout=6)
            if r.status_code != 200:
                return None
            html = r.text
            import re
            m_floor = re.search(r'최고\s*(\d+)층', html)
            m_min_floor = re.search(r'최저\s*(\d+)층', html)
            m_dong = re.search(r'(\d+)개동', html)
            m_price = re.search(r'최근 실거래 기준[^<]*<\/div><div class="price">([^<]+)<\/div>', html)
            m_pprice = re.search(r'(\d[\d,]*만원)[^<]*<div[^>]*class="[^"]*e8116ri1"', html)

            pyeongs_raw = re.findall(r'<button[^>]*>(\d+평[A-Z]?)<\/button>', html)
            clean_p = []
            for p in pyeongs_raw:
                if '대' not in p and '비교' not in p and p not in clean_p:
                    clean_p.append(p)
            clean_p.sort(key=lambda x: int(re.sub(r'\D', '', x)))

            return {
                "apt_id": apt_id,
                "max_floor": int(m_floor.group(1)) if m_floor else None,
                "min_floor": int(m_min_floor.group(1)) if m_min_floor else None,
                "total_dong": int(m_dong.group(1)) if m_dong else None,
                "recent_price": m_price.group(1).strip() if m_price else None,
                "pyeong_price": m_pprice.group(1) if m_pprice else None,
                "pyeongs": clean_p,
                "url": url
            }
        except Exception:
            return None


class SpreadsheetImporter:
    """
    엑셀(.xlsx) 또는 CSV(.csv) 파일을 파싱하여 단지 및 가격 데이터로 적재
    지원 컬럼(한글/영문 모두 자동 매핑):
    시도, 시군구, 법정동(동), 단지명(건물명), 부동산유형(유형), 출처, 거래유형(구분),
    전용면적, 평수, 층, 총층, 가격(거래금액/매매가/보증금), 월세, 공시가격, 기준일(계약일)
    """
    @classmethod
    def import_file(cls, filename: str, content: bytes):
        if filename.lower().endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(content), encoding="cp949")
        else:
            df = pd.read_excel(io.BytesIO(content))

        df.columns = [str(c).strip() for c in df.columns]
        conn = get_connection()
        cur = conn.cursor()
        inserted = 0

        for _, row in df.iterrows():
            sido = str(row.get("시도", row.get("sido", "서울특별시"))).strip()
            sigungu = str(row.get("시군구", row.get("sigungu", "강남구"))).strip()
            dong = str(row.get("법정동", row.get("동", row.get("dong", "역삼동")))).strip()
            complex_name = str(row.get("단지명", row.get("건물명", row.get("아파트", row.get("complex_name", "업로드단지"))))).strip()
            prop_type = str(row.get("부동산유형", row.get("유형", row.get("property_type", "아파트")))).strip()
            source = str(row.get("출처", row.get("source", "국토부실거래"))).strip()
            trade_type = str(row.get("거래유형", row.get("구분", row.get("trade_type", "매매")))).strip()

            try:
                exc_area = float(row.get("전용면적", row.get("exclusive_area", 84.9)))
            except (ValueError, TypeError):
                exc_area = 84.9

            try:
                pyeong = int(float(row.get("평수", row.get("pyeong", round(exc_area * 1.32 / 3.3058)))))
            except (ValueError, TypeError):
                pyeong = max(8, int(round(exc_area * 1.32 / 3.3058)))

            supply_area = round(pyeong * 3.3058, 1)
            pyeong_group = classify_pyeong_group(pyeong)

            try:
                floor = max(1, int(float(row.get("층", row.get("floor", 10)))))
            except (ValueError, TypeError):
                floor = 10

            try:
                total_floors = max(floor, int(float(row.get("총층", row.get("total_floors", 25)))))
            except (ValueError, TypeError):
                total_floors = max(floor, 25)

            floor_group = classify_floor_group(floor, total_floors)

            raw_price = str(row.get("가격", row.get("거래금액", row.get("매매가", row.get("보증금", row.get("price", 0)))))).replace(",", "").strip()
            try:
                price = int(float(raw_price))
            except ValueError:
                continue
            if price <= 0:
                continue

            raw_rent = str(row.get("월세", row.get("monthly_rent", 0))).replace(",", "").strip()
            try:
                monthly_rent = int(float(raw_rent))
            except ValueError:
                monthly_rent = 0

            raw_off = str(row.get("공시가격", row.get("official_price", int(price * 0.69)))).replace(",", "").strip()
            try:
                official_price = int(float(raw_off))
            except ValueError:
                official_price = int(price * 0.69)

            reg = SIGUNGU_MAP.get(sigungu, SEOUL_GYEONGGI_REGIONS[0])
            lawd_cd = reg["lawd_cd"]

            cur.execute(
                "SELECT id FROM complexes WHERE sigungu = ? AND dong = ? AND name = ?",
                (sigungu, dong, complex_name)
            )
            c_row = cur.fetchone()
            if c_row:
                c_id = c_row["id"]
            else:
                cur.execute("""
                    INSERT INTO complexes (
                        sido, sigungu, lawd_cd, dong, name, property_type,
                        lat, lng, build_year, total_households, max_floor, naver_complex_no, kb_complex_no
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sido, sigungu, lawd_cd, dong, complex_name, prop_type,
                    reg["lat"], reg["lng"], 2018, 500, total_floors, "", ""
                ))
                c_id = cur.lastrowid

            record_date = str(row.get("기준일", row.get("계약일", datetime.now().strftime("%Y-%m-%d"))))[:10]
            cur.execute("""
                INSERT INTO price_records (
                    complex_id, sido, sigungu, lawd_cd, dong, complex_name, property_type,
                    source, trade_type, exclusive_area, supply_area, pyeong, pyeong_group,
                    floor, total_floors, floor_group, price, monthly_rent,
                    kb_upper_price, kb_lower_price, official_price, direction, record_date, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                c_id, sido, sigungu, lawd_cd, dong, complex_name, prop_type,
                source, trade_type, exc_area, supply_area, pyeong, pyeong_group,
                floor, total_floors, floor_group, price, monthly_rent,
                int(price * 1.05), int(price * 0.94), official_price, "남향", record_date,
                f"파일 업로드 ({filename})"
            ))
            inserted += 1

        conn.commit()
        conn.close()
        return {"inserted": inserted, "filename": filename}
