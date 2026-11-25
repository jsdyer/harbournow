import test from 'node:test';
import assert from 'node:assert/strict';
import {endpoint,typeName,duration,project,filterShips,segmentTrack,csv} from '../web/core.mjs';
test('collector addresses accept HTTPS origins and local development only',()=>{
 assert.equal(endpoint('https://harbour.example.com/'),'https://harbour.example.com');
 assert.equal(endpoint('http://localhost:8090'),'http://localhost:8090');
 for(const value of ['http://example.com','https://name:secret@example.com','https://example.com/api','https://example.com/?key=secret','javascript:alert(1)'])assert.throws(()=>endpoint(value));
});
test('navigation status is not substituted for vessel type',()=>{assert.equal(typeName(70),'Cargo');assert.equal(typeName(52),'Tug');assert.equal(typeName(null),'Unknown');});
test('elapsed display handles invalid and future observations',()=>{assert.equal(duration(-5),'Unknown');assert.equal(duration(3601),'1 h 0 min');});
test('Mercator projection is geographically ordered and bounded near poles',()=>{const middle=project(0,0,2);assert.deepEqual(middle,[512,512]);assert.ok(project(44,-63,2)[1]<512);assert.ok(Number.isFinite(project(90,180,2)[1]));});
test('query searches name and destination and respects stale/type filters',()=>{const ships=[{name:'ONE',mmsi:'123456789',destination:'Halifax',ship_type:70,stale:false},{name:'TWO',ship_type:52,stale:true}];assert.equal(filterShips(ships,'halifax','Cargo',false).length,1);assert.equal(filterShips(ships,'','',false).length,1);assert.equal(filterShips(ships,'','',true).length,2);});
test('tracks break across coverage gaps rather than drawing invented movement',()=>{assert.deepEqual(segmentTrack([{time:1},{time:60},{time:900}]).map(x=>x.length),[2,1]);});
test('CSV protects formula-like vessel names and quotes commas',()=>{assert.equal(csv([['=cmd','name, port','a"b']]),'"\'=cmd","name, port","a""b"');});
