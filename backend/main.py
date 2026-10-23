# -*- coding: utf-8 -*-
import os
import io
from typing import Optional
from fastapi import FastAPI, Query, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from database import init_db, get_connection
from regions_data import SEOUL_GYEONGGI_REGIONS
from collectors import MolitPublicDataCollector, NaverKbSyncService, SpreadsheetImporter, HogangnonoCollector

app = FastAPI(
    title="서울·경기 부동산 통합 비교 지도 API",
    description="부동산공시가격 알리미, 국토교통부 실거래가, 네이버 부동산, KB 부동산 통합 매매·전세·월세·공시가격 및 층별·평수별 비교 시스템",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서버 시작 시 DB 초기화 및 시드 데이터 생성
init_db()

# 지역 중심좌표 룩업 테이블
SIGUNGU_COORD_MAP = {
    (r["sido"], r["sigungu"]): {"lat": r["lat"], "lng": r["lng"], "lawd_cd": r["lawd_cd"]}
    for r in SEOUL_GYEONGGI_REGIONS
}
DONG_COORD_MAP = {}
for r in SEOUL_GYEONGGI_REGIONS:
    for d in r["dongs"]:
        DONG_COORD_MAP[(r["sido"], r["sigungu"], d["dong"])] = {"lat": d["lat"], "lng": d["lng"], "lawd_cd": r["lawd_cd"]}


def build_where_clause(
    sido: str = "전체",
    sigungu: str = "전체",
    property_type: str = "전체",
    trade_type: str = "매매",
    source: str = "전체",
    pyeong_group: str = "전체",
    min_pyeong: Optional[int] = None,
    max_pyeong: Optional[int] = None,
    floor_group: str = "전체",
    min_floor: Optional[int] = None,
    max_floor: Optional[int] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    search: Optional[str] = None,
    table_alias: str = ""
):
    prefix = f"{table_alias}." if table_alias else ""
    clauses = ["1=1"]
    params = []

    if sido and sido != "전체":
        clauses.append(f"{prefix}sido = ?")
        params.append(sido)
    if sigungu and sigungu != "전체":
        clauses.append(f"{prefix}sigungu = ?")
        params.append(sigungu)
    if property_type and property_type != "전체":
        clauses.append(f"{prefix}property_type = ?")
        params.append(property_type)
    if trade_type and trade_type != "전체":
        clauses.append(f"{prefix}trade_type = ?")
        params.append(trade_type)
    if source and source != "전체":
        clauses.append(f"{prefix}source = ?")
        params.append(source)
    if pyeong_group and pyeong_group != "전체":
        clauses.append(f"{prefix}pyeong_group = ?")
        params.append(pyeong_group)
    if min_pyeong is not None:
        clauses.append(f"{prefix}pyeong >= ?")
        params.append(min_pyeong)
    if max_pyeong is not None:
        clauses.append(f"{prefix}pyeong <= ?")
        params.append(max_pyeong)
    if floor_group and floor_group != "전체":
        clauses.append(f"{prefix}floor_group = ?")
        params.append(floor_group)
    if min_floor is not None:
        clauses.append(f"{prefix}floor >= ?")
        params.append(min_floor)
    if max_floor is not None:
        clauses.append(f"{prefix}floor <= ?")
        params.append(max_floor)
    if min_price is not None and min_price > 0:
        clauses.append(f"{prefix}price >= ?")
        params.append(min_price)
    if max_price is not None and max_price > 0:
        clauses.append(f"{prefix}price <= ?")
        params.append(max_price)
    if search and search.strip():
        q = f"%{search.strip()}%"
        clauses.append(f"({prefix}sigungu LIKE ? OR {prefix}dong LIKE ? OR {prefix}complex_name LIKE ?)")
        params.extend([q, q, q])

    return " AND ".join(clauses), params


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(frontend_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/data.js")
def serve_data_js():
    data_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "data.js")
    if os.path.exists(data_path):
        with open(data_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), media_type="application/javascript")
    return HTMLResponse(content="window.STATIC_REAL_ESTATE_DATA = null;", media_type="application/javascript")


@app.get("/api/lawd-codes")
def get_lawd_codes():
    return [
        {
            "sido": r["sido"],
            "sigungu": r["sigungu"],
            "lawd_cd": r["lawd_cd"],
            "lat": r["lat"],
            "lng": r["lng"],
            "dong_count": len(r["dongs"])
        }
        for r in SEOUL_GYEONGGI_REGIONS
    ]


@app.get("/api/regions/summary")
def get_regions_summary(
    level: str = Query("sigungu", description="sigungu 또는 dong"),
    sido: str = "전체",
    sigungu: str = "전체",
    property_type: str = "전체",
    trade_type: str = "매매",
    source: str = "전체",
    pyeong_group: str = "전체",
    min_pyeong: Optional[int] = None,
    max_pyeong: Optional[int] = None,
    floor_group: str = "전체",
    min_floor: Optional[int] = None,
    max_floor: Optional[int] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    search: Optional[str] = None,
):
    where_sql, params = build_where_clause(
        sido, sigungu, property_type, trade_type, source,
        pyeong_group, min_pyeong, max_pyeong,
        floor_group, min_floor, max_floor,
        min_price, max_price, search
    )

    conn = get_connection()
    cur = conn.cursor()

    if level == "dong":
        sql = f"""
            SELECT
                sido, sigungu, lawd_cd, dong,
                COUNT(*) AS record_count,
                COUNT(DISTINCT complex_id) AS complex_count,
                CAST(ROUND(AVG(price)) AS INTEGER) AS avg_price,
                CAST(ROUND(MIN(price)) AS INTEGER) AS min_price,
                CAST(ROUND(MAX(price)) AS INTEGER) AS max_price,
                CAST(ROUND(AVG(price * 1.0 / pyeong)) AS INTEGER) AS avg_pyeong_price,
                CAST(ROUND(AVG(monthly_rent)) AS INTEGER) AS avg_monthly_rent,
                CAST(ROUND(AVG(official_price)) AS INTEGER) AS avg_official_price,
                CAST(ROUND(AVG(CASE WHEN source='네이버부동산' THEN price END)) AS INTEGER) AS naver_avg_price,
                CAST(ROUND(AVG(CASE WHEN source='KB부동산' THEN price END)) AS INTEGER) AS kb_avg_price,
                CAST(ROUND(AVG(CASE WHEN source='국토부실거래' THEN price END)) AS INTEGER) AS molit_avg_price
            FROM price_records
            WHERE {where_sql}
            GROUP BY sido, sigungu, lawd_cd, dong
            ORDER BY avg_price DESC
        """
        cur.execute(sql, params)
        rows = cur.fetchall()
        results = []
        for r in rows:
            coord = DONG_COORD_MAP.get((r["sido"], r["sigungu"], r["dong"]))
            if not coord:
                coord = SIGUNGU_COORD_MAP.get((r["sido"], r["sigungu"]), {"lat": 37.5665, "lng": 126.9780})
            results.append({
                "level": "dong",
                "sido": r["sido"],
                "sigungu": r["sigungu"],
                "lawd_cd": r["lawd_cd"],
                "dong": r["dong"],
                "label": r["dong"],
                "full_name": f"{r['sido']} {r['sigungu']} {r['dong']}",
                "lat": coord["lat"],
                "lng": coord["lng"],
                "record_count": r["record_count"],
                "complex_count": r["complex_count"],
                "avg_price": r["avg_price"] or 0,
                "min_price": r["min_price"] or 0,
                "max_price": r["max_price"] or 0,
                "avg_pyeong_price": r["avg_pyeong_price"] or 0,
                "avg_monthly_rent": r["avg_monthly_rent"] or 0,
                "avg_official_price": r["avg_official_price"] or 0,
                "naver_avg_price": r["naver_avg_price"] or r["avg_price"] or 0,
                "kb_avg_price": r["kb_avg_price"] or r["avg_price"] or 0,
                "molit_avg_price": r["molit_avg_price"] or r["avg_price"] or 0,
            })
    else:
        sql = f"""
            SELECT
                sido, sigungu, lawd_cd,
                COUNT(*) AS record_count,
                COUNT(DISTINCT complex_id) AS complex_count,
                CAST(ROUND(AVG(price)) AS INTEGER) AS avg_price,
                CAST(ROUND(MIN(price)) AS INTEGER) AS min_price,
                CAST(ROUND(MAX(price)) AS INTEGER) AS max_price,
                CAST(ROUND(AVG(price * 1.0 / pyeong)) AS INTEGER) AS avg_pyeong_price,
                CAST(ROUND(AVG(monthly_rent)) AS INTEGER) AS avg_monthly_rent,
                CAST(ROUND(AVG(official_price)) AS INTEGER) AS avg_official_price,
                CAST(ROUND(AVG(CASE WHEN source='네이버부동산' THEN price END)) AS INTEGER) AS naver_avg_price,
                CAST(ROUND(AVG(CASE WHEN source='KB부동산' THEN price END)) AS INTEGER) AS kb_avg_price,
                CAST(ROUND(AVG(CASE WHEN source='국토부실거래' THEN price END)) AS INTEGER) AS molit_avg_price
            FROM price_records
            WHERE {where_sql}
            GROUP BY sido, sigungu, lawd_cd
            ORDER BY avg_price DESC
        """
        cur.execute(sql, params)
        rows = cur.fetchall()
        results = []
        for r in rows:
            coord = SIGUNGU_COORD_MAP.get((r["sido"], r["sigungu"]), {"lat": 37.5665, "lng": 126.9780})
            results.append({
                "level": "sigungu",
                "sido": r["sido"],
                "sigungu": r["sigungu"],
                "lawd_cd": r["lawd_cd"],
                "dong": "",
                "label": r["sigungu"],
                "full_name": f"{r['sido']} {r['sigungu']}",
                "lat": coord["lat"],
                "lng": coord["lng"],
                "record_count": r["record_count"],
                "complex_count": r["complex_count"],
                "avg_price": r["avg_price"] or 0,
                "min_price": r["min_price"] or 0,
                "max_price": r["max_price"] or 0,
                "avg_pyeong_price": r["avg_pyeong_price"] or 0,
                "avg_monthly_rent": r["avg_monthly_rent"] or 0,
                "avg_official_price": r["avg_official_price"] or 0,
                "naver_avg_price": r["naver_avg_price"] or r["avg_price"] or 0,
                "kb_avg_price": r["kb_avg_price"] or r["avg_price"] or 0,
                "molit_avg_price": r["molit_avg_price"] or r["avg_price"] or 0,
            })

    conn.close()
    return results


@app.get("/api/complexes")
def get_complexes(
    sido: str = "전체",
    sigungu: str = "전체",
    dong: str = "전체",
    property_type: str = "전체",
    trade_type: str = "매매",
    source: str = "전체",
    pyeong_group: str = "전체",
    min_pyeong: Optional[int] = None,
    max_pyeong: Optional[int] = None,
    floor_group: str = "전체",
    min_floor: Optional[int] = None,
    max_floor: Optional[int] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    search: Optional[str] = None,
):
    where_sql, params = build_where_clause(
        sido, sigungu, property_type, trade_type, source,
        pyeong_group, min_pyeong, max_pyeong,
        floor_group, min_floor, max_floor,
        min_price, max_price, search,
        table_alias="pr"
    )
    if dong and dong != "전체":
        where_sql += " AND pr.dong = ?"
        params.append(dong)

    conn = get_connection()
    cur = conn.cursor()

    sql = f"""
        SELECT
            c.id, c.sido, c.sigungu, c.lawd_cd, c.dong, c.name, c.property_type,
            c.lat, c.lng, c.build_year, c.total_households, c.max_floor,
            COUNT(pr.id) AS record_count,
            CAST(ROUND(AVG(pr.price)) AS INTEGER) AS avg_price,
            CAST(ROUND(MIN(pr.price)) AS INTEGER) AS min_price,
            CAST(ROUND(MAX(pr.price)) AS INTEGER) AS max_price,
            CAST(ROUND(AVG(pr.price * 1.0 / pr.pyeong)) AS INTEGER) AS avg_pyeong_price,
            CAST(ROUND(AVG(pr.monthly_rent)) AS INTEGER) AS avg_monthly_rent,
            CAST(ROUND(AVG(pr.official_price)) AS INTEGER) AS avg_official_price,
            CAST(ROUND(AVG(CASE WHEN pr.source='네이버부동산' THEN pr.price END)) AS INTEGER) AS naver_price,
            CAST(ROUND(AVG(CASE WHEN pr.source='KB부동산' THEN pr.price END)) AS INTEGER) AS kb_price,
            CAST(ROUND(AVG(CASE WHEN pr.source='국토부실거래' THEN pr.price END)) AS INTEGER) AS molit_price,
            GROUP_CONCAT(DISTINCT pr.pyeong) AS pyeongs
        FROM complexes c
        JOIN price_records pr ON c.id = pr.complex_id
        WHERE {where_sql}
        GROUP BY c.id
        ORDER BY avg_price DESC
    """
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    return [dict(r) for r in rows]


@app.get("/api/complexes/{complex_id}")
def get_complex_detail(
    complex_id: int,
    trade_type: str = "매매",
    pyeong: Optional[int] = None,
):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM complexes WHERE id = ?", (complex_id,))
    comp = cur.fetchone()
    if not comp:
        conn.close()
        raise HTTPException(status_code=404, detail="단지를 찾을 수 없습니다.")

    # 1. 단지 내 전체 평형 목록
    cur.execute("""
        SELECT DISTINCT pyeong, pyeong_group, exclusive_area, supply_area
        FROM price_records
        WHERE complex_id = ?
        ORDER BY pyeong ASC
    """, (complex_id,))
    pyeong_list = [dict(r) for r in cur.fetchall()]

    # 선택된 평형 필터 조건
    pyeong_clause = ""
    pyeong_params = []
    if pyeong is not None and pyeong > 0:
        pyeong_clause = " AND pyeong = ?"
        pyeong_params = [pyeong]

    # 2. 출처별(공시가격알리미 / 국토부실거래 / 네이버부동산 / KB부동산) 및 거래유형별 요약
    cur.execute(f"""
        SELECT
            source,
            trade_type,
            COUNT(*) AS cnt,
            CAST(ROUND(AVG(price)) AS INTEGER) AS avg_price,
            CAST(ROUND(MIN(price)) AS INTEGER) AS min_price,
            CAST(ROUND(MAX(price)) AS INTEGER) AS max_price,
            CAST(ROUND(AVG(monthly_rent)) AS INTEGER) AS avg_monthly_rent,
            CAST(ROUND(AVG(kb_upper_price)) AS INTEGER) AS kb_upper,
            CAST(ROUND(AVG(kb_lower_price)) AS INTEGER) AS kb_lower,
            CAST(ROUND(AVG(official_price)) AS INTEGER) AS avg_official
        FROM price_records
        WHERE complex_id = ? {pyeong_clause}
        GROUP BY source, trade_type
    """, [complex_id] + pyeong_params)
    source_summary = [dict(r) for r in cur.fetchall()]

    # 3. 층별 구분(1층, 저층, 중층, 고층, 탑층) 가격 비교
    cur.execute(f"""
        SELECT
            floor_group,
            MIN(floor) AS sample_floor,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' THEN price END)) AS INTEGER) AS sale_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' AND source='네이버부동산' THEN price END)) AS INTEGER) AS naver_sale_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' AND source='국토부실거래' THEN price END)) AS INTEGER) AS molit_sale_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' AND source='KB부동산' THEN price END)) AS INTEGER) AS kb_sale_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='전세' THEN price END)) AS INTEGER) AS jeonse_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='월세' THEN price END)) AS INTEGER) AS wolse_deposit_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='월세' THEN monthly_rent END)) AS INTEGER) AS wolse_rent_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='공시가격' THEN price END)) AS INTEGER) AS official_avg
        FROM price_records
        WHERE complex_id = ? {pyeong_clause}
        GROUP BY floor_group
        ORDER BY sample_floor ASC
    """, [complex_id] + pyeong_params)
    floor_breakdown = [dict(r) for r in cur.fetchall()]

    # 4. 평수별(면적별) 가격 비교
    cur.execute("""
        SELECT
            pyeong,
            pyeong_group,
            exclusive_area,
            supply_area,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' THEN price END)) AS INTEGER) AS sale_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='매매' THEN price * 1.0 / pyeong END)) AS INTEGER) AS pyeong_price,
            CAST(ROUND(AVG(CASE WHEN trade_type='전세' THEN price END)) AS INTEGER) AS jeonse_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='월세' THEN price END)) AS INTEGER) AS wolse_deposit_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='월세' THEN monthly_rent END)) AS INTEGER) AS wolse_rent_avg,
            CAST(ROUND(AVG(CASE WHEN trade_type='공시가격' THEN price END)) AS INTEGER) AS official_avg
        FROM price_records
        WHERE complex_id = ?
        GROUP BY pyeong
        ORDER BY pyeong ASC
    """, (complex_id,))
    area_breakdown = [dict(r) for r in cur.fetchall()]

    # 5. 개별 매물 및 실거래/공시가격 상세 내역
    cur.execute(f"""
        SELECT *
        FROM price_records
        WHERE complex_id = ? {pyeong_clause}
        ORDER BY pyeong ASC, floor DESC, record_date DESC
        LIMIT 120
    """, [complex_id] + pyeong_params)
    records = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "complex": dict(comp),
        "pyeong_list": pyeong_list,
        "source_summary": source_summary,
        "floor_breakdown": floor_breakdown,
        "area_breakdown": area_breakdown,
        "records": records
    }


class CollectMolitRequest(BaseModel):
    service_key: str
    lawd_cd: str
    deal_ymd: str
    property_type: str = "아파트"
    mode: str = "매매"



@app.get("/api/hogangnono/search")
def search_hogangnono(query: str):
    """호갱노노 실시간 단지 검색 API 프록시"""
    results = HogangnonoCollector.search_apt(query)
    return {"status": "success", "query": query, "items": results}


@app.get("/api/hogangnono/apt/{apt_id}")
def get_hogangnono_apt(apt_id: str):
    """호갱노노 단지 상세 정보 (최고층, 평형목록, 실거래시세) 조회"""
    detail = HogangnonoCollector.get_apt_detail(apt_id)
    if not detail:
        raise HTTPException(status_code=404, detail="호갱노노 단지 정보를 찾을 수 없습니다.")
    return {"status": "success", "data": detail}


@app.post("/api/collect/molit")
def collect_molit_data(req: CollectMolitRequest):
    try:
        result = MolitPublicDataCollector.fetch_and_save(
            service_key=req.service_key,
            lawd_cd=req.lawd_cd,
            deal_ymd=req.deal_ymd,
            property_type=req.property_type,
            mode=req.mode
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


class SyncNaverKbRequest(BaseModel):
    lawd_cd: str
    source_target: str = "ALL"


@app.post("/api/collect/sync")
def sync_naver_kb(req: SyncNaverKbRequest):
    try:
        return NaverKbSyncService.sync_region(req.lawd_cd, req.source_target)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/upload")
async def upload_spreadsheet(file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = SpreadsheetImporter.import_file(file.filename, content)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"파일 업로드 처리 중 오류: {str(e)}")


@app.get("/api/sample-template")
def download_sample_template():
    csv_content = (
        "시도,시군구,법정동,단지명,부동산유형,출처,거래유형,전용면적,평수,층,총층,가격,월세,공시가격,기준일\n"
        "서울특별시,강남구,대치동,래미안대치팰리스,아파트,국토부실거래,매매,84.9,34,18,35,345000,0,241000,2026-10-15\n"
        "서울특별시,강남구,대치동,래미안대치팰리스,아파트,네이버부동산,매매,84.9,34,22,35,358000,0,245000,2026-10-20\n"
        "경기도,성남시 분당구,백현동,판교푸르지오그랑블,아파트,KB부동산,전세,97.2,38,14,25,135000,0,192000,2026-10-18\n"
    )
    stream = io.BytesIO(csv_content.encode("utf-8-sig"))
    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=real_estate_upload_template.csv"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
