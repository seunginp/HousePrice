import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from batch_update_hogang_data import fetch_apt_detail

def main():
    with open('data.js', encoding='utf-8') as f:
        text = f.read()

    idx1 = text.find('window.STATIC_REAL_ESTATE_DATA = ')
    idx2 = text.find('window.HOGANGNONO_PRESET_DATA = ')
    static_data = json.loads(text[idx1 + len('window.STATIC_REAL_ESTATE_DATA = '):idx2].strip().rstrip(';'))
    comps = static_data['complexes_v2']

    with open('backend/all_hogang_apts_mapped.json', encoding='utf-8') as f:
        hogang_apts = json.load(f)

    lookup = {}
    for aid, item in hogang_apts.items():
        raw = item['raw_name']
        parts = raw.split(maxsplit=1)
        dong = parts[0] if len(parts) > 1 else ""
        apt_name = parts[1] if len(parts) > 1 else raw

        lookup[(dong, apt_name)] = aid
        lookup[(dong, re.sub(r'\s+', '', apt_name))] = aid
        lookup[apt_name] = aid
        lookup[re.sub(r'\s+', '', apt_name)] = aid
        lookup[raw] = aid

    # Priority target selection
    target_map = {} # hid -> name
    with open('backend/verified_hogang_registry.json', encoding='utf-8') as f:
        reg = json.load(f)
    for k, v in reg.items():
        if isinstance(v, dict) and v.get('hogang_id'):
            target_map[v['hogang_id']] = v.get('name', k)

    KEY_REGIONS = ["강남구", "서초구", "송파구", "과천시", "분당구", "영통구", "마포구", "용산구", "성동구"]
    KEY_NAMES = ["광교", "판교", "동탄", "위례", "고덕", "미사", "다산", "킨텍스", "목동", "여의도", "압구정", "반포", "대치", "개포", "잠실"]

    for c in comps:
        c_sigungu = c[2]
        c_dong = c[3]
        c_name = c[4]
        c_hh = c[9]

        norm_name = re.sub(r'\s+', '', c_name)
        aid = (lookup.get((c_dong, c_name)) or 
               lookup.get((c_dong, norm_name)) or 
               lookup.get(c_name) or 
               lookup.get(norm_name))
        
        if aid:
            is_priority = (
                c_hh >= 700 or
                any(k in c_sigungu for k in KEY_REGIONS) or
                any(k in c_name for k in KEY_NAMES)
            )
            if is_priority:
                target_map[aid] = c_name

    print(f"Total priority target Hogang IDs to scrape: {len(target_map)}")

    # Load existing registry to avoid re-fetching what's already rich
    already_done = set()
    for k, v in reg.items():
        if isinstance(v, dict) and v.get('hogang_id') and v.get('pyeong_details'):
            already_done.add(v['hogang_id'])

    to_fetch = [hid for hid in target_map.keys() if hid not in already_done]
    print(f"Already rich in registry: {len(already_done)}, to fetch: {len(to_fetch)}")

    t0 = time.time()
    fetched = 0
    with ThreadPoolExecutor(max_workers=30) as executor:
        future_to_hid = {executor.submit(fetch_apt_detail, hid): hid for hid in to_fetch}
        for future in as_completed(future_to_hid):
            hid = future_to_hid[future]
            name = target_map[hid]
            try:
                res = future.result()
                if res and res.get('pyeongs'):
                    reg[name] = {
                        "query": name,
                        "hogang_id": hid,
                        "name": name,
                        "households": res.get('households'),
                        "max_floor": res.get('max_floor'),
                        "min_floor": res.get('min_floor'),
                        "total_dong": res.get('total_dong'),
                        "pyeongs": res.get('pyeongs'),
                        "pyeong_details": res.get('pyeong_details'),
                        "recent_price": res.get('recent_price'),
                        "url": res.get('url')
                    }
                    fetched += 1
                    if fetched % 250 == 0:
                        print(f"Progress: {fetched}/{len(to_fetch)} fetched in {time.time()-t0:.1f}s...")
                        # Save checkpoint
                        with open('backend/verified_hogang_registry.json', 'w', encoding='utf-8') as f:
                            json.dump(reg, f, ensure_ascii=False, indent=2)
            except Exception as e:
                pass

    print(f"[{time.time()-t0:.1f}s] Complete! Fetched {fetched} new rich apartment details!")
    with open('backend/verified_hogang_registry.json', 'w', encoding='utf-8') as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()
