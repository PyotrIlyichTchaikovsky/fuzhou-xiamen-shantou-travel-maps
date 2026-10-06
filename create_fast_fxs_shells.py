"""Build stable Fuzhou–Xiamen–Shantou map shells for existing Notion embeds.

Run only when changing the map UI itself. Routine itinerary edits update one
routes/YYYY-MM-DD.json file instead of rebuilding these HTML pages.
"""

import json
import re
from pathlib import Path


ROOT = Path('travel/fuzhou-xiamen-shantou')
OUT = ROOT / 'embed-v2'
OUT.mkdir(parents=True, exist_ok=True)

CITY_DAYS = {
    'city-fuzhou': [
        ('2026-10-11', '10/11 到站', 1, None, False),
        ('2026-10-12', '10/12 西湖·三坊七巷', 0, None, False),
        ('2026-10-13', '10/13 鼓山', 0, None, False),
        ('2026-10-14', '10/14 烟台山', 0, None, False),
    ],
    'city-xiamen': [
        ('2026-10-15', '10/15 鼓浪屿', 0, None, False),
        ('2026-10-16', '10/16 植物园', 0, None, False),
        ('2026-10-17', '10/17 南普陀·沙坡尾', 0, None, False),
        ('2026-10-18', '10/18 胡里山·环岛路', 0, None, False),
        ('2026-10-19', '10/19 八市·集美', 0, None, False),
    ],
    'city-shantou': [
        ('2026-10-20', '10/20 抵达', 1, None, False),
        ('2026-10-21', '10/21 老城', 0, None, False),
        ('2026-10-22', '10/22 南澳岛', 0, None, False),
        ('2026-10-23', '10/23 机动选项', 0, None, True),
    ],
}

CITY_NOTES = {
    'city-fuzhou': '汇总10月11日至14日的福州行程。点选日期可只看当天路线；地点和顺序以每日路线数据为准。',
    'city-xiamen': '汇总10月15日至19日的厦门行程。点选日期可只看当天路线；地点和顺序以每日路线数据为准。',
    'city-shantou': '汇总10月20日至23日的汕头行程。点选日期可只看当天路线；地点和顺序以每日路线数据为准。',
}

LOAD_HELPER = """async function loadRoute(path){
  const url=new URL(path,location.href);url.searchParams.set('rev',String(Date.now()));
  try{const response=await fetch(url,{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);return await response.json()}
  catch(error){const box=document.getElementById('status');box.textContent='路线数据暂时无法加载，请刷新重试。';box.style.display='block';throw error}
}
"""

DAILY_OLD = "const data=JSON.parse(document.getElementById('route-data').textContent), mapbox="
CITY_OLD = "const data=JSON.parse(document.getElementById('map-data').textContent),filters="


def replace_payload(html: str, element_id: str, payload: dict) -> str:
    tag = re.search(
        rf'<script id="{element_id}" type="application/json">.*?</script>',
        html,
        flags=re.S,
    )
    if tag is None:
        raise ValueError(f'Missing {element_id} payload')
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    new_id = 'route-source' if element_id == 'route-data' else 'city-source'
    return html[:tag.start()] + f'<script id="{new_id}" type="application/json">{encoded}</script>' + html[tag.end():]


for source in sorted(ROOT.glob('2026-10-??.html')):
    day = source.stem
    html = source.read_text(encoding='utf-8')
    if html.count(DAILY_OLD) != 1:
        raise ValueError(f'Unexpected daily JS in {source}')
    html = replace_payload(html, 'route-data', {'path': f'../routes/{day}.json'})
    replacement = (
        LOAD_HELPER
        + "const data=await loadRoute(JSON.parse(document.getElementById('route-source').textContent).path), mapbox="
    )
    html = html.replace(DAILY_OLD, replacement, 1)
    target = OUT / source.name
    target.write_text(html, encoding='utf-8', newline='')
    print(target.as_posix(), target.stat().st_size)

for name, sections in CITY_DAYS.items():
    source = ROOT / f'{name}.html'
    html = source.read_text(encoding='utf-8')
    original = re.search(r'<script id="map-data" type="application/json">(.*?)</script>', html, flags=re.S)
    if original is None:
        raise ValueError(f'Missing city data in {source}')
    current = json.loads(original.group(1))
    if [s['label'] for s in current['sections']] != [s[1] for s in sections]:
        raise ValueError(f'City labels drifted in {source}; update CITY_DAYS before rebuilding')
    if html.count(CITY_OLD) != 1:
        raise ValueError(f'Unexpected city JS in {source}')
    config = {
        'title': current['title'],
        'note': CITY_NOTES[name],
        'sections': [
            {'date': date, 'label': label, 'start': start, 'end': end, 'extras': extras}
            for date, label, start, end, extras in sections
        ],
    }
    html = replace_payload(html, 'map-data', config)
    city_loader = """const config=JSON.parse(document.getElementById('city-source').textContent);
const fetched=await Promise.all(config.sections.map(s=>loadRoute('../routes/'+s.date+'.json')));
const data={title:config.title,note:config.note,sections:config.sections.map((s,i)=>{
  const day=fetched[i],points=day.points.slice(s.start,s.end===null?undefined:s.end);
  const segments=day.segments.slice(s.start,s.end===null?undefined:s.end-1);
  if(s.extras)for(const option of day.alternatives||[])for(const point of option.points)points.push({...point,name:point.name+'（可选）'});
  const summary=day.title.includes('｜')?day.title.split('｜').slice(1).join('｜'):day.title;
  return {label:s.date.slice(5).replace('-','/')+' '+summary,points,segments};
})},filters="""
    html = html.replace(CITY_OLD, LOAD_HELPER + city_loader, 1)
    target = OUT / source.name
    target.write_text(html, encoding='utf-8', newline='')
    print(target.as_posix(), target.stat().st_size)
