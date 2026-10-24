import urllib.request
import gzip
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_target_bjds():
    url = 'https://hogangnono.com/sitemap/regionApts/sitemap.xml'
    req = urllib.request.Request(url, headers={'User-Agent': 'Googlebot'})
    raw = urllib.request.urlopen(req, timeout=10).read()
    try:
        content = gzip.decompress(raw).decode('utf-8')
    except Exception:
        content = raw.decode('utf-8')
    bjd_codes = re.findall(r'/region/(\d+)/0/apt-list', content)
    # Seoul (11*) and Gyeonggi (41*)
    return [b for b in bjd_codes if b.startswith('11') or b.startswith('41')]

def fetch_bjd(bjd):
    url = f'https://hogangnono.com/region/{bjd}/0/apt-list'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8')
        apts = re.findall(r'<a href="/apt/([a-zA-Z0-9]+)/[^"]*"[^>]*><h5 class="name">([^<]+)</h5>(?:\s*<span class="price[^"]*">([^<]*)</span>)?(?:\s*<span class="area[^"]*">([^<]*)</span>)?', html)
        return bjd, apts
    except Exception:
        return bjd, []

def main():
    bjds = get_target_bjds()
    print(f"Total Seoul + Gyeonggi BJDs to fetch: {len(bjds)}")
    t0 = time.time()
    
    results = {}
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(fetch_bjd, b): b for b in bjds}
        count = 0
        for f in as_completed(futures):
            bjd, apts = f.result()
            count += 1
            if count % 500 == 0:
                print(f"Progress: {count}/{len(bjds)} BJDs processed... ({len(results)} apts collected so far)")
            if apts:
                for aid, aname, price, area in apts:
                    if aid not in results:
                        results[aid] = {
                            "id": aid,
                            "raw_name": aname.strip(),
                            "price": price.strip() if price else None,
                            "rep_area": area.strip() if area else None,
                            "bjd": bjd
                        }

    print(f"[{time.time()-t0:.2f}s] Finished! Total unique Seoul + Gyeonggi apartments found: {len(results)}")
    with open('backend/all_hogang_apts_mapped.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Saved to backend/all_hogang_apts_mapped.json!")

if __name__ == '__main__':
    main()
