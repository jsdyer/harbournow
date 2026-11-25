import {endpoint, typeName, duration, project, filterShips, segmentTrack, csv} from './core.mjs';
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const storageKey = 'coolcode:harbournow:api';
let config, harbours = [], base = '', harbour, ships = [], events = [], dailyEvents = [], dailyCounts = {}, selected = null, track = [], zoom = 12, center = [0,0], loaded = false, busy = false, requestGeneration = 0;
function text(tag, content, className) { const el = document.createElement(tag); el.textContent = content; if (className) el.className = className; return el; }
function fmt(stamp) {return new Date(stamp * 1000).toLocaleString(undefined, {timeZone: harbour?.timezone || 'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short'});}
function banner(title, message, state='') {const node=$('connection-banner');node.className='notice '+state;node.replaceChildren(text('strong',title),text('p',message));}
async function get(path, signal) { const r = await fetch(base + '/api/v1/' + path, {signal, credentials:'omit', referrerPolicy:'no-referrer'}); if (!r.ok) throw new Error(`The collector returned HTTP ${r.status}.`); const json=await r.json();if(!json || typeof json!=='object') throw new Error('The collector response was not valid.'); return json; }
function resetView(){zoom=harbour.zoom;center=project(...harbour.center,zoom);renderMap();}
function renderMap(){
  if(!harbour) return;
  const map=$('map'), w=map.clientWidth, h=map.clientHeight;
  const x0=center[0]-w/2,y0=center[1]-h/2;
  $('tiles').replaceChildren();
  for(let x=Math.floor(x0/256);x<=Math.floor((x0+w)/256);x++)for(let y=Math.floor(y0/256);y<=Math.floor((y0+h)/256);y++){
    if(y<0||y>=2**zoom) continue;
    const image=document.createElement('img');image.alt='';image.draggable=false;image.src=config.map_tiles.replace('{z}',zoom).replace('{x}',((x%2**zoom)+2**zoom)%2**zoom).replace('{y}',y);image.style.left=(x*256-x0)+'px';image.style.top=(y*256-y0)+'px';$('tiles').append(image);
  }
  const svg=$('overlay');svg.setAttribute('viewBox',`0 0 ${w} ${h}`);svg.replaceChildren();
  const p=([lat,lon])=>{const [x,y]=project(lat,lon,zoom);return[x-x0,y-y0];};
  for(const [points,color,opacity] of [[harbour.boundary,'#123e4b',0],[harbour.anchorage,'#b57612',.1]]){
    const el=document.createElementNS(NS,'polygon');el.setAttribute('points',points.map(p).map(v=>v.join(',')).join(' '));el.setAttribute('fill',color);el.setAttribute('fill-opacity',opacity);el.setAttribute('stroke',color);el.setAttribute('stroke-width','1.5');el.setAttribute('stroke-dasharray','5 5');svg.append(el);
  }
  for(const segment of segmentTrack(track)){
    if(segment.length<2)continue;
    const line=document.createElementNS(NS,'polyline');line.setAttribute('points',segment.map(v=>p([v.lat,v.lon]).join(',')).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#153e8b');line.setAttribute('stroke-width','3');svg.append(line);
  }
  for(const ship of visibleShips()){
    const [x,y]=p([ship.lat,ship.lon]);if(x<0||y<0||x>w||y>h)continue;
    const marker=document.createElementNS(NS,'path');marker.setAttribute('d','M0 -10 L7 8 L0 5 L-7 8 Z');marker.setAttribute('transform',`translate(${x} ${y}) rotate(${ship.heading??ship.course??0})`);marker.setAttribute('fill',ship.stale?'#6d7a7d':ship.state?.anchored?'#b87b19':'#007d84');marker.setAttribute('class','vessel');marker.setAttribute('tabindex','0');marker.setAttribute('role','button');marker.setAttribute('aria-label',ship.name||ship.mmsi);marker.addEventListener('click',()=>selectShip(ship));marker.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectShip(ship);}});if(ship.mmsi===selected)marker.setAttribute('stroke-width','4');const title=document.createElementNS(NS,'title');title.textContent=`${ship.name||ship.mmsi} · ${typeName(ship.ship_type)}`;marker.append(title);svg.append(marker);
  }
  $('map-empty').hidden=loaded&&visibleShips().length>0;
  $('map-empty').textContent=!base?'Connect a collector to see observed vessels.':!loaded?'Waiting for observations.':'No vessels match this view. Try showing older positions.';
}
function visibleShips(){return filterShips(ships,$('search').value,$('type').value,$('stale').checked);}
function renderShips(){
  const shown=visibleShips();$('filtered-count').textContent=`${shown.length} shown`;$('vessels').replaceChildren();
  if(!shown.length)$('vessels').append(text('p',loaded?'No matching observations.':'No observations loaded.','empty'));
  for(const ship of shown){
    const row=text('button','','vessel-row'+(ship.mmsi===selected?' selected':''));row.type='button';row.append(text('strong',ship.name||`MMSI ${ship.mmsi}`),text('span',`${typeName(ship.ship_type)} · ${ship.speed==null?'speed unknown':ship.speed.toFixed(1)+' kn'}`),text('span',`${ship.stale?'Older position · ':''}${duration(Date.now()/1000-ship.position_at)} ago`));if(ship.state?.anchored&&!ship.stale)row.append(text('span',`At anchor · ${duration(Date.now()/1000-ship.state.anchor_since)} observed`,'anchor'));row.addEventListener('click',()=>selectShip(ship));$('vessels').append(row);
  }
  $('count').textContent=loaded?ships.filter(s=>!s.stale).length:'—';$('anchor-count').textContent=loaded?ships.filter(s=>!s.stale&&s.state?.anchored).length:'—';$('entry-count').textContent=loaded?(dailyCounts.entry||0):'—';$('exit-count').textContent=loaded?(dailyCounts.exit||0):'—';renderMap();
}
async function selectShip(ship){
  selected=ship.mmsi;track=[];renderShips();$('detail').hidden=false;const detail=$('detail');detail.replaceChildren(text('h2',ship.name||`Vessel ${ship.mmsi}`));
  const pairs=[['MMSI',ship.mmsi],['Type',typeName(ship.ship_type)],['Speed',ship.speed==null?'Unavailable':ship.speed.toFixed(1)+' knots'],['Course',ship.course==null?'Unavailable':ship.course.toFixed(1)+'°'],['Position observed',fmt(ship.position_at)],['Reported destination',ship.destination||'Not received'],['Callsign',ship.callsign||'Not received'],['Position',`${ship.lat.toFixed(5)}, ${ship.lon.toFixed(5)}`]];
  const dl=document.createElement('dl');for(const [name,value] of pairs){const item=document.createElement('div');item.append(text('dt',name),text('dd',value));dl.append(item);}detail.append(dl,text('p',ship.state?.anchored?`Observed at anchor since ${fmt(ship.state.anchor_since)}. This timer describes continuous observations, not the vessel’s full visit.`:'Select a vessel to see up to 24 hours of recorded track. Lines are broken across observation gaps.','caption'));
  const generation=requestGeneration;
  try{const result=await get(`track?mmsi=${ship.mmsi}`,AbortSignal.timeout(10000));if(selected===ship.mmsi&&generation===requestGeneration){track=Array.isArray(result.track)?result.track:[];renderMap();detail.append(text('p',`${track.length} recorded track points in the past 24 hours.`,'caption'));}}catch{if(generation===requestGeneration)detail.append(text('p','Track could not be loaded. The last vessel details remain available.','caption'));}
}
function renderEvents(){
  const body=$('events');body.replaceChildren();const names={entry:'Observed entry',exit:'Observed exit',anchor_observed:'Anchoring observed',anchor_ended:'Anchoring ended'};
  if(!events.length){const row=document.createElement('tr'),cell=text('td',loaded?'No recorded movements for this period.':'No movement history loaded.');cell.colSpan=3;row.append(cell);body.append(row);}
  for(const event of events){const row=document.createElement('tr');row.append(text('td',event.name||event.mmsi),text('td',names[event.kind]||event.kind),text('td',fmt(event.time)));body.append(row);}
}
async function refresh(){
  if(!base){$('connection-error').textContent='Add your HTTPS collector address below to load observations.';document.querySelector('.settings').open=true;return;}
  if(busy)return;busy=true;$('refresh').disabled=true;const generation=requestGeneration;
  try{
    const signal=AbortSignal.timeout(15000),id=encodeURIComponent(harbour.id),hours=$('period').value;
    const [health, snapshot, movements, day]=await Promise.all([get('health',signal),get(`ships?harbour=${id}`,signal),get(`events?harbour=${id}&hours=${hours}`,signal),hours==='24'?Promise.resolve(null):get(`events?harbour=${id}&hours=24`,signal)]);
    if(generation!==requestGeneration)return;
    if(!Array.isArray(snapshot.ships)||!Array.isArray(movements.events))throw new Error('The server did not return Harbour Now observations.');
    ships=snapshot.ships.filter(s=>/^\d{9}$/.test(s.mmsi)&&Number.isFinite(s.lat)&&Number.isFinite(s.lon)&&Number.isFinite(s.position_at));events=movements.events;dailyEvents=day?day.events:events;dailyCounts=(day||movements).counts||{};loaded=true;
    const previous=$('type').value;$('type').replaceChildren(new Option('All types',''));for(const type of [...new Set(ships.map(s=>typeName(s.ship_type)))].sort())$('type').add(new Option(type,type));$('type').value=previous;
    if(!health.configured)banner('Collector needs its AISStream key','The server is reachable, but its server-side AISSTREAM_API_KEY is not configured.','stale');
    else if(!health.observations_fresh)banner('Waiting for fresh observations',`Feed: ${health.feed?.state||'unknown'}. ${health.last_observation_at?'Last observation '+new Date(health.last_observation_at).toLocaleString()+'.':'No vessel observations have arrived yet.'} Coverage and collection gaps can leave this view incomplete.`,'stale');
    else banner('Observations connected',`Updated ${new Date(snapshot.generated_at).toLocaleTimeString()}. ${health.feed?.state==='connected'?'The collector is receiving AIS observations.':'The stream is reconnecting; recent observations are retained.'}`,'live');
    renderShips();renderEvents();$('connection-error').textContent='';
  }catch(error){if(generation===requestGeneration){banner('Collector unavailable',`${error.name==='TimeoutError'?'The request timed out.':error.message} ${loaded?'Previously loaded observations remain visible with their original times.':'Check the HTTPS address and the server’s allowed origins.'}`,'stale');ships=ships.map(s=>({...s,stale:Date.now()/1000-s.position_at>900}));renderShips();}}
  finally{busy=false;$('refresh').disabled=false;if(generation!==requestGeneration&&base)queueMicrotask(refresh);}
}
async function connect(value,remember){
  const candidate=endpoint(value);if(!candidate)throw new Error('Enter a collector address.');base=candidate;requestGeneration++;loaded=false;ships=[];events=[];dailyEvents=[];track=[];selected=null;$('detail').hidden=true;
  const generation=requestGeneration;
  const result=await get('harbours',AbortSignal.timeout(12000));if(generation!==requestGeneration)return;if(!Array.isArray(result.harbours)||!result.harbours.length)throw new Error('This server does not expose a Harbour Now harbour list.');
  for(const option of $('period').options)option.disabled=Number(option.value)>Number(result.retention_days||30)*24;
  if($('period').selectedOptions[0]?.disabled)$('period').value='24';
  harbours=result.harbours;const previous=harbour?.id;$('harbour').replaceChildren();for(const h of harbours)$('harbour').add(new Option(h.name,h.id));harbour=harbours.find(h=>h.id===previous)||harbours[0];$('harbour').value=harbour.id;$('boundary-note').textContent=harbour.boundary_note;resetView();
  if(remember){try{localStorage.setItem(storageKey,base);}catch{}}else{try{localStorage.removeItem(storageKey);}catch{}}
  $('endpoint').value=base;await refresh();
}
$('connection-form').addEventListener('submit',async e=>{e.preventDefault();try{await connect($('endpoint').value,$('remember').checked);}catch(error){$('connection-error').textContent=error.message;banner('Unable to connect',error.message,'stale');}});
$('disconnect').addEventListener('click',()=>{try{localStorage.removeItem(storageKey);}catch{}base='';requestGeneration++;loaded=false;ships=[];events=[];dailyEvents=[];track=[];selected=null;$('endpoint').value='';$('remember').checked=false;$('detail').hidden=true;banner('Collector not connected','Connect an HTTPS Harbour Now collector to see observations. No example ships are shown as live data.');renderShips();renderEvents();});
$('harbour').addEventListener('change',()=>{requestGeneration++;harbour=harbours.find(h=>h.id===$('harbour').value);ships=[];events=[];dailyEvents=[];track=[];selected=null;loaded=false;$('detail').hidden=true;$('boundary-note').textContent=harbour.boundary_note;resetView();renderShips();renderEvents();refresh();});
for(const id of ['search','type','stale'])$(id).addEventListener(id==='search'?'input':'change',renderShips);
$('refresh').addEventListener('click',refresh);$('period').addEventListener('change',refresh);$('recenter').addEventListener('click',resetView);
for(const [id,delta]of [['zoom-in',1],['zoom-out',-1]])$(id).addEventListener('click',()=>{const next=Math.max(9,Math.min(16,zoom+delta));center=center.map(v=>v*2**(next-zoom));zoom=next;renderMap();});
let drag=null;$('map').addEventListener('pointerdown',e=>{if(e.target.closest('a')||e.target.classList?.contains('vessel'))return;drag={x:e.clientX,y:e.clientY,center:[...center]};$('map').setPointerCapture(e.pointerId);});$('map').addEventListener('pointermove',e=>{if(drag){center=[drag.center[0]-e.clientX+drag.x,drag.center[1]-e.clientY+drag.y];renderMap();}});$('map').addEventListener('pointerup',()=>{drag=null;});$('map').addEventListener('pointercancel',()=>{drag=null;});
$('export').addEventListener('click',()=>{const rows=[['MMSI','Vessel','Observation','UTC time','Harbour'],...events.map(e=>[e.mmsi,e.name,e.kind,new Date(e.time*1000).toISOString(),harbour.name])];const url=URL.createObjectURL(new Blob([csv(rows)],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`harbournow-${harbour.id}-movements.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
new ResizeObserver(()=>renderMap()).observe($('map'));
try{
  [config,{harbours}]=await Promise.all([fetch('config.json').then(r=>r.json()),fetch('harbours.json').then(r=>r.json())]);
  harbour=harbours.find(h=>h.id===config.default_harbour)||harbours[0];$('harbour').replaceChildren();for(const h of harbours)$('harbour').add(new Option(h.name,h.id));$('harbour').value=harbour.id;$('boundary-note').textContent=harbour.boundary_note;resetView();
  let saved='';try{saved=localStorage.getItem(storageKey)||'';}catch{}
  if(saved||config.api_base){$('remember').checked=Boolean(saved);await connect(saved||config.api_base,Boolean(saved));}
  else if(location.hostname!=='coolcode.ca'&&location.hostname!=='jsdyer.github.io'&&location.pathname==='/'){
    // The same Docker service also serves the frontend; an unavailable route stays offline.
    try{await connect(location.origin,false);}catch{}
  }
  setInterval(()=>{if(base&&!document.hidden)refresh();},Math.max(30,config.refresh_seconds)*1000);
}catch(error){banner('Configuration could not be loaded',error.message,'stale');}
