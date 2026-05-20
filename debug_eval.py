"""Debug the proxy eval call."""
import json
import requests

JS = """
(async function(){
  await new Promise(r => setTimeout(r, 100));
  var v = document.querySelector('video');
  return JSON.stringify({
    href: location.href,
    has_video: !!v,
    src: v ? (v.src || v.currentSrc) : null
  });
})()
"""

# First list targets
r = requests.get('http://localhost:3456/targets', timeout=10, proxies={'http': None, 'https': None})
print('targets status:', r.status_code, 'content-type:', r.headers.get('content-type'))
print('body start:', r.text[:200])
targets = r.json() if r.text else []
if isinstance(targets, dict):
    targets = targets.get('value', [])
print('count:', len(targets))
live_tabs = [t for t in targets if 'livingroom' in (t.get('url') or '')]
print('livingroom tabs:', [(t['targetId'], t['url']) for t in live_tabs])

if live_tabs:
    tid = live_tabs[0]['targetId']
    print('\nEvaluating in target', tid)
    er = requests.post(
        f'http://localhost:3456/eval?target={tid}',
        data=JS.encode('utf-8'),
        timeout=40,
        proxies={'http': None, 'https': None},
    )
    print('eval status:', er.status_code, 'content-type:', er.headers.get('content-type'))
    print('body start:', er.text[:500])
    try:
        body = er.json()
        print('parsed:', body)
    except Exception as e:
        print('parse error:', e)
