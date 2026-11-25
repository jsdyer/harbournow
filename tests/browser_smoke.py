"""CI-only browser checks against deterministic, explicitly test-only API fixtures."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from pathlib import Path
import json
import threading
import time
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(ROOT/'dist')))
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url=f'http://127.0.0.1:{server.server_address[1]}'
now=time.time()
harbours=json.loads((ROOT/'config/harbours.json').read_text())['harbours']
def mock(route):
    path=route.request.url
    if '/api/v1/harbours' in path:data={'harbours':harbours}
    elif '/health' in path:data={'configured':True,'observations_fresh':True,'feed':{'state':'connected'},'last_observation_at':'2026-11-25T00:00:00Z'}
    elif '/ships' in path:data={'generated_at':'2026-11-25T00:00:00Z','ships':[{'mmsi':'123456789','name':'TEST VESSEL <script>','lat':44.65,'lon':-63.565,'speed':2.1,'ship_type':70,'position_at':now,'stale':False,'state':{'anchored':False}}]}
    elif '/events' in path:data={'events':[{'mmsi':'123456789','name':'TEST VESSEL','kind':'entry','time':now}]}
    else:data={'track':[{'time':now-120,'lat':44.64,'lon':-63.56},{'time':now,'lat':44.65,'lon':-63.565}]}
    route.fulfill(status=200,content_type='application/json',body=json.dumps(data),headers={'Access-Control-Allow-Origin':'*'})
try:
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        offline_config=json.loads((ROOT/'web/config.json').read_text());offline_config['api_base']=''
        page.route('**/config.json',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(offline_config)))
        page.route('**/api/v1/**',lambda route:route.fulfill(status=404,body='not connected'))
        page.goto(url+'/index.html');page.wait_for_selector('#map svg')
        assert 'Collector not connected' in page.locator('#connection-banner').inner_text()
        page.locator('summary').click();page.locator('#endpoint').fill('https://harbour.example.test')
        page.unroute('**/api/v1/**');page.route('https://harbour.example.test/api/v1/**',mock)
        page.get_by_role('button',name='Connect',exact=True).click()
        page.wait_for_selector('.vessel-row')
        assert page.locator('#count').inner_text()=='1'
        page.locator('.vessel-row').click()
        assert page.locator('#detail h2').inner_text()=='TEST VESSEL <script>'
        page.locator('#search').fill('not present');assert page.locator('.vessel-row').count()==0
        page.locator('#search').fill('');assert page.locator('.vessel-row').count()==1
        (ROOT/'browser-checks').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/'browser-checks/desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ROOT/'browser-checks/mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert not errors,errors
        default_page=browser.new_page()
        default_errors=[];default_page.on('pageerror',lambda error:default_errors.append(str(error)))
        default_origin=json.loads((ROOT/'web/config.json').read_text())['api_base']
        default_page.route(default_origin+'/api/v1/**',mock)
        default_page.goto(url+'/index.html')
        default_page.wait_for_selector('.vessel-row')
        assert default_page.locator('#count').inner_text()=='1'
        assert 'Observations connected' in default_page.locator('#connection-banner').inner_text()
        assert not default_errors,default_errors
        browser.close()
finally:
    server.shutdown();server.server_close();thread.join()
