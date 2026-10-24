import json
import re

def main():
    print("Loading datasets...")
    with open('backend/verified_hogang_registry.json', encoding='utf-8') as f:
        reg = json.load(f)

    with open('backend/all_hogang_apts_mapped.json', encoding='utf-8') as f:
        hogang_all = json.load(f)

    with open('data.js', encoding='utf-8') as f:
        text = f.read()

    idx1 = text.find('window.STATIC_REAL_ESTATE_DATA = ')
    idx2 = text.find('window.HOGANGNONO_PRESET_DATA = ')
    static_data = json.loads(text[idx1 + len('window.STATIC_REAL_ESTATE_DATA = '):idx2].strip().rstrip(';'))
    comps = static_data['complexes_v2']

    # Normalize lookup maps
    reg_lookup = {}
    for k, v in reg.items():
        if isinstance(v, dict):
            reg_lookup[k] = v
            norm_k = re.sub(r'\s+', '', k)
            reg_lookup[norm_k] = v
            if v.get('name'):
                reg_lookup[v['name']] = v
                reg_lookup[re.sub(r'\s+', '', v['name'])] = v

    hogang_lookup = {}
    for aid, item in hogang_all.items():
        raw = item['raw_name']
        parts = raw.split(maxsplit=1)
        dong = parts[0] if len(parts) > 1 else ""
        apt_name = parts[1] if len(parts) > 1 else raw

        hogang_lookup[(dong, apt_name)] = item
        hogang_lookup[(dong, re.sub(r'\s+', '', apt_name))] = item
        hogang_lookup[apt_name] = item
        hogang_lookup[re.sub(r'\s+', '', apt_name)] = item
        hogang_lookup[raw] = item

    rich_count = 0
    basic_count = 0
    fallback_count = 0

    clean_preset = {}

    # 1. Populate clean_preset with all rich entries from reg
    for k, v in reg.items():
        if isinstance(v, dict) and v.get('pyeongs'):
            clean_preset[k] = {
                "id": v.get("hogang_id"),
                "max_floor": v.get("max_floor"),
                "min_floor": v.get("min_floor"),
                "households": v.get("households"),
                "total_dong": v.get("total_dong"),
                "pyeongs": v.get("pyeongs"),
                "pyeong_details": v.get("pyeong_details"),
                "recent_price": v.get("recent_price"),
                "pyeong_price": v.get("pyeong_price"),
                "url": v.get("url")
            }

    # 2. Iterate complexes_v2 and apply real data
    for c in comps:
        # Schema: [id, sido_idx, sigungu, dong, name, prop_idx, lat, lng, build_year, households, max_floor, rep_pyeong, sale_avg, jeonse_avg, lawd_cd, pyeongs]
        c_dong = c[3]
        c_name = c[4]
        norm_name = re.sub(r'\s+', '', c_name)

        rich_match = (reg_lookup.get((c_dong, c_name)) or 
                      reg_lookup.get(c_name) or 
                      reg_lookup.get(norm_name))

        if rich_match and rich_match.get('pyeongs'):
            pd = rich_match.get('pyeong_details')
            if pd and len(pd) > 0:
                clean_ints = [p['pyeong'] for p in pd]
                max_hh_p = max(pd, key=lambda x: x.get('households', 0))['pyeong']
                c[11] = max_hh_p
            else:
                clean_ints = [int(re.sub(r'\D', '', p)) for p in rich_match['pyeongs'] if re.sub(r'\D', '', p)]
            
            if len(c) > 15:
                c[15] = clean_ints
            else:
                c.append(clean_ints)

            if rich_match.get('households'):
                c[9] = rich_match['households']
            if rich_match.get('max_floor'):
                c[10] = rich_match['max_floor']
            
            rich_count += 1
            continue

        # Case 2: In hogang_all (basic match)
        basic_match = (hogang_lookup.get((c_dong, c_name)) or 
                       hogang_lookup.get((c_dong, norm_name)) or 
                       hogang_lookup.get(c_name) or 
                       hogang_lookup.get(norm_name))

        if basic_match:
            rep_area_str = basic_match.get('rep_area')
            hid = basic_match.get('id')
            p_int = int(re.sub(r'\D', '', rep_area_str)) if rep_area_str and re.sub(r'\D', '', rep_area_str) else c[11]
            
            if len(c) > 15:
                c[15] = [p_int]
            else:
                c.append([p_int])
            c[11] = p_int

            if c_name not in clean_preset:
                clean_preset[c_name] = {
                    "id": hid,
                    "recent_price": basic_match.get('price'),
                    "pyeongs": [f"{p_int}평"],
                    "url": f"https://hogangnono.com/apt/{hid}"
                }

            basic_count += 1
            continue

        # Case 3: Fallback (keep single rep_pyeong, ZERO arbitrary heuristic lists!)
        single_p = [c[11]] if c[11] > 0 else [33]
        if len(c) > 15:
            c[15] = single_p
        else:
            c.append(single_p)
        fallback_count += 1

    print(f"Update Summary:")
    print(f"  - Rich Hogangnono Multi-Pyeong + Households: {rich_count} complexes")
    print(f"  - Verified Hogangnono Single-Pyeong: {basic_count} complexes")
    print(f"  - Fallback clean single pyeong: {fallback_count} complexes")
    print(f"  - Total preset entries in data.js: {len(clean_preset)}")

    js_str = "window.STATIC_REAL_ESTATE_DATA = " + json.dumps(static_data, ensure_ascii=False, separators=(",", ":")) + ";\n\n"
    js_str += "window.HOGANGNONO_PRESET_DATA = " + json.dumps(clean_preset, ensure_ascii=False) + ";\n"

    with open('data.js', 'w', encoding='utf-8') as f:
        f.write(js_str)
    with open('frontend/data.js', 'w', encoding='utf-8') as f:
        f.write(js_str)

    print("Successfully wrote updated data.js and frontend/data.js!")

if __name__ == '__main__':
    main()
