'use strict';
const $=id=>document.getElementById(id);let demo=false,token='',connected=false,selected=null,busy=false;let sessionActive=false,lastUpdated=0;
const titles={games:['Games','Your game folders, one shortcut away.'],repositories:['Repository updates','Preset projects and your saved repositories.'],overview:['Console overview','A clear view of your console, close to home.'],library:['Applications','Discover what’s on your console. Launch with confidence.'],plugins:['Plugin adapters','A dedicated home for console-side extensions.'],activity:['Session activity','A record of this session’s connection and launch actions.']};
function notice(t){$('notice').textContent=t}function log(t){if($('events').firstElementChild?.textContent==='No actions yet.')$('events').replaceChildren();let li=document.createElement('li'),time=document.createElement('time');time.textContent=new Date().toLocaleTimeString();li.append(time,document.createTextNode(t));$('events').prepend(li)}
function view(v){hideCpuKey();document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==v);document.querySelectorAll('nav button').forEach(e=>e.classList.toggle('active',e.dataset.view===v));$('crumb').textContent=v==='library'?'Applications':v[0].toUpperCase()+v.slice(1);$('page-title').replaceChildren(document.createTextNode(titles[v][0]),Object.assign(document.createElement('span'),{textContent:'.'}));$('page-description').textContent=titles[v][1]}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{view(b.dataset.view);if(b.dataset.view==='games')task(loadGames)};for(const b of document.querySelectorAll('[data-goto]'))b.onclick=()=>view(b.dataset.goto);
for(const b of document.querySelectorAll('.close'))b.onclick=()=>b.closest('dialog').close();
async function api(action,data={}){const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(data),signal:AbortSignal.timeout(45000)});let j;try{j=await r.json()}catch{throw Error('Open the app using the URL printed by your local bridge.')}if(!r.ok)throw Error(j.error||'The bridge could not complete this action.');return j}
async function task(fn){if(busy)return;busy=true;try{await fn()}catch(e){notice(e.message);if(!connected){$('connection-label').textContent='Not connected';$('mode').textContent='OFFLINE';$('metric-status').textContent='Offline';$('console-name').textContent='Connection required';$('console-note').textContent='Check the bridge and reconnect.';$('footer-mode').textContent='Local connection required'}log('Action failed: '+e.message)}finally{busy=false}}
function status(s){connected=true;sessionActive=true;$('connection-label').textContent=demo?'Demo console':'Console connected';$('console-name').textContent=demo?'Demo workspace':'Console connected';$('console-note').textContent=demo?'Sample data only. No console commands are sent.':'Neighborhood connection is ready.';$('mode').textContent=demo?'DEMO':'CONNECTED';$('metric-status').textContent=demo?'Demo':'Connected';$('metric-type').textContent=s.type||'Unavailable';$('metric-kernel').textContent=s.kernel||'Unavailable';$('metric-drives').textContent=s.drives.length;$('footer-mode').textContent=demo?'Demo · sample data':'Local session · private data excluded';$('connect').textContent='Change connection';
  const prev=$('drive').value,oldPath=$('path').value;$('drive').replaceChildren();for(const d of s.drives){const o=document.createElement('option');o.value=d;o.textContent=d;$('drive').append(o)}if(s.drives.includes(prev)){$('drive').value=prev;$('path').value=oldPath}else $('path').value=$('drive').value;
  syncGameDrives(s.drives);
  renderTelemetry(s);
}
function renderTelemetry(s){
  lastUpdated=Date.now();document.querySelector('.live-strip').classList.remove('stale');$('quick-status').textContent=demo?'Demo':'Connected';
  let count=0;for(const key of ['cpu','gpu','edram','motherboard']){const v=s.temperatures?.[key],valid=typeof v==='number'&&Number.isFinite(v)&&v>0&&v<=125;if(valid)count++;const text=valid?v.toFixed(1)+' °C':'Unavailable';$('temp-'+key).textContent=text;$('temp-'+key+'-note').textContent=valid?(demo?'Sample sensor':'Reported sensor'):'Sensor not supported';if(key==='cpu'||key==='gpu')$('quick-'+key).textContent=valid?text:'—';}
  const t=s.current_title||{},path=t.executable||'',name=t.name||path.split(/[\\/]/).filter(Boolean).pop()||'Unavailable';$('current-title').textContent=name;$('quick-title').textContent=name;$('current-path').textContent=path||'Running executable is not reported by this adapter.';$('current-title-id').textContent=t.title_id||'Unavailable';
  $('telemetry-state').textContent=demo?'DEMO / SAMPLE DATA':count===4?'LIVE READINGS':count?'PARTIAL SENSOR SUPPORT':'SENSORS UNAVAILABLE';$('telemetry-note').textContent=demo?'Sample data only. Demo readings are not taken from a console.':count===4?'Readings refresh every 10 seconds while this page is visible.':'Temperatures need compatible JRPC consolefeatures support. Missing readings stay unavailable; status refreshes every 10 seconds.';updateAge();
}
function clearTelemetry(reason){lastUpdated=0;document.querySelector('.live-strip').classList.add('stale');$('quick-status').textContent=reason;$('quick-title').textContent='Unavailable';$('quick-cpu').textContent='—';$('quick-gpu').textContent='—';$('quick-age').textContent='Not current';$('current-title').textContent='Unavailable';$('current-path').textContent='No current reading.';$('current-title-id').textContent='—';$('telemetry-state').textContent=reason.toUpperCase();for(const key of ['cpu','gpu','edram','motherboard']){$('temp-'+key).textContent='—';$('temp-'+key+'-note').textContent='No current reading';}}
function updateAge(){if(!lastUpdated)return;const seconds=Math.floor((Date.now()-lastUpdated)/1000);$('quick-age').textContent=demo?'Sample':seconds<2?'Just now':seconds+'s ago';document.querySelector('.live-strip').classList.toggle('stale',!demo&&seconds>30);if(!demo&&seconds>30){$('quick-status').textContent='Stale';$('telemetry-state').textContent='STALE / LAST READING';}}
async function refreshStatus(){try{status(await api('status'))}catch(e){connected=false;clearTelemetry('Unavailable');$('connection-label').textContent='Connection unavailable';$('metric-status').textContent='Unavailable';$('mode').textContent='UNAVAILABLE';$('console-note').textContent='Status refresh failed. Retrying while this page is visible.';$('telemetry-note').textContent='Console could not be reached. Last readings have been cleared.';throw e}}
setInterval(updateAge,1000);
setInterval(()=>{if(sessionActive&&!demo&&!busy&&!document.hidden&&!document.querySelector('dialog[open]'))task(refreshStatus)},10000);

function connectDialog(){hideCpuKey();$('hosted-help').hidden=location.hostname==='127.0.0.1'||location.hostname==='localhost'||/^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(location.hostname);$('connection-dialog').showModal()}
$('connect').onclick=connectDialog;$('connection-open').onclick=connectDialog;
$('connection-form').onsubmit=e=>{e.preventDefault();task(async()=>{token=$('token').value.trim();demo=false;connected=false;sessionActive=false;selected=null;resetGames();clearTelemetry('Connecting');$('connection-label').textContent='Connecting…';$('mode').textContent='CONNECTING';$('metric-status').textContent='Connecting';$('metric-type').textContent='—';$('metric-kernel').textContent='—';$('metric-drives').textContent='—';$('files').replaceChildren();const s=await api('connect',{target:$('target').value.trim()});status(s);$('connection-dialog').close();notice('Connected. Choose a discovered storage root to browse applications.');log('Neighborhood connection established.');$('token').value='';})};
$('demo').onclick=()=>{if(busy)return;hideCpuKey();demo=true;token='';selected=null;resetGames();status({temperatures:{cpu:58,gpu:61,edram:55,motherboard:36},current_title:{name:'Nebulah Dash (sample)',executable:'DemoUSB:\\Nebulah\\default.xex',title_id:'00000000'},type:'Retail (sample)',kernel:'2.0.17559.0',drives:['DemoDisk:\\','DemoUSB:\\']});notice('Demo mode — sample data, no connection to a real console.');log('Demo mode enabled.');};
$('drive').onchange=()=>{$('path').value=$('drive').value;task(browse)};
const samples=[{name:'Games',directory:true},{name:'Homebrew',directory:true},{name:'Plugins',directory:true},{name:'Nebulah',directory:true}];
function demoFiles(path){if(/^[^\\]+\\$/.test(path))return samples;if(/Games/i.test(path))return [{name:'default.xex',size:12582912},{name:'default_mp.xex',size:13631488}];if(/Plugins/i.test(path))return [{name:'sample-plugin.xex',size:524288}];return [{name:'default.xex',size:2097152},{name:'readme.txt',size:2048}]}
async function browse(){if(!connected)throw Error('Connect a console or choose Explore demo first.');const path=$('path').value;const r=demo?{files:demoFiles(path)}:await api('browse',{path});$('files').replaceChildren();if(!r.files.length){const d=document.createElement('div');d.className='empty-state';d.textContent='This directory is empty.';$('files').append(d)}for(const f of r.files){const row=document.createElement('div');row.className='file-row';const icon=document.createElement('span');icon.className='file-icon';icon.textContent=f.directory?'▱':'◇';const meta=document.createElement('div'),name=document.createElement('b'),sub=document.createElement('small');name.textContent=f.name;sub.textContent=f.directory?'Directory':Math.ceil((f.size||0)/1024).toLocaleString()+' KB';meta.append(name,sub);row.append(icon,meta);if(f.directory||/\.xex$/i.test(f.name)){const b=document.createElement('button');b.className='secondary';b.textContent=f.directory?'Open →':'Inspect XEX';b.onclick=()=>task(async()=>{const full=path.replace(/\\?$/,'\\')+f.name;if(f.directory){$('path').value=full+'\\';await browse()}else await inspect(full)});row.append(b)}$('files').append(row)}log(demo?'Demo directory opened.':'Console directory opened.');}
$('browse').onclick=()=>task(browse);$('up').onclick=()=>task(async()=>{const p=$('path').value.replace(/\\$/,'');const i=p.lastIndexOf('\\');if(i>=0){$('path').value=p.slice(0,i+1);await browse()}});
async function inspect(path,buildId=null){selected=null;$('launch').disabled=true;$('launch-path').textContent=path;$('validation').textContent='Reading and checking XEX…';if(!$('launch-dialog').open)$('launch-dialog').showModal();try{if(!buildId){$('expected-build').replaceChildren(Object.assign(document.createElement('option'),{value:'',textContent:'Identify by hash (no expected build)'}));if(!demo){const catalog=await api('registry/list');for(const b of catalog.builds){const o=document.createElement('option');o.value=b.id;o.textContent=b.project+' / '+b.version+' / '+b.filename+' ['+b.state+']';$('expected-build').append(o)}}}const v=demo?{valid:true,plugin:/Plugins/i.test(path),hash:'Demo only — no file was read',ticket:'demo',checks:['XEX2 header (sample)','Header bounds (sample)','Application module (sample)']}:await api('validate',{path,build_id:buildId});selected={...v,path};$('validation').replaceChildren();for(const text of [...v.checks,'SHA-256: '+v.hash,v.plugin?'Plugin module: runtime loader required.':'Application candidate. Structural checks passed.']){const d=document.createElement('div');d.className='validation-row mono';d.textContent=text;$('validation').append(d)}if(!demo){const report=v.verification||{status:'unknown'},row=document.createElement('div');row.className='validation-row mono';row.textContent='Build registry: '+report.status+(report.discrepancies?.length?' — '+report.discrepancies.join(' '):'')+(report.status==='unknown'?' — No reviewed reference. This file has only passed structural checks.':'');$('validation').append(row);if(report.expected){const expected=document.createElement('div');expected.className='validation-row mono';expected.textContent='Expected: '+report.expected.sha256+' / '+report.expected.size+' bytes. Actual: '+v.hash+' / '+v.size+' bytes.';$('validation').append(expected)}for(const match of report.matches||[]){const detail=document.createElement('div');detail.className='validation-row mono';detail.textContent=match.project+' / '+match.version+' / '+match.state+' / '+match.repository+' @ '+match.commit;$('validation').append(detail)}}
if(v.game_verification){const badge=gameBadge(v.game_verification);$('validation').append(badge);}
$('launch').disabled=!v.valid||v.plugin||(!demo&&!v.ticket);$('launch').textContent=demo?'Simulate launch →':'Launch application →';log(demo?'Demo XEX inspection completed.':'XEX structural inspection completed.')}catch(e){$('validation').textContent=e.message;throw e}}
$('launch').onclick=()=>task(async()=>{if(!selected||!selected.valid||selected.plugin)return;$('launch').disabled=true;if(!demo){await api('launch',{ticket:selected.ticket});clearTelemetry('Launching');connected=false;}$('launch-dialog').close();notice(demo?'Simulated launch complete. Nothing was sent to a console.':'Launch command accepted. The console may disconnect while the title starts.');log(demo?'Launch simulated.':'Launch command accepted.');selected=null});
$('refresh').onclick=()=>task(async()=>{if(!sessionActive)throw Error('Connect your console first.');if(!demo)await refreshStatus();notice(demo?'Demo data refreshed.':'Console status refreshed.');});$('clear').onclick=()=>{$('events').replaceChildren();log('Activity cleared.');};

// CPU keys are only read following fresh explicit consent. Never log the response.
let privateTicket=null,privateGeneration=0,privateTimer=null;
function clearCpuKey(){privateGeneration++;privateTicket=null;clearTimeout(privateTimer);$('cpu-key-value').textContent='';$('cpu-key-result').hidden=true;$('cpu-key-consent').hidden=false;$('cpu-key-confirm').disabled=false;$('cpu-key-message').textContent='';$('cpu-key-cancel').textContent='Cancel';}
function hideCpuKey(){clearCpuKey();if($('cpu-key-dialog').open)$('cpu-key-dialog').close();}
$('cpu-key-dialog').addEventListener('close',clearCpuKey);
$('cpu-key-cancel').onclick=hideCpuKey;
document.addEventListener('visibilitychange',()=>{if(document.hidden)hideCpuKey()});
window.addEventListener('pagehide',hideCpuKey);
$('cpu-key-open').onclick=()=>task(async()=>{
  if(demo||!connected)throw Error('Connect a real console before requesting private information.');
  clearCpuKey();const generation=privateGeneration;
  const consent=await api('cpu-key/prepare'); // No private console read.
  if(generation!==privateGeneration||document.hidden)return;
  privateTicket=consent.confirmation_ticket;$('cpu-key-dialog').showModal();
  privateTimer=setTimeout(()=>{privateTicket=null;$('cpu-key-confirm').disabled=true;$('cpu-key-message').textContent='Confirmation expired. Close and request again.';},60000);
});
$('cpu-key-confirm').onclick=async()=>{
  if(busy||!privateTicket||demo||!connected)return;
  const ticket=privateTicket,generation=privateGeneration;privateTicket=null;clearTimeout(privateTimer);busy=true;
  $('cpu-key-confirm').disabled=true;$('cpu-key-message').textContent='Reading CPU key…';
  try{
    const result=await api('cpu-key/reveal',{confirmed:true,confirmation_ticket:ticket});
    if(generation!==privateGeneration||document.hidden||!$('cpu-key-dialog').open)return;
    if(!/^[0-9A-F]{32}$/.test(result.cpu_key||''))throw Error('Invalid response');
    $('cpu-key-value').textContent=result.cpu_key;$('cpu-key-consent').hidden=true;$('cpu-key-result').hidden=false;$('cpu-key-message').textContent='';$('cpu-key-cancel').textContent='Hide and close';
    privateTimer=setTimeout(hideCpuKey,60000);
  }catch{
    if(generation===privateGeneration)$('cpu-key-message').textContent='CPU key could not be read. Check compatible JRPC support, then close and confirm again.';
  }finally{busy=false;}
};

$('expected-build').onchange=()=>task(()=>inspect($('launch-path').textContent,$('expected-build').value||null));

function detail(parent,label,value){const row=document.createElement('p');row.className='small';row.textContent=label+': '+(value===null||value===undefined?'Unavailable':value);parent.append(row)}
function renderRepository(parent,entry,result){const card=document.createElement('article');card.className='repo-card';const heading=document.createElement('h3'),link=document.createElement('a');link.href='https://github.com/'+entry.repository;link.target='_blank';link.rel='noopener noreferrer';link.textContent=entry.repository;heading.append(link);card.append(heading);detail(card,'Tracking',entry.origin);if(result){detail(card,'Check result',result.status);detail(card,'Checked at',result.checked_at);if(result.error)detail(card,'Error',result.error);const data=result.status==='unavailable'?result.last_success:result;if(data){if(result.status==='unavailable')detail(card,'Data freshness','Previous successful check — not current');for(const [label,key] of [['New push since prior check','push_changed'],['Owner','owner'],['Stars','stars'],['Last repo push','last_push'],['Metadata updated','metadata_updated'],['Default branch','branch'],['Revision','revision'],['Commit date','commit_date'],['License','license'],['Archived','archived'],['Forks','forks'],['Open issues','open_issues'],['Description','description']])detail(card,label,data[key]);detail(card,'Latest stable release',data.release?.tag_name||data.release_status);if(data.release)detail(card,'Release published',data.release.published_at)}}else detail(card,'Check result','Not checked yet');if(entry.origin==='saved'){const remove=document.createElement('button');remove.className='secondary';remove.textContent='Remove saved repository';remove.onclick=()=>task(async()=>{await api('repos/remove',{repository:entry.repository});await showRepositories()});card.append(remove)}parent.append(card)}
async function showRepositories(){if(demo)throw Error('Repository checks require your local bridge; demo mode sends no requests.');const data=await api('repos/list');$('repo-results').replaceChildren();for(const entry of data.repositories)renderRepository($('repo-results'),entry,entry.last_check);return data.repositories}
$('repo-pair').onclick=()=>task(async()=>{if(demo)throw Error('Leave demo mode by connecting your local bridge first.');token=$('repo-token').value.trim();$('repo-token').value='';await showRepositories()});
$('repo-refresh').onclick=()=>task(showRepositories);
$('repo-save').onsubmit=e=>{e.preventDefault();task(async()=>{if(demo)throw Error('Save repositories through your local bridge.');await api('repos/save',{repository:$('repo-name').value});$('repo-name').value='';await showRepositories()})};
$('check-updates').onclick=()=>task(async()=>{const entries=await showRepositories();$('repo-results').replaceChildren();for(const entry of entries){notice('Checking '+entry.repository+'…');let result;try{result=await api('repos/check',{repository:entry.repository})}catch{result={status:'unavailable',error:'Bridge request failed.',last_success:entry.last_check}}renderRepository($('repo-results'),entry,result)}notice('Repository checks finished. Review individual results for unavailable data.');});
async function showInventory(){if(demo)throw Error('Live inventory requires your local bridge.');const data=await api('plugins/list'),repos=await api('repos/list');$('plugin-inventory').replaceChildren();for(const [label,items,state] of [['Console modules',data.console.items,data.console.state],['Backend components',data.backend,'runtime observation'],['User plugins',data.user,'metadata registrations']]){const group=document.createElement('section');const heading=document.createElement('h2');heading.textContent=label;group.append(heading);detail(group,'Source status',state);if(!items.length)detail(group,'Entries','None reported');for(const item of items){const card=document.createElement('article');card.className='repo-card';detail(card,'Name',item.name);detail(card,'State',item.state);if(item.plugin_classification)detail(card,'Plugin classification',item.plugin_classification);if(item.version)detail(card,'Registered version',item.version);if(item.repository){detail(card,'Repository',item.repository);const metadata=repos.repositories.find(r=>r.repository.toLowerCase()===item.repository.toLowerCase())?.last_check;if(metadata){detail(card,'Latest known revision',metadata.revision);detail(card,'Repository owner',metadata.owner);detail(card,'Stars at last check',metadata.stars);detail(card,'Last repository push',metadata.last_push);detail(card,'Metadata checked at',metadata.checked_at)}else detail(card,'Repository metadata','Use Check updates to retrieve')}if(item.state==='registered-not-loaded'){const remove=document.createElement('button');remove.className='secondary';remove.textContent='Remove registration';remove.onclick=()=>task(async()=>{await api('plugins/remove',{name:item.name});await showInventory()});card.append(remove)}group.append(card)}$('plugin-inventory').append(group)}}
$('inventory-refresh').onclick=()=>task(showInventory);
$('plugin-register').onsubmit=e=>{e.preventDefault();task(async()=>{if(demo)throw Error('Registration requires your local bridge.');await api('plugins/register',{name:$('plugin-name').value,version:$('plugin-version').value,repository:$('plugin-repo').value});await showInventory()})};

// Demo shortcuts remain in memory and never reach the local bridge.
let demoGames=[],demoGameId=0;
function resetGames(){if($('game-preview-dialog').open)$('game-preview-dialog').close(); $('game-shortcuts').replaceChildren();$('game-files').replaceChildren();$('game-drive').replaceChildren();$('game-folder').value='';$('game-executable').value='';$('game-name').value=''; }
function syncGameDrives(drives){const previous=$('game-drive').value;$('game-drive').replaceChildren();for(const root of drives)$('game-drive').append(Object.assign(document.createElement('option'),{value:root,textContent:root}));if(drives.includes(previous))$('game-drive').value=previous;else{$('game-folder').value=$('game-drive').value;$('game-files').replaceChildren();$('game-executable').value='';}}
function requireGameConnection(){if(!connected)throw Error('Connect a console or explore demo before using game paths.');}
async function loadGames(){requireGameConnection();const entries=demo?demoGames:(await api('games/list')).shortcuts;$('game-shortcuts').replaceChildren();if(!entries.length){const empty=document.createElement('p');empty.className='empty-state';empty.textContent=demo?'No demo shortcuts yet. Browse a sample folder below and save one.':'No shortcuts for this console connection. Browse a folder below to add one.';$('game-shortcuts').append(empty);}for(const entry of entries){const card=document.createElement('article');card.className='game-card';card.dataset.shortcutId=entry.id;const title=document.createElement('h3'),path=document.createElement('p'),actions=document.createElement('div');title.textContent=entry.name;path.className='mono';path.textContent=entry.folder+entry.executable;actions.className='game-actions';const button=(label,fn)=>{const b=document.createElement('button');b.className='secondary';b.textContent=label;b.onclick=()=>task(fn);actions.append(b);};button('Game preview',async()=>{requireGameConnection();await previewGame(entry);});button('Open folder',async()=>{requireGameConnection();$('game-folder').value=entry.folder;$('game-executable').value='';await browseGames();});if(entry.executable)button('Validate & launch',async()=>{requireGameConnection();await inspect(entry.folder+entry.executable);});button('Remove shortcut',async()=>{requireGameConnection();if(demo)demoGames=demoGames.filter(g=>g.id!==entry.id);else await api('games/remove',{id:entry.id});await loadGames();});const cover=document.createElement('div');cover.className='game-cover mini';cover.textContent='XBOX 360';card.append(cover,title,path,actions);$('game-shortcuts').append(card);}}
async function browseGames(){requireGameConnection();const folder=$('game-folder').value.replace(/\\?$/,'\\');const files=demo?demoFiles(folder):(await api('browse',{path:folder})).files;$('game-folder').value=folder;$('game-files').replaceChildren();$('game-executable').value='';if(!files.length)$('game-files').textContent='This folder is empty.';for(const f of files){if(!f.directory&&!/\.xex$/i.test(f.name))continue;const row=document.createElement('div');row.className='file-row';const label=document.createElement('b'),action=document.createElement('button');label.textContent=f.name;action.className='secondary';action.textContent=f.directory?'Open folder →':'Use launch file';action.onclick=()=>task(async()=>{if(f.directory){$('game-folder').value=folder+f.name+'\\';await browseGames();}else{$('game-folder').value=folder;$('game-executable').value=f.name;if(!$('game-name').value)$('game-name').value=folder.split('\\').filter(Boolean).pop();$('game-name').focus();}});row.append(label,action);$('game-files').append(row);}}
$('game-browse').onclick=()=>task(browseGames);
$('games-refresh').onclick=()=>task(loadGames);
$('game-drive').onchange=()=>task(async()=>{$('game-folder').value=$('game-drive').value;await browseGames();});
$('game-folder').oninput=()=>{$('game-files').replaceChildren();$('game-executable').value='';};
$('game-up').onclick=()=>task(async()=>{const folder=$('game-folder').value.replace(/\\$/,'');const i=folder.lastIndexOf('\\');if(i>=0){$('game-folder').value=folder.slice(0,i+1);await browseGames();}});
$('game-save').onsubmit=e=>{e.preventDefault();task(async()=>{requireGameConnection();const entry={name:$('game-name').value.trim(),folder:$('game-folder').value.replace(/\\?$/,'\\'),executable:$('game-executable').value.trim()};if(!entry.name)throw Error('Enter a shortcut name.');if(demo){if(!Array.from($('game-drive').options).some(o=>entry.folder.startsWith(o.value)))throw Error('Choose a sample storage root.');if(entry.executable&&!demoFiles(entry.folder).some(f=>!f.directory&&f.name===entry.executable))throw Error('Choose a sample XEX from this folder.');const existing=demoGames.find(g=>g.folder===entry.folder&&g.executable===entry.executable);if(existing)Object.assign(existing,entry);else demoGames.push({...entry,id:++demoGameId});}else await api('games/save',entry);await loadGames();notice(demo?'Demo shortcut saved for this page session.':'Game shortcut saved on your local bridge.');});};

function gameBadge(result){const badge=document.createElement('span');const status=result.status;badge.className='game-badge '+(status==='verified'?'verified':['mismatch','revoked'].includes(status)?'mismatch':'unknown');badge.textContent=(status==='verified'||['mismatch','revoked'].includes(status)?'✓ ':'? ')+result.label;return badge;}
function renderGameCapabilities(){const panel=$('game-capabilities');panel.replaceChildren();for(const [name,reason] of [['Trainers','No tested trainer adapter installed.'],['Title updates','Discovery and activation adapter not implemented.'],['GSC injection','Game/version compatibility unknown; no tested adapter installed.']]){const row=document.createElement('div');row.className='capability';const text=document.createElement('div'),heading=document.createElement('b'),note=document.createElement('p'),button=document.createElement('button');heading.textContent=name;note.textContent=reason;button.textContent='Unavailable';button.className='secondary';button.disabled=true;text.append(heading,note);row.append(text,button);panel.append(row);}}
function showGameMetadata(result,fallback){const report=result.verification,metadata=report.metadata||{},game=report.game;$('game-preview-name').textContent=game?.title||fallback;$('game-preview-source').textContent=demo?'Demo metadata — no console file read':game?.source||'File metadata from console XEX; artwork not available';$('game-cover').replaceChildren();if(game?.cover){const img=document.createElement('img');img.src=game.cover;img.alt=(game.title||fallback)+' cover';img.onerror=()=>{$('game-cover').textContent='Artwork unavailable';};$('game-cover').append(img);}else $('game-cover').textContent='XBOX 360';const container=$('game-metadata');container.replaceChildren();for(const [label,key] of [['Title ID','title_id'],['Media ID','media_id'],['File version (hex)','version'],['Base version (hex)','base_version'],['Disc','disc'],['Disc count','disc_count']])detail(container,label,metadata[key]);}
// Candidate export is bound to the most recently inspected file in this preview.
// It never changes badges or sends catalog, trust, or console-write requests.
let gamePreviewGeneration=0,candidateGeneration=0,candidateInspection=null,candidateExport=null;
function resetGameCandidate(message='Read a console XEX to prepare a candidate.'){
  candidateGeneration++;candidateInspection=null;candidateExport=null;
  $('game-candidate-form').reset();$('game-candidate-form').hidden=true;
  $('game-candidate-file').textContent='';$('game-candidate-output').hidden=true;
  $('game-candidate-json').value='';$('game-candidate-help').textContent=message;
  $('game-candidate-message').textContent='';
}
function offerGameCandidate(result){
  if(demo){resetGameCandidate('Candidate export is unavailable for demo data. Connect and inspect a real console file.');return;}
  if(!result.inspection_id){resetGameCandidate(result.candidate_unavailable||'Complete XEX execution metadata is required. Read another file.');return;}
  candidateInspection=result.inspection_id;
  $('game-candidate-form').hidden=false;
  $('game-candidate-file').textContent=result.file+' · '+result.verification.actual_size+' bytes · SHA-256 '+result.verification.actual_sha256;
  $('game-candidate-help').textContent='This export uses the inspected snapshot (valid for 10 minutes). Enter its title and provenance; read the file again if its bytes have changed.';
}
$('game-preview-dialog').addEventListener('close',()=>{gamePreviewGeneration++;resetGameCandidate();});
for(const id of ['game-candidate-title','game-candidate-provenance'])$(id).addEventListener('input',()=>{
  candidateGeneration++;candidateExport=null;$('game-candidate-output').hidden=true;
  $('game-candidate-json').value='';$('game-candidate-message').textContent='';
});
$('game-candidate-form').onsubmit=e=>{
  e.preventDefault();task(async()=>{
    if(demo||!connected||!candidateInspection)throw Error('Inspect a real console file before exporting a candidate.');
    const title=$('game-candidate-title').value.trim(),provenance=$('game-candidate-provenance').value.trim();
    if(!title||!provenance){$('game-candidate-message').textContent='Enter both a game title and its provenance.';return;}
    const generation=candidateGeneration,inspection=candidateInspection;
    candidateExport=null;$('game-candidate-output').hidden=true;$('game-candidate-json').value='';
    $('game-candidate-message').textContent='Preparing untrusted candidate…';
    try{
      const result=await api('games/propose',{inspection_id:inspection,title,provenance});
      if(generation!==candidateGeneration||!$('game-preview-dialog').open)return;
      candidateExport={text:JSON.stringify(result.candidate,null,2)+'\n',filename:result.candidate.id+'.candidate.json'};
      $('game-candidate-json').value=candidateExport.text;$('game-candidate-output').hidden=false;
      $('game-candidate-message').textContent='Untrusted candidate ready. The catalog and verification result are unchanged. Submit it for separate review.';
    }catch(e){
      if(generation===candidateGeneration&&$('game-preview-dialog').open)$('game-candidate-message').textContent='Could not generate candidate. Check title/provenance and read the file again if the inspection expired. '+e.message;
    }
  });
};
$('game-candidate-copy').onclick=async()=>{
  if(!candidateExport)return;
  const generation=candidateGeneration;
  try{
    if(!navigator.clipboard?.writeText)throw Error('Clipboard unavailable');
    await navigator.clipboard.writeText(candidateExport.text);
    if(generation===candidateGeneration)$('game-candidate-message').textContent='Candidate JSON copied. It remains untrusted until separately reviewed.';
  }catch{
    if(generation!==candidateGeneration)return;
    $('game-candidate-json').focus();$('game-candidate-json').select();
    $('game-candidate-message').textContent='Automatic copy is unavailable here. Copy the selected JSON manually or use Download JSON.';
  }
};
$('game-candidate-download').onclick=()=>{
  if(!candidateExport)return;
  const url=URL.createObjectURL(new Blob([candidateExport.text],{type:'application/json'})),link=document.createElement('a');
  link.href=url;link.download=candidateExport.filename;document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
async function previewGame(entry){
  requireGameConnection();
  const generation=++gamePreviewGeneration;
  const current=()=>generation===gamePreviewGeneration&&$('game-preview-dialog').open;
  resetGameCandidate();
  $('game-preview-name').textContent=entry.name;$('game-preview-source').textContent='Reading game folder…';
  $('game-metadata').replaceChildren();$('game-cover').textContent='XBOX 360';$('game-launch-files').replaceChildren();
  renderGameCapabilities();$('game-preview-dialog').showModal();
  const files=demo?demoFiles(entry.folder):(await api('browse',{path:entry.folder})).files;
  if(!current())return;
  const xex=files.filter(f=>!f.directory&&/\.xex$/i.test(f.name));
  $('game-preview-source').textContent=demo?'Sample folder — no console connection':'Select a file to read metadata and verify its current bytes.';
  if(!xex.length)$('game-launch-files').textContent='No XEX launch files in this folder. Open a game subfolder and save a shortcut.';
  for(const file of xex){
    const row=document.createElement('article');row.className='game-file';
    const heading=document.createElement('h4'),badge=gameBadge({status:'unknown',label:'Not checked'}),buttons=document.createElement('div'),verify=document.createElement('button'),launch=document.createElement('button'),details=document.createElement('details'),summary=document.createElement('summary'),reportText=document.createElement('pre');
    heading.textContent=file.name;buttons.className='game-actions';verify.className='secondary';verify.textContent='Read metadata & verify';
    launch.className='secondary';launch.textContent='Validate & launch';summary.textContent='Verification details';
    details.append(summary,reportText);details.hidden=true;buttons.append(verify,launch);row.append(heading,badge,buttons,details);$('game-launch-files').append(row);
    const path=entry.folder+file.name;
    const check=async()=>{
      resetGameCandidate('Reading selected XEX…');badge.className='game-badge unknown';badge.textContent='Reading file…';details.hidden=true;
      try{
        const result=demo?{plugin:false,verification:{status:file.name==='default_mp.xex'?'mismatch':'verified',label:file.name==='default_mp.xex'?'Demo: differs from sample reference':'Demo: matches sample reference',actual_sha256:'Sample only — not a real hash',metadata:{title_id:'00000000',media_id:'00000000',version:'00000000',base_version:'00000000',disc:1,disc_count:1},references:[],game:{title:entry.name+' (sample)',source:'Demo'}}}:await api('games/inspect',{path});
        if(!current())return;
        const fresh=gameBadge(result.verification);badge.className=fresh.className;badge.textContent=fresh.textContent;
        showGameMetadata(result,entry.name);offerGameCandidate(result);
        const card=Array.from(document.querySelectorAll('.game-card')).find(c=>c.dataset.shortcutId===String(entry.id));
        if(card&&result.verification.game){
          card.querySelector('h3').textContent=result.verification.game.title;
          if(result.verification.game.cover){const image=document.createElement('img');image.src=result.verification.game.cover;image.alt=result.verification.game.title+' cover';card.querySelector('.game-cover').replaceChildren(image);}
        }
        reportText.textContent=JSON.stringify({checked_at:new Date().toISOString(),...result.verification,game:undefined},null,2);details.hidden=false;
        launch.disabled=result.plugin||['mismatch','revoked'].includes(result.verification.status);
        launch.title=result.plugin?'Plugin modules cannot launch as games.':launch.disabled?'File differs from a reviewed baseline or is revoked.':'';
      }catch(e){if(current()){resetGameCandidate('Inspection unavailable. Read a valid console XEX before proposing a baseline.');badge.className='game-badge unknown';badge.textContent='? Check unavailable';}throw e;}
    };
    verify.onclick=()=>task(check);
    launch.onclick=()=>task(async()=>{requireGameConnection();$('game-preview-dialog').close();await inspect(path);});
    if(file.name===entry.executable){await check();if(!current())return;}
  }
}
