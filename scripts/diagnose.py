"""Read-only diagnostic: dump everything about <video> elements in any visible
icourse livingroom tab. Does NOT navigate, does NOT mutate.
"""
import json
import requests

JS = r"""
(function(){
  var videos = Array.from(document.querySelectorAll('video')).map(function(v, i){
    return {
      i: i,
      src: v.src || null,
      currentSrc: v.currentSrc || null,
      readyState: v.readyState,
      networkState: v.networkState,
      duration: v.duration,
      paused: v.paused,
      muted: v.muted,
      preload: v.preload,
      autoplay: v.autoplay,
      tagPath: (function(){
        var path = [], el = v;
        while (el && el !== document.body) { path.push(el.tagName + (el.id ? '#'+el.id : '') + (el.className ? '.'+String(el.className).split(' ').slice(0,2).join('.') : '')); el = el.parentElement; }
        return path.reverse().join(' > ');
      })(),
    };
  });
  return JSON.stringify({
    href: location.href,
    title: document.title,
    readyState: document.readyState,
    videoCount: videos.length,
    videos: videos,
  }, null, 2);
})()
"""

s = requests.Session()
s.trust_env = False

# 1) Find livingroom tab(s)
r = s.get("http://localhost:3456/targets", timeout=10)
targets = r.json()
if isinstance(targets, dict):
    targets = targets.get("value", [])

live_tabs = [t for t in targets if "livingroom" in t.get("url", "")]
print(f"Found {len(live_tabs)} livingroom tab(s):")
for t in live_tabs:
    print(f"  - {t['targetId']}  {t['url']}")
print()

# 2) Eval the diagnostic JS on each
for t in live_tabs:
    tid = t["targetId"]
    print(f"=== eval on {tid} ===")
    er = s.post(
        "http://localhost:3456/eval",
        params={"target": tid},
        data=JS.encode("utf-8"),
        timeout=30,
    )
    if er.status_code != 200:
        print(f"  HTTP {er.status_code}: {er.text[:300]}")
        continue
    body = er.json()
    val = body.get("value") if "value" in body else body
    if isinstance(val, str):
        print(val)
    else:
        print(json.dumps(val, indent=2, ensure_ascii=False))
    print()
