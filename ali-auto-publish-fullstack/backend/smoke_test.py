import urllib.request as u, urllib.error as e, json, textwrap, time
base='http://127.0.0.1:8000'
paths=[
  '/api/health',
  '/api/config/',
  '/api/upload/status',
]
print('waiting backend...')
for _ in range(30):
    try:
        u.urlopen(base+'/api/health', timeout=1)
        break
    except Exception:
        time.sleep(1)
for p in paths:
    print('\n===',p,'===')
    data=None; method='GET'
    if p=='/api/upload/start':
        method='POST'; data=json.dumps({'mode':'batch','max_products':1}).encode()
    req=u.Request(base+p, data=data, method=method, headers={'Content-Type':'application/json'} if data else {})
    try:
        resp=u.urlopen(req, timeout=10)
        body=resp.read().decode('utf-8','ignore')
        print('OK',resp.status)
        print(textwrap.shorten(body, 200))
    except e.HTTPError as ex:
        b=ex.read().decode('utf-8','ignore')
        print('HTTP',ex.code,b)
    except Exception as ex:
        print('ERR',type(ex).__name__,ex)
