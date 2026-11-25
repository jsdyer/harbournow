import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from collector.model import normalize, inside, parse_time
from collector.store import Store
from collector.app import BoundedHTTPServer, handler_factory, load_config, maintenance, collect, subscription_compressed, stream_failure_reason, StreamFailure

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {"retention_days": 30,"stale_seconds":900,"transition_gap_seconds":600,"track_interval_seconds":60,"harbours":[{"id":"test","name":"Test Harbour","timezone":"UTC","center":[0,0],"zoom":12,"subscription_bbox":[[-3,-3],[3,3]],"boundary":[[-1,-1],[-1,1],[1,1],[1,-1]],"anchorage":[[-0.5,-0.5],[-0.5,0.5],[0.5,0.5],[0.5,-0.5]],"boundary_note":"Test geometry"}]}


def point(stamp,lat=0,lon=0,speed=5):
    return {"mmsi":"123456789","name":"Test ship","lat":lat,"lon":lon,"speed":speed,"position_at":stamp,"observed_at":stamp}


class NormalizationTests(unittest.TestCase):
    def envelope(self):
        return {"MessageType":"PositionReport","MetaData":{"MMSI":123456789,"ShipName":"SHIP@@@@"},"Message":{"PositionReport":{"Valid":True,"Latitude":44.6,"Longitude":-63.5,"Sog":102.3,"Cog":360,"TrueHeading":511}}}

    def test_sentinel_values_are_unknown(self):
        value=normalize(self.envelope(),10000)
        self.assertEqual(value["name"],"SHIP")
        for key in ["speed","course","heading"]:self.assertIsNone(value[key])

    def test_bad_positions_and_mmsi_are_rejected(self):
        for bad in [91,float('nan'),True]:
            e=self.envelope();e["Message"]["PositionReport"]["Latitude"]=bad
            self.assertIsNone(normalize(e,10000))
        e=self.envelope();e["MetaData"]["MMSI"]="123";self.assertIsNone(normalize(e,10000))

    def test_invalid_flag_and_non_vessel_messages_are_rejected(self):
        e=self.envelope();e["Message"]["PositionReport"]["Valid"]=False;self.assertIsNone(normalize(e,10000))
        e=self.envelope();e["MessageType"]="BaseStationReport";self.assertIsNone(normalize(e,10000))

    def test_static_message_preserves_missing_fields(self):
        e={"MessageType":"StaticDataReport","MetaData":{"MMSI":123456789},"Message":{"StaticDataReport":{"ReportA":{"Name":"NEW NAME"}}}}
        result=normalize(e,10000);self.assertEqual(result["name"],"NEW NAME");self.assertNotIn("lat",result);self.assertNotIn("destination",result)

    def test_timestamp_validation(self):
        self.assertEqual(parse_time(None,10000),10000)
        self.assertIsNone(parse_time("not a date",10000))
        self.assertIsNone(parse_time("2030-01-01T00:00:00Z",10000))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:',config())
    def tearDown(self):self.store.db.close()
    def state(self):return self.store.snapshot('test',11000)[0]['state']

    def test_initial_discovery_is_not_arrival(self):
        self.store.ingest(point(10000));self.assertEqual(self.store.events('test',0),[])

    def test_crossing_requires_two_reports_and_bounce_does_not_count(self):
        for p in [point(10000,lat=2),point(10060),point(10120,lat=2)]:self.store.ingest(p)
        self.assertEqual(self.store.events('test',0),[])
        self.store.ingest(point(10180));self.store.ingest(point(10240))
        self.assertEqual([e['kind'] for e in self.store.events('test',0)],['entry'])

    def test_gap_does_not_invent_arrival_or_anchor_dwell(self):
        self.store.ingest(point(10000,lat=2));self.store.ingest(point(11000,speed=0));self.store.ingest(point(11120,speed=0))
        self.assertEqual([e['kind'] for e in self.store.events('test',0)],['anchor_observed'])
        self.assertEqual(self.state()['anchor_since'],11000)
        self.store.ingest(point(12000,speed=0));self.assertFalse(self.state()['anchored'])

    def test_boundary_change_resets_without_fake_crossing(self):
        self.store.ingest(point(10000,lat=2))
        self.store.config['harbours'][0]['boundary']=[[-2.5,-2.5],[-2.5,2.5],[2.5,2.5],[2.5,-2.5]]
        self.store.ingest(point(10060,lat=2));self.store.ingest(point(10120,lat=2))
        self.assertEqual(self.store.events('test',0),[])

    def test_anchor_requires_dwell_and_zone(self):
        self.store.ingest(point(10000,speed=0));self.store.ingest(point(10060,speed=0));self.assertFalse(self.state()['anchored'])
        self.store.ingest(point(10120,speed=0));self.assertTrue(self.state()['anchored'])
        self.store.ingest(point(10180,lat=.8,speed=0));self.assertFalse(self.state()['anchored'])

    def test_out_of_order_and_out_of_area_are_rejected(self):
        self.store.ingest(point(10000));self.assertFalse(self.store.ingest(point(9999)))
        self.assertFalse(self.store.ingest(point(10060,lat=50)))

    def test_track_sampling_and_retention(self):
        for stamp in [10000,10001,10059,10060]:self.store.ingest(point(stamp))
        self.assertEqual(len(self.store.track('123456789',0)),2)
        self.store.prune(10000+31*86400);self.assertEqual(self.store.track('123456789',0),[])
        self.assertEqual(self.store.snapshot('test',10000+31*86400),[])

    def test_static_data_does_not_make_position_fresh(self):
        self.store.ingest(point(10000));self.store.ingest({'mmsi':'123456789','observed_at':12000,'static_at':12000,'destination':'Halifax'})
        ship=self.store.snapshot('test',12000)[0];self.assertEqual(ship['position_at'],10000);self.assertTrue(ship['stale']);self.assertEqual(ship['destination'],'Halifax')

    def test_third_harbour_is_derived_from_config(self):
        third=copy.deepcopy(self.store.config['harbours'][0]);third['id']='third';self.store.config['harbours'].append(third)
        self.store.ingest(point(10000));self.assertEqual(len(self.store.snapshot('third',10000)),1)

    def test_database_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'test.sqlite');a=Store(path,config());a.ingest(point(10000));a.db.close();b=Store(path,config());self.assertEqual(len(b.snapshot('test',10000)),1);b.db.close()

    def test_maintenance_prunes_without_ingestion(self):
        self.store.ingest(point(10000))
        async def run():
            stop=asyncio.Event();task=asyncio.create_task(maintenance(self.store,stop));await asyncio.sleep(.01);stop.set();await task
        asyncio.run(run());self.assertEqual(self.store.track('123456789',0),[])


class ConfigTests(unittest.TestCase):
    def test_actual_config_loads(self):self.assertEqual(len(load_config(ROOT/'config/harbours.json')['harbours']),2)
    def test_non_finite_and_boolean_coordinates_rejected(self):
        for value in [float('nan'),True]:
            c=config();c['harbours'][0]['center'][0]=value
            with tempfile.NamedTemporaryFile(mode='w',suffix='.json') as file:
                json.dump(c,file);file.flush()
                with self.assertRaises(ValueError):load_config(file.name)


class ConnectionTests(unittest.TestCase):
    def test_compressed_subscription_and_ingestion_without_exposing_key(self):
        store=Store(':memory:',config())
        sent=[]
        async def run():
            stop=asyncio.Event()
            class Socket:
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                async def send(self,value):sent.append(json.loads(value))
                def __aiter__(self):return self.messages()
                async def messages(self):
                    yield (ROOT/'tests/fixtures/subscription-confirmation.json').read_bytes()
                    yield json.dumps({'MessageType':'PositionReport','MetaData':{'MMSI':123456789},'Message':{'PositionReport':{'Valid':True,'Latitude':0,'Longitude':0,'Sog':1}}}).encode()
                    stop.set()
            with patch('websockets.asyncio.client.connect',return_value=Socket()) as mock:
                with patch('collector.app.asyncio.sleep',side_effect=AssertionError('A valid confirmation must not trigger reconnect backoff')):
                    await collect(store,'TEST_SECRET_NOT_REAL',stop)
                self.assertEqual(mock.call_args.kwargs['compression'],'deflate')
                self.assertLessEqual(mock.call_args.kwargs['max_size'],262144)
        asyncio.run(run())
        self.assertEqual(sent[0]['APIKey'],'TEST_SECRET_NOT_REAL')
        self.assertEqual(len(sent[0]['BoundingBoxes']),1)
        self.assertEqual(len(store.snapshot('test',time.time())),1)
        self.assertTrue(store.metadata()['connection']['compression_confirmed'])
        self.assertNotIn('TEST_SECRET_NOT_REAL',json.dumps(store.metadata()))
        store.db.close()

    def test_legacy_confirmation_is_supported_but_missing_or_false_is_not(self):
        self.assertTrue(subscription_compressed({'Message':{'SubscriptionConfirmation':{'CompressionEnabled':True}}}))
        for message, code in [({'Message':{'CompressionEnabled':False}},'compression_not_confirmed'),({'Message':{}},'invalid_confirmation'),({'Message':{'CompressionEnabled':'true'}},'invalid_confirmation')]:
            with self.assertRaises(StreamFailure) as caught:subscription_compressed(message)
            self.assertEqual(caught.exception.code,code)

    def test_error_codes_never_echo_provider_payloads_or_secret_text(self):
        for exception, expected in [(StreamFailure('subscription_rejected'),'subscription_rejected'),(StreamFailure('compression_not_confirmed'),'compression_not_confirmed'),(OSError('SECRET_KEY=private upstream payload'),'network_error'),(TimeoutError('private'),'connection_timeout'),(RuntimeError('private'),'collector_error')]:
            code,reason=stream_failure_reason(exception)
            self.assertEqual(code,expected)
            self.assertNotIn('private',reason)
            self.assertNotIn('SECRET_KEY',reason)

    def test_provider_rejection_and_bad_compression_record_distinct_redacted_health(self):
        for envelope, expected in [({'error':'SECRET_KEY=must_not_leak'},'subscription_rejected'),({'MessageType':'SubscriptionConfirmation','Message':{'CompressionEnabled':False}},'compression_not_confirmed')]:
            store=Store(':memory:',config())
            async def run():
                stop=asyncio.Event()
                class Socket:
                    async def __aenter__(self):return self
                    async def __aexit__(self,*args):pass
                    async def send(self,value):pass
                    def __aiter__(self):return self.messages()
                    async def messages(self):yield json.dumps(envelope).encode()
                async def finish_backoff(_):stop.set()
                with patch('websockets.asyncio.client.connect',return_value=Socket()),patch('collector.app.asyncio.sleep',side_effect=finish_backoff):
                    await collect(store,'PRIVATE_KEY',stop)
            asyncio.run(run())
            state=store.metadata()['connection']
            self.assertEqual(state['reason_code'],expected)
            self.assertNotIn('SECRET_KEY',json.dumps(state));self.assertNotIn('PRIVATE_KEY',json.dumps(state))
            store.db.close()


class APITests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:',config());self.store.meta('configured',False)
        self.server=BoundedHTTPServer(('127.0.0.1',0),handler_factory(self.store,{'https://coolcode.ca'},ROOT/'web'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_address[1])
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.store.db.close()
    def fetch(self,path,origin=None):return urlopen(Request(self.base+path,headers={'Origin':origin} if origin else {}),timeout=3)
    def test_health_is_honest_without_key(self):
        with self.fetch('/api/v1/health') as r:
            data=json.load(r);self.assertEqual(data['service'],'ok');self.assertFalse(data['configured']);self.assertFalse(data['observations_fresh'])
    def test_cors_allows_only_configured_origin(self):
        with self.fetch('/api/v1/health','https://coolcode.ca') as r:self.assertEqual(r.headers['Access-Control-Allow-Origin'],'https://coolcode.ca')
        with self.assertRaises(HTTPError) as error:self.fetch('/api/v1/health','https://evil.example')
        self.assertEqual(error.exception.code,403)
    def test_bad_query_and_traversal(self):
        for path in ['/api/v1/track?mmsi=1','/api/v1/events?hours=999999','/api/v1/ships?harbour=missing','/api/v1/ships?harbour=test&harbour=test']:
            with self.assertRaises(HTTPError) as error:self.fetch(path)
            self.assertEqual(error.exception.code,400)
        for path in ['/.env','/../README.md','/config/harbours.json','/collector/app.py']:
            with self.assertRaises(HTTPError) as error:self.fetch(path)
            self.assertEqual(error.exception.code,404)


if __name__=='__main__':unittest.main()
