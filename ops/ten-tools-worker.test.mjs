import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const load = async name => {
  const code = await readFile(new URL(name, import.meta.url), 'utf8');
  return (await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))).default;
};
const base = await load('./ten-tools-worker-base.js');
const worker = await load('./ten-tools-worker.js');
const manifest = JSON.parse(await readFile(new URL('./ten-tools-integration.json',import.meta.url),'utf8'));
const request = path => new Request('https://worker.invalid'+path,{headers:{Origin:'https://coolcode.ca'}});

test('all existing and new registered IDs survive the combined Worker', async () => {
  const old = await (await base.fetch(request('/registry'),{})).json();
  const current = await (await worker.fetch(request('/registry'),{})).json();
  assert.deepEqual(current, old);
  assert.equal(new Set(current.tool_ids).size,current.tool_ids.length);
  for(const id of manifest.repository_scope) assert.ok(current.tool_ids.includes(id),id);
});

test('status adds only new configuration booleans and never reveals secrets', async () => {
  const env={TMDB_READ_ACCESS_TOKEN:'private-tmdb-sentinel',ADSBLOL_API_KEY:'private-flight-sentinel'};
  const old=await(await base.fetch(request('/api/status'),env)).json();
  const response=await worker.fetch(request('/api/status'),env), raw=await response.text(), current=JSON.parse(raw);
  assert.equal(response.status,200);
  for(const [key,value] of Object.entries(old.configured)) assert.equal(current.configured[key],value,key);
  assert.equal(current.configured.screenplaces,true);
  assert.equal(current.configured.planehere,true);
  assert.equal(current.configured.planehere_key,true);
  for(const secret of Object.values(env)) assert.equal(raw.includes(secret),false);
  const anonymous=await(await worker.fetch(request('/api/status'),{})).json();
  assert.equal(anonymous.configured.planehere,true);
  assert.equal(anonymous.configured.planehere_key,false);
});

test('combined API preserves origin, method and preflight boundaries', async () => {
  for(const path of ['/api/screenplaces/title?wikidata=Q1','/api/planehere/nearby?lat=44.65&lon=-63.57&radius=25']) {
    const foreign=await worker.fetch(new Request('https://worker.invalid'+path,{headers:{Origin:'https://unrelated.invalid'}}),{});
    assert.equal(foreign.status,403);
    assert.equal(foreign.headers.get('Access-Control-Allow-Origin'),null);
    const post=await worker.fetch(new Request('https://worker.invalid'+path,{method:'POST',headers:{Origin:'https://coolcode.ca'}}),{});
    assert.equal(post.status,405);
    const options=await worker.fetch(new Request('https://worker.invalid'+path,{method:'OPTIONS',headers:{Origin:'https://coolcode.ca'}}),{});
    assert.equal(options.status,204);
    assert.equal(options.headers.get('Access-Control-Allow-Origin'),'https://coolcode.ca');
  }
});

test('release manifest hashes the exact dashboard-pasteable source', async () => {
  for(const [file,key] of [['ten-tools-worker.js','worker_sha256'],['ten-tools-worker-base.js','baseline_sha256']]) {
    const body=await readFile(new URL(file,import.meta.url));
    assert.equal(createHash('sha256').update(body).digest('hex'),manifest[key]);
  }
  assert.equal(manifest.existing_repositories_modified,false);
  assert.equal(manifest.worker_deployed,false);
});
