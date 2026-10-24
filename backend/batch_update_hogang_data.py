import urllib.request
import urllib.parse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def search_hogang(name):
    try:
        q = urllib.parse.quote(name)
        url = f"https://hogangnono.com/api/v2/searches/new?query={q}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://hogangnono.com/'
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            apt_list = data.get('data', {}).get('matched', {}).get('apt', {}).get('list', [])
            if apt_list:
                top = apt_list[0]
                return top.get('id'), top.get('name'), top.get('address'), top.get('household')
    except Exception as e:
        pass
    return None, None, None, None

def fetch_apt_detail(hid):
    url = f"https://hogangnono.com/apt/{hid}"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://hogangnono.com/'
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8')
        
        m_store = re.search(r'"AptDongStore":\s*({[\s\S]*?})\s*,\s*"[A-Za-z]+Store":', html)
        if not m_store:
            return None
        
        store = json.loads(m_store.group(1))
        py_map = store.get('areaListPyMap', {})
        if not py_map:
            return None

        pyeong_details = []
        pyeong_names = []
        clean_ints = []
        for py_str, items in sorted(py_map.items(), key=lambda x: int(x[0])):
            py_int = int(py_str)
            clean_ints.append(py_int)
            pyeong_names.append(f"{py_int}평")
            tot_hh = sum(i.get('total_household', 0) for i in items)
            pub_areas = [i.get('public_area', 0) for i in items if i.get('public_area')]
            priv_areas = [i.get('private_area', 0) for i in items if i.get('private_area')]
            types = [i.get('area_type', '') for i in items if i.get('area_type')]
            
            pyeong_details.append({
                "pyeong": py_int,
                "households": tot_hh,
                "supply_area": round(pub_areas[0], 2) if pub_areas else round(py_int * 3.3058, 2),
                "exclusive_area": round(priv_areas[0], 2) if priv_areas else round(py_int * 3.3058 * 0.76, 2),
                "types": types
            })

        m_floor = re.search(r'최고\s*(\d+)층', html)
        m_min = re.search(r'최저\s*(\d+)층', html)
        m_dong = re.search(r'(\d+)개동', html)
        m_hh = re.search(r'(\d+)세대', html)
        m_price = re.search(r'최근 실거래 기준[^<]*<\/div><div class="price">([^<]+)<\/div>', html)

        # In case m_floor is None, check dongBuildingMap height or highest_floor
        max_floor = int(m_floor.group(1)) if m_floor else None
        if not max_floor:
            dong_map = store.get('dongBuildingMap') or store.get('dongMap') or {}
            floors = []
            for d in dong_map.values():
                if d.get('highest_floor'):
                    floors.append(d['highest_floor'])
                elif d.get('height'):
                    floors.append(int(round(d['height'] / 3.0)))
            if floors:
                max_floor = max(floors)

        return {
            "hogang_id": hid,
            "max_floor": max_floor,
            "min_floor": int(m_min.group(1)) if m_min else None,
            "households": int(m_hh.group(1)) if m_hh else sum(p['households'] for p in pyeong_details),
            "total_dong": int(m_dong.group(1)) if m_dong else None,
            "pyeongs": pyeong_names,
            "clean_ints": clean_ints,
            "pyeong_details": pyeong_details,
            "recent_price": m_price.group(1).strip() if m_price else None,
            "url": url
        }
    except Exception as e:
        print(f"Error fetching detail {hid}: {e}")
        return None

def main():
    with open('backend/verified_hogang_registry.json', 'r', encoding='utf-8') as f:
        reg = json.load(f)

    # 1. Add key complexes if missing
    must_have = [
        '광교두산위브', '광교더샵', '광교아이파크', '광교호반베르디움',
        '광교호수마을호반써밋', '광교더샵레이크파크', '광교센트럴타운60단지',
        '광교중흥S클래스', '자연앤힐스테이트', '광교센트럴뷰', 'e편한세상광교'
    ]
    for name in must_have:
        if name not in reg or not reg[name].get('hogang_id'):
            print(f"Searching Hogangnono for {name}...")
            hid, cname, addr, hh = search_hogang(name)
            if hid:
                reg[name] = {
                    "query": name,
                    "hogang_id": hid,
                    "name": cname or name,
                    "address": addr,
                    "households": hh,
                    "url": f"https://hogangnono.com/apt/{hid}"
                }
                print(f"Added {name} -> {hid}")

    # 2. Collect unique hogang_ids to fetch
    unique_hids = set()
    for k, v in reg.items():
        if isinstance(v, dict) and v.get('hogang_id'):
            unique_hids.add(v['hogang_id'])

    print(f"Total unique Hogang IDs to fetch: {len(unique_hids)}")

    fetched_details = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_hid = {executor.submit(fetch_apt_detail, hid): hid for hid in unique_hids}
        count = 0
        for future in as_completed(future_to_hid):
            hid = future_to_hid[future]
            try:
                res = future.result()
                if res:
                    fetched_details[hid] = res
                    count += 1
                    if count % 20 == 0:
                        print(f"Fetched {count}/{len(unique_hids)} complexes...")
            except Exception as e:
                print(f"Future error {hid}: {e}")

    print(f"Successfully fetched details for {len(fetched_details)} complexes!")

    # 3. Merge back into reg
    for k, v in reg.items():
        hid = v.get('hogang_id')
        if hid and hid in fetched_details:
            detail = fetched_details[hid]
            v['max_floor'] = detail['max_floor'] or v.get('max_floor')
            v['min_floor'] = detail['min_floor'] or v.get('min_floor')
            v['households'] = detail['households'] or v.get('households')
            v['total_dong'] = detail['total_dong'] or v.get('total_dong')
            v['pyeongs'] = detail['pyeongs']
            v['pyeong_details'] = detail['pyeong_details']
            if detail['recent_price']:
                v['recent_price'] = detail['recent_price']
            v['url'] = detail['url']

    with open('backend/verified_hogang_registry.json', 'w', encoding='utf-8') as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    print("Updated backend/verified_hogang_registry.json with rich pyeong_details!")

if __name__ == '__main__':
    main()
