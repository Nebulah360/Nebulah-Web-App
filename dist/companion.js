'use strict';
// All values rendered as text. Display metadata is kept separate from trust badges.
function button(label,action){const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=label;b.onclick=()=>task(action);return b;}
function bytesLabel(n){return n>=1073741824?(n/1073741824).toFixed(2)+' GiB':n>=1048576?(n/1048576).toFixed(1)+' MiB':n.toLocaleString()+' bytes';}
let consoleFilePickerMode='download';
function browserTools(prefix,path){
  const container=$(prefix==='app'?'files':prefix==='download'?'download-files':'game-files'),rows=Array.from(container.querySelectorAll('.file-row'));
  const apply=()=>{const query=$(prefix+'-search').value.toLocaleLowerCase(),filter=$(prefix+'-filter').value;let shown=0;
    for(const row of rows){const directory=row.dataset.directory==='true',name=row.dataset.name;const eligible=filter==='all'||filter==='folders'&&directory||filter==='files'&&!directory||filter==='xex'&&(directory||/\.xex$/i.test(name));row.hidden=!eligible||!name.toLocaleLowerCase().includes(query);if(!row.hidden)shown++;}
    $(prefix+'-count').textContent=shown+' of '+rows.length+' entries';};
  $(prefix+'-search').oninput=apply;$(prefix+'-filter').onchange=apply;apply();
  const crumbs=$(prefix+'-crumbs');crumbs.replaceChildren();const parts=path.split('\\').filter(Boolean);let cumulative='';
  for(const part of parts){cumulative+=part+'\\';const dest=cumulative;crumbs.append(button(part,async()=>{if(prefix==='app'){$('path').value=dest;await browse();}else if(prefix==='download'){await browseDownloadFolder(dest);}else{$('game-folder').value=dest;await browseGames();}}));}
}
function decorateFileRow(row,file,folder){
  const path=folder.replace(/\\?$/,'\\')+file.name;
  row.append(button('☆ Favorite',async()=>{if(!file.directory&&/\.xex$/i.test(file.name)){openFavorite({path,name:file.name,directory:false});return;}await api('favorites/save',{path:file.directory?path+'\\':path,name:file.name,directory:Boolean(file.directory)});notice('Favorite saved for this console.');}));
  if(!file.directory)row.append(button('Download',async()=>downloadFile(path)));
}
async function showFavorites(){
  if(!connected)throw Error('Connect a console first.');let data;try{data=await api('favorites/list');}catch(error){$('favorites-list').textContent='Favorites unavailable. Reconnect and retry.';$('recent-list').replaceChildren();throw error;}
  for(const [id,items] of [['favorites-list',data.favorites],['recent-list',data.recent]]){
    const panel=$(id);panel.replaceChildren();if(!items.length)panel.textContent='None saved for this console.';
    for(const item of items){const row=document.createElement('article');row.className='repo-card';const title=document.createElement('b');title.textContent=item.name||item.path.split('\\').pop();row.append(title);detail(row,'Path',item.path);if(item.mode)detail(row,'Game mode',gameModeLabel(item.mode));if(item.state)detail(row,'Last launch',({'accepted':'Command accepted; awaiting confirmation','confirmed-path':'Running executable confirmed','confirmed-executable-name':'Executable name and Title ID observed; exact path unconfirmed','confirmed-title-id':'Title ID confirmed; executable not confirmed','unconfirmed':'Launch not confirmed'})[item.state]+' · '+new Date(item.launched*1000).toLocaleString());
      if(item.directory)row.append(button('Open folder',async()=>{$('path').value=item.path;view('library');await browse();}));
      else if(/\.xex$/i.test(item.path))row.append(button('Validate & launch',async()=>inspect(item.path)));
      else row.append(button('Download',async()=>downloadFile(item.path)));
      if(id==='favorites-list'&&!item.directory&&/\.xex$/i.test(item.path))row.append(button('Edit favorite',async()=>openFavorite(item)));
      if(id==='favorites-list')row.append(button('Remove favorite',async()=>{await api('favorites/remove',{path:item.path});await showFavorites();notice('Favorite removed for this console.');}));panel.append(row);
    }
  }
}
let favoriteSelection=null;
function openFavorite(item){favoriteSelection={path:item.path,directory:false};$('favorite-path').textContent=item.path;$('favorite-name').value=item.name;$('favorite-mode').value=item.mode||'';$('favorite-dialog').showModal();}
$('favorite-form').onsubmit=e=>{e.preventDefault();task(async()=>{if(!connected||!favoriteSelection)throw Error('Choose a favorite while connected.');await api('favorites/save',{...favoriteSelection,name:$('favorite-name').value.trim(),mode:$('favorite-mode').value});$('favorite-dialog').close();favoriteSelection=null;await showFavorites();notice('Favorite saved for this console.');});};
$('favorites-refresh').onclick=()=>task(showFavorites);
let profiles=[];
const consoleCacheKey='nebulah-console-profiles-v1';
function validConsoleTarget(value){return typeof value==='string'&&/^[A-Za-z0-9_.-]{1,253}$/.test(value);}
function renderProfiles(){const selected=$('profile-select').value,select=$('profile-select');select.replaceChildren(Object.assign(document.createElement('option'),{value:'',textContent:'Choose a profile'}));for(const p of profiles)select.append(Object.assign(document.createElement('option'),{value:p.id,textContent:p.name}));if(profiles.some(p=>p.id===selected))select.value=selected;if(typeof renderSettingsProfiles==='function')renderSettingsProfiles();}
function cacheProfiles(){try{localStorage.setItem(consoleCacheKey,JSON.stringify({profiles}));}catch{notice('Browser storage is unavailable. Console profiles remain saved on the bridge.');}}
function restoreProfiles(){$('target').value='';try{const saved=JSON.parse(localStorage.getItem(consoleCacheKey)||'null');if(!saved)return;if(Array.isArray(saved.profiles))profiles=saved.profiles.slice(0,32).filter(p=>p&&typeof p.id==='string'&&/^[a-f0-9]{24}$/.test(p.id)&&typeof p.name==='string'&&p.name.length<=80&&validConsoleTarget(p.target)).map(p=>({id:p.id,name:p.name,target:p.target}));renderProfiles();}catch{}}
async function loadProfiles(){if(!token)token=$('token').value.trim();profiles=(await api('profiles/list')).profiles;renderProfiles();cacheProfiles();}
async function rememberConsole(target){cacheProfiles();try{await loadProfiles();if(target&&!profiles.some(p=>p.target.toLowerCase()===target.toLowerCase())){await api('profiles/save',{name:target.slice(0,80),target});await loadProfiles();}cacheProfiles();}catch{notice('Connected. Could not refresh saved console profiles.');}}
restoreProfiles();
$('profiles-load').onclick=()=>task(loadProfiles);
$('profile-select').onchange=()=>{const p=profiles.find(p=>p.id===$('profile-select').value);if(p){$('target').value=p.target;$('profile-name').value=p.name;cacheProfiles();}};
$('profile-save').onclick=()=>task(async()=>{if(!token)token=$('token').value.trim();await api('profiles/save',{id:$('profile-select').value||undefined,name:$('profile-name').value,target:$('target').value.trim()});await loadProfiles();notice('Console profile saved.');});
$('profile-remove').onclick=()=>task(async()=>{await api('profiles/remove',{id:$('profile-select').value});await loadProfiles();});
$('capacity-refresh').onclick=()=>task(async()=>{
  if(!connected)throw Error('Connect a console first.');const panel=$('capacity-list');panel.replaceChildren();
  for(const option of $('drive').options){if(!option.value)continue;const row=document.createElement('article');row.className='repo-card';const title=document.createElement('b');title.textContent=option.value;row.append(title);panel.append(row);
    try{const capacity=await api('storage/capacity',{root:option.value});detail(row,'Used / total',bytesLabel(capacity.used)+' / '+bytesLabel(capacity.total));detail(row,'Free',bytesLabel(capacity.free));const meter=document.createElement('progress');meter.max=capacity.total;meter.value=capacity.used;meter.setAttribute('aria-label','Used storage');row.append(meter);}catch{detail(row,'Capacity','Unavailable from this drive.');}
  }
  if(!panel.children.length)panel.textContent='Discover storage first.';
});
let scanCancel=false,scanId=null,libraryFiles=[];
function renderLibrary(){const query=$('library-search').value.toLocaleLowerCase(),panel=$('library-results');panel.replaceChildren();const matches=libraryFiles.filter(f=>f.path.toLocaleLowerCase().includes(query));if(!matches.length)panel.textContent='No matching scanned files.';
  for(const file of matches){const row=document.createElement('article');row.className='repo-card';detail(row,'File',file.path);detail(row,'Size',bytesLabel(file.size));detail(row,'Last scanned',new Date(file.scanned*1000).toLocaleString());if(/\.xex$/i.test(file.path)){row.append(button('Game preview',async()=>{const i=file.path.lastIndexOf('\\');await previewGame({name:file.path.slice(i+1),folder:file.path.slice(0,i+1),executable:file.path.slice(i+1)});}));row.append(button('Validate & launch',async()=>inspect(file.path)));}else detail(row,'Status','ISO/GOD candidate only — not verified or launchable');panel.append(row);}}
async function loadLibrary(){libraryFiles=(await api('library/list')).files;renderLibrary();}
$('library-search').oninput=renderLibrary;$('library-refresh').onclick=()=>task(loadLibrary);
$('library-clear').onclick=()=>task(async()=>{await api('library/clear');await loadLibrary();});
$('scan-cancel').onclick=()=>{scanCancel=true;$('scan-progress').textContent='Cancelling after the current folder…';};
const scanFormat=document.createElement('select');scanFormat.setAttribute('aria-label','Scan format');
for(const [value,textContent] of [['xex','XEX files (default)'],['iso-god','ISO/GOD candidates — experimental']])scanFormat.append(Object.assign(document.createElement('option'),{value,textContent}));
scanFormat.value='xex';($('scan-progress').parentElement||document.body).append(scanFormat);
const isoDisclaimer='ISO/GOD discovery only. Names and folder layout do not prove a copy is valid, complete, unique or safe. Conversion, launch, deletion, replacement and integrity checks are unavailable. Existing transfer limits still apply. Use your own authorized copies. Continue?';
$('scan-start').onclick=()=>task(async()=>{
  const formats=scanFormat.value||'xex';
  if(formats==='iso-god'&&!window.confirm(isoDisclaimer))return;
  if(!connected||!$('path').value)throw Error('Connect and choose a folder in File transfer first.');scanCancel=false;$('scan-cancel').disabled=false;
  try{let state=await api('scan/start',{path:$('path').value,depth:Number($('scan-depth').value),formats,disclaimer_accepted:formats==='iso-god'});scanId=state.id;
    while(state.state==='running'){
      if(scanCancel){state=await api('scan/cancel',{id:scanId});break;}
      state=await api('scan/step',{id:scanId});$('scan-progress').textContent=state.state+' · '+state.visited+' folders · '+state.found+' candidates · '+state.remaining+' queued · '+state.errors+' unavailable/incomplete';
    }
    $('scan-progress').textContent=state.state+' · '+state.visited+' folders · '+state.found+' candidates · '+state.errors+' unavailable/incomplete. Saved results may include earlier scans.';await loadLibrary();
  }finally{$('scan-cancel').disabled=true;scanId=null;}
});
let gamesWorkCancelled=false,gamesLookupAttempted=new Set(),libraryStorageSelection=null,gamesScanActive=false;
function requestLibraryStorageSelection(root){
  libraryStorageSelection={root,generation:gameLibraryGeneration};
  if(gamesScanActive)gamesWorkCancelled=true;
  resumeLibraryStorageSelection();
}
function resumeLibraryStorageSelection(){
  if(!libraryStorageSelection||busy)return;
  const request=libraryStorageSelection;libraryStorageSelection=null;
  if(!connected||consoleRecoveryHold||request.generation!==gameLibraryGeneration)return;
  task(async()=>{if(request.root==='all')await loadGameLibrary();else await scanGameLibrary(request.root,false,true);});
}
function gamesWorkControls(active){gamesScanActive=active;$('games-scan').disabled=active;$('games-identify').disabled=active;$('games-prune').disabled=active;$('games-cancel').disabled=!active;}
let identifyToastTimer=null,identifyToastActive=false;
function beginIdentifyToast(){clearTimeout(identifyToastTimer);identifyToastActive=true;const toast=$('games-identify-toast');toast.hidden=false;toast.dataset.tone='success';$('games-identify-toast-title').textContent='Identifying unread games';$('games-identify-toast-message').textContent='Preparing library…';}
function finishIdentifyToast(tone='success'){if(!identifyToastActive)return;identifyToastActive=false;const toast=$('games-identify-toast');toast.dataset.tone=tone;$('games-identify-toast-title').textContent=tone==='error'?'Identification failed':tone==='warning'?'Identification needs attention':'Identification complete';clearTimeout(identifyToastTimer);identifyToastTimer=setTimeout(()=>{toast.hidden=true;},tone==='error'?10000:7000);}
function hideIdentifyToast(){identifyToastActive=false;clearTimeout(identifyToastTimer);$('games-identify-toast').hidden=true;}
function setGamesProgress(message){$('games-progress').textContent=message;$('games-library-status').textContent=message;if(identifyToastActive)$('games-identify-toast-message').textContent=message;}
function gamesWorkCurrent(generation){return generation===gameLibraryGeneration&&connected&&!gamesWorkCancelled&&!consoleRecoveryHold;}
$('games-cancel').onclick=()=>{gamesWorkCancelled=true;libraryStorageSelection=null;setGamesProgress('Cancelling after the active console operation…');};
async function identifyLibraryFiles(generation,scanSummary=''){
  beginIdentifyToast();
  const selected=new Set(gameLibraryGroups.filter(item=>!['plugin','stealth'].includes(item.kind)&&!item.categories?.some(category=>['plugins','stealth'].includes(category))).flatMap(item=>item.paths||[]).filter(gameLibraryPathVisible).map(path=>path.toLowerCase()));
  const known=new Set(gameLibraryGroups.filter(item=>item.component||item.categories?.some(category=>['homebrew','apps','emulators'].includes(category))).flatMap(item=>item.paths||[]).map(path=>path.toLowerCase()));
  const root=$('games-scan-location').value;
  const files=gameLibraryFiles.filter(item=>/\.xex$/i.test(item.path)&&!item.inspection?.plugin&&selected.has(item.path.toLowerCase())&&(!root||root==='all'||item.path.toLowerCase().startsWith(root.toLowerCase())));
  let read=0,lookedUp=0,failed=0,skipped=0,budget=0,limited=false,firstFailure='';
  const seenTitles=new Set(),started=Date.now();
  const cachedTitles=new Set(gameLibraryGroups.filter(group=>group.metadata_available).map(group=>group.title_id));
  for(const item of files){
    if(!gamesWorkCurrent(generation))break;
    if(Date.now()-started>=1800000){limited=true;break;}
    let metadata=item.inspection?.metadata,plugin=item.inspection?.plugin;
    if(!item.inspection){
      if(read>=100||Date.now()-started>=1800000){limited=true;break;}
      if(!Number.isSafeInteger(item.size)||item.size<24||item.size>64*1024*1024){skipped++;continue;}
      if(budget+item.size>512*1024*1024){limited=true;break;}
      budget+=item.size;read++;
      setGamesProgress('Identifying '+read+' · '+libraryDisplayName(item.path)+' · '+failed+' unavailable');
      try{const result=await api('games/inspect',{path:item.path});metadata=result.verification?.metadata;plugin=result.plugin;}
      catch(error){if(error.httpStatus!==400||error.diagnostic||error.recoveryRequired)throw error;failed++;if(!firstFailure)firstFailure=error.message;continue;}
      if(!gamesWorkCurrent(generation))break;
    }
    const id=metadata?.title_id;
    if(!plugin&&!known.has(item.path.toLowerCase())&&/^[0-9A-F]{8}$/i.test(id||'')&&id!=='00000000'&&!seenTitles.has(id)&&!cachedTitles.has(id)&&!gamesLookupAttempted.has(id)){
      if(seenTitles.size>=100){limited=true;continue;}seenTitles.add(id);gamesLookupAttempted.add(id);
      setGamesProgress('Fetching name and cover · '+id);
      try{await api('metadata/lookup',{title_id:id,online:true});lookedUp++;}
      catch(error){if(error.httpStatus!==400||error.diagnostic||error.recoveryRequired)throw error;failed++;}
    }
  }
  let auroraNames=0;
  if(gamesWorkCurrent(generation)){
    setGamesProgress('Checking on-console Aurora title names…');
    const result=await api('metadata/aurora-import',{});
    auroraNames=result.imported||0;
  }
  if(generation!==gameLibraryGeneration||!connected)return;
  await loadGameLibrary();
  if(generation!==gameLibraryGeneration||!connected)return;
  setGamesProgress(scanSummary+(gamesWorkCancelled?'Cancelled. ':limited?'Pass limit reached; use Identify unread games again to continue. ':'Identification finished. ')+read+' XEX reads · '+lookedUp+' title lookups · '+auroraNames+' Aurora names · '+skipped+' files outside inspection limits · '+failed+' unavailable.'+(firstFailure?' First read failure: '+firstFailure+'.':'')+' Names and covers never grant launch trust.');
  finishIdentifyToast(gamesWorkCancelled||limited||failed?'warning':'success');
}
$('games-identify').onclick=()=>task(async()=>{
  requireGameConnection();const generation=gameLibraryGeneration;gamesWorkCancelled=false;gamesWorkControls(true);beginIdentifyToast();
  try{await loadGameLibrary();if(gamesWorkCurrent(generation))await identifyLibraryFiles(generation);}
  catch(error){if(generation===gameLibraryGeneration){setGamesProgress('Identification stopped. '+error.message);finishIdentifyToast('error');}throw error;}
  finally{gamesWorkControls(false);}
});
async function scanGameLibrary(location=$('plugin-scan-location').value||'all',identify=true,storageSelection=false){
  requireGameConnection();const generation=gameLibraryGeneration;gamesWorkCancelled=false;gamesWorkControls(true);let id=null;
  if(!storageSelection)gamesLookupAttempted.clear();
  const current=()=>generation===gameLibraryGeneration&&connected&&(!storageSelection||location.toLowerCase()===($('games-scan-location').value||'all').toLowerCase());
  try{
    let paths;
    if(location==='all'){await discoverStorage();paths=Array.from($('plugin-scan-location').options).map(option=>option.value).filter(root=>root&&root!=='all');}
    else {const selected=Array.from($('plugin-scan-location').options).find(option=>option.value.toLowerCase()===location.toLowerCase());if(!selected)throw Error('Choose discovered library storage.');location=selected.value;paths=[location];}
    if(!gamesWorkCurrent(generation))return;if(!paths.length)throw Error('No accessible storage was discovered. Check the console connection.');
    if(!storageSelection)$('games-scan-location').value=location;
    let state=await api('scan/start',{paths,depth:Number($('games-scan-depth').value||6),formats:'xex',view:'installs'});id=state.id;
    while(state.state==='running'){
      if(generation!==gameLibraryGeneration||!connected)return;
      if(gamesWorkCancelled||!current()){state=await api('scan/cancel',{id});break;}
      state=await api('scan/step',{id});
      if(generation!==gameLibraryGeneration||!connected)return;
      if(current())setGamesProgress('Scanning '+(location==='all'?'all storage':location)+' · '+state.visited+' folders · '+state.found+' XEX files · '+state.remaining+' queued · '+state.errors+' unavailable/incomplete');
    }
    if(!current())return;
    await loadGameLibrary();if(generation!==gameLibraryGeneration||!connected)return;
    if(!current())return;
    setGamesProgress('Scan '+state.state+' · '+(location==='all'?'all storage':location)+' · '+state.found+' XEX files · '+state.errors+' unavailable/incomplete. Saved earlier observations are retained.');
    // The explicit Scan action includes a bounded identification pass.
    if(identify&&gamesWorkCurrent(generation)&&state.state!=='cancelled')await identifyLibraryFiles(generation,'Scan '+state.state+' · '+state.found+' XEX files · '+state.errors+' unavailable/incomplete. ');
  }catch(error){if(current()){setGamesProgress('Scan stopped. '+error.message);finishIdentifyToast('error');}throw error;}
  finally{gamesWorkControls(false);}
}
$('games-scan').onclick=()=>task(()=>scanGameLibrary());
$('games-prune').onclick=()=>task(async()=>{
  requireGameConnection();const root=$('games-scan-location').value||'all',selection=root==='all'?{}:{root};
  const preview=await api('library/prune-uninspected',selection);
  if(!preview.count){setGamesProgress('No unread game entries to remove from the local library.');return;}
  const message='Remove '+preview.count+' unread game '+(preview.count===1?'entry':'entries')+' from this console’s local library? Saved labels for those entries will also be removed. No console files will be deleted.';
  if(typeof window.confirm!=='function'||!window.confirm(message))return;
  const result=await api('library/prune-uninspected',{...selection,confirmed:true,expected_count:preview.count});
  await loadGameLibrary();setGamesProgress('Removed '+result.removed+' unread game '+(result.removed===1?'entry':'entries')+' from the local library. Console files were not changed.');
});

let pluginWorkspaceGeneration=0;
let pendingForceRelease=null;
function resetPluginWorkspace(){pluginWorkspaceGeneration++;pendingForceRelease=null;if($('plugin-force-dialog').open)$('plugin-force-dialog').close();$('plugin-files').replaceChildren();$('plugin-file-count').textContent='';$('plugin-capabilities').textContent='Refresh after reconnecting to read plugin capabilities.';$('plugin-inventory').textContent='Reconnect, then refresh the module inventory.';}
function openForceRelease(name){pendingForceRelease={name,generation:pluginWorkspaceGeneration};$('plugin-force-name').textContent=name;$('plugin-force-dialog').showModal();}
$('plugin-force-cancel').onclick=()=>{$('plugin-force-dialog').close();};
$('plugin-force-dialog').addEventListener('close',()=>{pendingForceRelease=null;});
$('plugin-force-confirm').onclick=()=>task(async()=>{
  const pending=pendingForceRelease;pendingForceRelease=null;$('plugin-force-dialog').close();
  if(!pending||!connected||pending.generation!==pluginWorkspaceGeneration)throw Error('Plugin workspace changed. Refresh first.');
  try{const result=await api('plugins/force-release',{name:pending.name,confirmed:true});notice(result.name+' force released.');}
  finally{try{await showInventory();}catch{}}
});
function filterInspectedPlugins(){
  const query=$('plugin-file-search').value.trim().toLocaleLowerCase();
  const rows=Array.from($('plugin-files').children);
  let shown=0;
  for(const row of rows){row.hidden=!row.dataset.search.includes(query);if(!row.hidden)shown++;}
  $('plugin-file-count').textContent=query?shown+' of '+rows.length+' shown':rows.length+' inspected '+(rows.length===1?'file':'files');
}
$('plugin-file-search').oninput=filterInspectedPlugins;
async function loadPluginWorkspace(){
  const generation=++pluginWorkspaceGeneration;
  $('plugin-files').replaceChildren();
  if(!connected){$('plugin-files').textContent='Connect a console to view inspected plugin files.';$('plugin-file-count').textContent='';return;}
  const capabilities=await api('plugins/capabilities');
  if(generation!==pluginWorkspaceGeneration||!connected)return;
  $('plugin-route').querySelector('[value="component"]').disabled=!capabilities.component;
  if(!capabilities.component)$('plugin-route').value='neighborhood';
  $('plugin-route-note').textContent=capabilities.component?'Nebulah XEX tracks its own loads for managed unloading. Neighborhood remains available.':'Nebulah XEX is not loaded. Continue through Neighborhood, or load NebulahCompanion.xex through the inspected plugin route to enable managed unloading.';
  $('plugin-capabilities').textContent='Plugin inspection and module inventory available. '+capabilities.reason;
  const result=await api('plugins/library');if(generation!==pluginWorkspaceGeneration||!connected)return;
  let loadedNames=new Set(),bridgeLoadPaths=new Map(),bridgeSelectedPaths=new Map(),unloadReadyNames=new Set(),uncertainNames=new Set(),forceReadyNames=new Set(),moduleListComplete=false;
  if(result.files.length)try{const inventory=await api('plugins/list');if(generation!==pluginWorkspaceGeneration||!connected)return;moduleListComplete=inventory.console?.state==='observed';if(moduleListComplete||inventory.console?.state==='partial')for(const module of inventory.console.items){const name=module.name.toLowerCase();loadedNames.add(name);if(module.managed_by_bridge&&typeof module.bridge_load_path==='string')bridgeLoadPaths.set(name,module.bridge_load_path);if(module.managed_by_bridge&&typeof module.bridge_selected_path==='string')bridgeSelectedPaths.set(name,module.bridge_selected_path);if(module.unload_ready===true)unloadReadyNames.add(name);if(module.unload_uncertain===true)uncertainNames.add(name);if(module.force_ready===true)forceReadyNames.add(name);if(/^nebulahcompanion-[a-z0-9_]+\.xex$/i.test(name)){loadedNames.add('nebulahcompanion.xex');if(module.bridge_load_path)bridgeLoadPaths.set('nebulahcompanion.xex',module.bridge_load_path);if(module.bridge_selected_path)bridgeSelectedPaths.set('nebulahcompanion.xex',module.bridge_selected_path);}}}catch{}
  const files=result.files.filter(item=>!/^NebulahCompanion-[A-Za-z0-9_]+\.xex$/i.test(item.path.split('\\').pop())).sort((a,b)=>{
    const name=item=>item.label?.name||item.path.split(String.fromCharCode(92)).pop();
    return name(a).localeCompare(name(b),undefined,{sensitivity:'base'})||a.path.localeCompare(b.path,undefined,{sensitivity:'base'});
  });
  if(!files.length)$('plugin-files').textContent='No main Companion XEX or inspected plugin files are saved. Inspect NebulahCompanion.xex or another exact path above.';
  const managedActionNames=new Set();
  for(const item of files){
    const row=document.createElement('article'),heading=document.createElement('div'),title=document.createElement('h3'),state=document.createElement('span'),path=document.createElement('p'),actions=document.createElement('div'),details=document.createElement('details'),summary=document.createElement('summary');
    const filename=item.path.split(String.fromCharCode(92)).pop(),moduleName=filename.toLowerCase(),listed=loadedNames.has(moduleName),bridgePath=bridgeLoadPaths.get(moduleName),selectedPath=bridgeSelectedPaths.get(moduleName)||bridgePath,thisPath=listed&&selectedPath?.toLowerCase()===item.path.toLowerCase(),otherPath=listed&&selectedPath&&!thisPath;
    row.className='game-card plugin-file-row';row.dataset.search=(filename+' '+(item.label?.name||'')+' '+item.path).toLocaleLowerCase();
    heading.className='plugin-file-heading';title.textContent=item.label?.name||filename;
    state.className='game-badge '+(thisPath?'verified':'unknown');state.textContent=thisPath?'Loaded from this path'+(uncertainNames.has(moduleName)?' · unload unconfirmed':''):otherPath?'Loaded from another path':listed?'Loaded · path unknown':moduleListComplete?'Not loaded':'Module list incomplete';
    heading.append(title,state);path.className='mono plugin-file-path';path.textContent=item.path;
    actions.className='game-actions plugin-file-actions';
    if(capabilities.load&&moduleListComplete&&!listed){const load=button('Load module',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');const loaded=await api('plugins/load',{path:item.path,sha256:item.inspection.sha256,confirmed:true,route:$('plugin-route').value});notice(filename.toLowerCase()==='nebulahcompanion.xex'?'Nebulah Companion loaded. SHA-256 '+loaded.sha256+'; review: '+loaded.review_status+'.':loaded.name+' listed on console through '+loaded.route+' from '+loaded.runtime_path+'. In-game features are not verified. SHA-256 '+loaded.sha256+'; review: '+loaded.review_status+'.');await showInventory();});load.className='primary';actions.append(load);}
    if(capabilities.unload&&thisPath&&unloadReadyNames.has(moduleName))actions.append(button('Unload module',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');await unloadModule(filename);}));
    else if(capabilities.force_release&&moduleListComplete&&listed&&!otherPath&&forceReadyNames.has(moduleName)&&!managedActionNames.has(moduleName)){
      managedActionNames.add(moduleName);
      actions.append(button('Force release…',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');const managed=await api('plugins/managed-state',{name:filename});if(managed.state!=='release-uncertain')throw Error('Only a failed Nebulah-managed unload can be force released.');openForceRelease(filename);}));
    }
    else if(capabilities.component&&listed&&!otherPath&&!uncertainNames.has(moduleName)&&!managedActionNames.has(moduleName)&&!/^NebulahCompanion(?:-[A-Za-z0-9_]+)?\.xex$/i.test(filename)){
      managedActionNames.add(moduleName);
      actions.append(button('Unload managed module by name',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');const managed=await api('plugins/managed-state',{name:filename});if(managed.state!=='managed')throw Error('This module is '+managed.state.replace('-', ' ')+'. Managed unload is unavailable.');await unloadModule(filename);}));
    }
    actions.append(button('Inspect current file',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');await inspectPluginFile(item.path);}));
    actions.append(button('Remove',async()=>{if(generation!==pluginWorkspaceGeneration||!connected)throw Error('Plugin workspace changed. Refresh first.');await api('plugins/forget',{path:item.path,sha256:item.inspection.sha256});await loadPluginWorkspace();notice(filename+' removed from saved inspections. Console file and loaded module unchanged.');}));
    summary.textContent='Inspection details';details.append(summary);
    detail(details,'Console path',item.path);
    detail(details,'File classification','Structurally marked DLL/plugin; not a title launch');
    detail(details,'Measured SHA-256',item.inspection.sha256);
    detail(details,'Last inspection',new Date(item.inspection.inspected_at*1000).toLocaleString());
    detail(details,'Runtime state',listed&&moduleName==='nebulahcompanion.xex'&&thisPath?'Nebulah loaded this file. In-game features are unverified.':thisPath?'Nebulah selected this file and sent '+bridgePath+' to the loader during this bridge session; the current module name matches. In-game features are unverified.':otherPath?'Nebulah selected '+selectedPath+' and sent '+bridgePath+' to the loader during this bridge session; the current module name matches.':listed?'Module name is listed on console; loaded file path and bytes are unknown':moduleListComplete?'Module name not listed on console':'Module list is incomplete or unavailable; runtime state is unknown');
    if(uncertainNames.has(moduleName))detail(details,'Unload attempt','Kernel accepted one unload call, but the module stayed listed. Do not retry in this bridge session.');
    row.append(heading,path,actions,details);$('plugin-files').append(row);
  }
  filterInspectedPlugins();
}
async function inspectPluginFile(path){
  requireGameConnection();const generation=pluginWorkspaceGeneration;
  const result=await api('plugins/inspect',{path});if(generation!==pluginWorkspaceGeneration||!connected)return;
  $('plugin-inspect-result').textContent='DLL/plugin inspected · '+result.size+' bytes · review: '+result.review_status+' · SHA-256 '+result.sha256+'. '+result.note;
  await loadPluginWorkspace();
}
const readModuleInventory=showInventory;showInventory=async()=>{const generation=gameLibraryGeneration;await loadPluginWorkspace();if(generation===gameLibraryGeneration)await readModuleInventory();};
$('plugin-inspect-form').onsubmit=event=>{event.preventDefault();task(async()=>{try{await inspectPluginFile($('plugin-inspect-path').value.trim());}catch(error){$('plugin-inspect-result').textContent=error.message;throw error;}});};
let previewTitleId=null;
function resetPreviewLookup(){previewTitleId=null;$('preview-title-lookup').disabled=true;}
function applyPreviewTitle(result){$('game-preview-name').textContent=result.title;$('game-preview-source').textContent=result.source+(result.cached?' · cached':'')+' · display metadata only';if(result.cover){const image=document.createElement('img');image.src=result.cover;image.alt=result.title+' cover';image.onerror=()=>{$('game-cover').textContent='Artwork unavailable';};$('game-cover').replaceChildren(image);}else $('game-cover').textContent='Artwork unavailable';}
async function offerTitleLookup(id){previewTitleId=/^[0-9A-F]{8}$/i.test(id||'')&&id!=='00000000'?id:null;$('preview-title-lookup').disabled=!previewTitleId;if(!previewTitleId)return;$('metadata-id').value=id;const generation=gamePreviewGeneration;try{const cached=await api('metadata/lookup',{title_id:id});if(cached.state==='available'&&generation===gamePreviewGeneration&&$('game-preview-dialog').open&&previewTitleId===id)applyPreviewTitle(cached);}catch{}}
$('preview-title-lookup').onclick=()=>task(async()=>{
  const id=previewTitleId,generation=gamePreviewGeneration;if(!id)return;
  const current=()=>generation===gamePreviewGeneration&&$('game-preview-dialog').open&&previewTitleId===id;
  $('game-preview-source').textContent='Looking up community title and artwork…';
  try{const result=await api('metadata/lookup',{title_id:id,online:true});if(current())applyPreviewTitle(result);}
  catch(error){if(current())$('game-preview-source').textContent='Title lookup unavailable. '+error.message;throw error;}
});
function renderTitle(result){const panel=$('metadata-result');panel.replaceChildren();if(result.cover){const image=document.createElement('img');image.src=result.cover;image.alt=result.title+' cover';image.className='lookup-cover';image.onerror=()=>{image.remove();detail(panel,'Artwork','Image could not be displayed.');};panel.append(image);}for(const [label,key] of [['Title','title'],['Title ID','title_id'],['Developer','developer'],['Publisher','publisher'],['Source','source']])detail(panel,label,result[key]);detail(panel,'Metadata',result.cached?'Cached community data':'Community lookup; display only');detail(panel,'Artwork',result.cover?'Available':'Unavailable; title information is still usable');if(result.fetched_at)detail(panel,'Fetched',new Date(result.fetched_at*1000).toLocaleString());}
$('metadata-form').onsubmit=e=>{e.preventDefault();task(async()=>{const id=$('metadata-id').value.trim();$('metadata-result').textContent='Looking up community metadata…';try{const result=await api('metadata/lookup',{title_id:id,online:true});renderTitle(result);}catch(error){$('metadata-result').textContent='Metadata unavailable. Existing verification results are unchanged.';throw error;}});};
let alertSettings={enabled:false,cpu:80,gpu:80},alerted={cpu:false,gpu:false};
try{const saved=JSON.parse(localStorage.getItem('nebulah-alerts')||'null');if(saved&&typeof saved.enabled==='boolean'&&['cpu','gpu'].every(k=>Number.isFinite(saved[k])&&saved[k]>=40&&saved[k]<=110))alertSettings=saved;}catch{}
$('alerts-enabled').checked=alertSettings.enabled;$('alert-cpu').value=alertSettings.cpu;$('alert-gpu').value=alertSettings.gpu;
$('alerts-form').onsubmit=e=>{e.preventDefault();const cpu=Number($('alert-cpu').value),gpu=Number($('alert-gpu').value);if(![cpu,gpu].every(v=>Number.isFinite(v)&&v>=40&&v<=110))return;alertSettings={enabled:$('alerts-enabled').checked,cpu,gpu};alerted={cpu:false,gpu:false};try{localStorage.setItem('nebulah-alerts',JSON.stringify(alertSettings));}catch{}$('alerts-message').textContent='Alert thresholds saved in this browser.';if(!alertSettings.enabled)$('temperature-alert').hidden=true;};
$('notification-enable').onclick=async()=>{try{if(!window.isSecureContext||!('Notification' in window))throw Error();const permission=await Notification.requestPermission();$('alerts-message').textContent='Browser notifications: '+permission;}catch{$('alerts-message').textContent='Browser notifications are unavailable here. In-app alerts remain available.';}};
if(!window.isSecureContext||!('Notification' in window)){$('notification-enable').disabled=true;$('notification-enable').textContent='Browser notifications need HTTPS';}
let launchConfirmationToastSeen=false;
function companionStatus(status){
  const tracking=status.launch_tracking;
  if(tracking){$('launch-tracking').hidden=false;$('launch-tracking').textContent=({accepted:'Launch command accepted. Waiting for the running title to change…','confirmed-path':'Running executable matches the requested launch.','confirmed-executable-name':'Running executable name and Title ID match; exact file path was not confirmed.','confirmed-title-id':'Requested Title ID is now running; exact executable path was not confirmed.',unconfirmed:'Launch is unconfirmed after 60 seconds. The title may be running without telemetry; inspect the console before retrying.'})[tracking.state]||'Launch state unavailable.';}
  if(tracking&&!launchConfirmationToastSeen&&['confirmed-path','confirmed-executable-name','confirmed-title-id'].includes(tracking.state)){
    launchConfirmationToastSeen=true;
    showToast(tracking.state==='confirmed-path'?'Game or app launch confirmed: running XEX matches.':tracking.state==='confirmed-executable-name'?'Game or app executable name and Title ID observed; exact path unavailable.':'Game or app Title ID confirmed; exact XEX path unavailable.');
  }
  if(!alertSettings.enabled)return;const hot=[];
  for(const key of ['cpu','gpu']){const value=status.temperatures?.[key];if(typeof value!=='number'||!Number.isFinite(value))continue;if(value<alertSettings[key]-3)alerted[key]=false;
    if(value>=alertSettings[key]){const message=key.toUpperCase()+' '+value.toFixed(1)+' °C (threshold '+alertSettings[key]+' °C)';hot.push(message);if(!alerted[key]){alerted[key]=true;log('Temperature alert: '+message);showToast('Temperature alert: '+message,'warning');try{if(window.isSecureContext&&Notification.permission==='granted')new Notification('Nebulah temperature alert',{body:message});}catch{}}}}
  $('temperature-alert').hidden=!hot.length;$('temperature-alert').textContent=hot.join(' · ');
}
function trackLaunchAccepted(){launchConfirmationToastSeen=false;$('launch-tracking').hidden=false;$('launch-tracking').textContent='Launch command accepted. Waiting for status confirmation…';}
function resetCompanion(){favoriteSelection=null;gamesWorkCancelled=true;libraryStorageSelection=null;gamesLookupAttempted.clear();gamesWorkControls(false);hideIdentifyToast();setGamesProgress('Reconnect to continue scanning or identification.');resetPluginWorkspace();$('plugin-file-search').value='';$('plugin-inspect-path').value='';$('plugin-inspect-result').textContent='';if($('favorite-dialog').open)$('favorite-dialog').close();
  if($('download-browser-dialog').open)$('download-browser-dialog').close();$('download-files').replaceChildren();$('download-path').value='';previewTitleId=null;$('preview-title-lookup').disabled=true;alerted={cpu:false,gpu:false};$('temperature-alert').hidden=true;$('launch-tracking').hidden=true;$('favorites-list').replaceChildren();$('recent-list').replaceChildren();$('capacity-list').replaceChildren();$('library-results').replaceChildren();$('metadata-result').replaceChildren();libraryFiles=[];scanCancel=true;transferCancel=true;}
// Incremental SHA-256 keeps file hashing available on LAN HTTP without WebCrypto.
class FileHash {
  constructor(){this.h=new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);this.buffer=new Uint8Array(64);this.used=0;this.length=0;}
  update(bytes){this.length+=bytes.length;for(let i=0;i<bytes.length;){const n=Math.min(64-this.used,bytes.length-i);this.buffer.set(bytes.subarray(i,i+n),this.used);this.used+=n;i+=n;if(this.used===64){this.block(this.buffer);this.used=0;}}return this;}
  block(bytes){const k=FileHash.K,w=new Uint32Array(64),rotate=(x,n)=>(x>>>n)|(x<<(32-n));for(let i=0;i<16;i++)w[i]=(bytes[4*i]<<24)|(bytes[4*i+1]<<16)|(bytes[4*i+2]<<8)|bytes[4*i+3];for(let i=16;i<64;i++){const a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rotate(a,7)^rotate(a,18)^(a>>>3))+w[i-7]+(rotate(b,17)^rotate(b,19)^(b>>>10)))>>>0;}let [a,b,c,d,e,f,g,h]=this.h;for(let i=0;i<64;i++){const t1=(h+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i])>>>0,t2=((rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c)))>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}[a,b,c,d,e,f,g,h].forEach((v,i)=>this.h[i]=(this.h[i]+v)>>>0);}
  hex(){const bits=this.length*8;this.buffer[this.used++]=128;if(this.used>56){this.buffer.fill(0,this.used);this.block(this.buffer);this.used=0;}this.buffer.fill(0,this.used,56);const view=new DataView(this.buffer.buffer);view.setUint32(56,Math.floor(bits/4294967296));view.setUint32(60,bits>>>0);this.block(this.buffer);return Array.from(this.h,v=>v.toString(16).padStart(8,'0')).join('');}
}
FileHash.K=new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
let transferCancel=false,partialCleanupState=null;
const partialCleanupButton=document.createElement('button');partialCleanupButton.className='secondary';partialCleanupButton.type='button';partialCleanupButton.textContent='Remove failed partial';partialCleanupButton.hidden=true;
const transferStatusPanel=document.querySelector('.transfer-status')||document.body;transferStatusPanel.append(partialCleanupButton);
function offerPartialCleanup(state){
  if(!state?.remote_partial_possible||!state.temporary)return;
  partialCleanupState=state;partialCleanupButton.hidden=false;
}
partialCleanupButton.onclick=()=>task(async()=>{
  const state=partialCleanupState;if(!state)return;
  if(typeof window.confirm==='function'&&!window.confirm('Remove this exact failed upload partial?'))return;
  let recoveryConfirmed=false;
  if(consoleRecoveryHold){if(typeof window.confirm!=='function'||!window.confirm('Confirm console is responsive before cleanup?'))return;recoveryConfirmed=true;}
  const result=await api('transfer/cleanup',{id:state.id,path:state.temporary,confirmed:true,recovery_confirmed:recoveryConfirmed});
  partialCleanupState=null;partialCleanupButton.hidden=true;$('transfer-message').textContent='Failed upload partial removed.';return result;
});
const transferApi=api;api=async(...args)=>{const result=await transferApi(...args);if(args[0]==='transfer/cancel')offerPartialCleanup(result);return result;};
$('transfer-cancel').onclick=()=>{transferCancel=true;$('transfer-message').textContent='Cancellation requested; waiting for the active operation to return…';};
$('upload-file').onchange=()=>{$('upload-name').value=$('upload-file').files[0]?.name||'';};
function encodeBytes(bytes){let text='';for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text);}
function decodeBytes(text){return Uint8Array.from(atob(text),c=>c.charCodeAt(0));}
async function runTransfer(direction,path,file){
  transferCancel=false;$('transfer-cancel').disabled=false;$('transfer-progress').value=0;view('library');let state=null;const chunks=[],hash=new FileHash();
  try{
    let sha256;
    if(file){if(file.size>128*1024*1024)throw Error('Maximum transfer size is 128 MiB.');const initial=new FileHash();for(let offset=0;offset<file.size;offset+=1048576){if(transferCancel){$('transfer-message').textContent='Cancelled before upload.';return;}initial.update(new Uint8Array(await file.slice(offset,offset+1048576).arrayBuffer()));$('transfer-message').textContent='Hashing upload '+Math.min(100,Math.round((offset+1048576)/file.size*100))+'%';}sha256=initial.hex();}
    state=await api('transfer/start',{direction,path,size:file?.size,sha256,confirmed:direction==='upload',upload_protocol:2});
    if(direction==='upload'){
      if(typeof state.path!=='string')throw Error('Bridge did not return the upload destination. Restart the local bridge.');
      if(state.path!==path){
        const proposed=state.path;
        const message='Console filename adjusted for compatibility:\n'+path.split('\\').pop()+' → '+proposed.split('\\').pop()+'\n\nUpload to '+proposed+'?';
        $('transfer-message').textContent=message;
        if(typeof window.confirm!=='function'||!window.confirm(message)){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Upload cancelled before console write.';return;}
        path=proposed;$('upload-name').value=path.split('\\').pop();
      }
    }
    while(state.offset<state.size){
      if(transferCancel){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Cancelled.'+(state.remote_partial_possible?' Partial file may remain: '+state.temporary:'');return;}
      const payload={id:state.id,offset:state.offset};if(file)payload.content=encodeBytes(new Uint8Array(await file.slice(state.offset,state.offset+state.chunk_size).arrayBuffer()));
      if(direction==='download'&&state.offset===0){$('transfer-message').textContent='Receiving console file on the PC…';$('transfer-progress').removeAttribute('value');}
      state=await api('transfer/chunk',payload);
      if(direction==='download'){const bytes=decodeBytes(state.content);hash.update(bytes);chunks.push(bytes);}
      $('transfer-progress').value=state.size?100*state.offset/state.size:100;$('transfer-message').textContent=(direction==='upload'?'Staging on PC':direction)+' · '+bytesLabel(state.offset)+' / '+bytesLabel(state.size);
    }
    if(transferCancel){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Cancelled before finalizing.'+(state.remote_partial_possible?' Partial file may remain: '+state.temporary:'');return;}
    do {
      if(transferCancel){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Cancelled before finalizing.'+(state.remote_partial_possible?' Partial file may remain: '+state.temporary:'');return;}
      if(direction==='upload'){
        $('transfer-progress').removeAttribute('value');
        if(state.phase==='checked'){
          const report=state.checkpoint;
          if(!report||!state.consent||report.sha256!==sha256||report.size!==file?.size||!report.registry||!['unknown','candidate-match','reviewed-match'].includes(report.registry.status)||typeof report.note!=='string')throw Error('Executable checkpoint report missing or inconsistent. Update the local bridge.');
          const category=report.component?gameCategoryLabels[report.component.category]:'Unclassified executable';
          const message='Staged executable: '+(report.component?.name||path.split('\\').pop())+'\nCategory hint: '+category+'\nStructure: '+(report.plugin?'DLL/plugin':'Application')+'\nBytes: '+report.size+'\nReview: '+report.registry.status+'\nSHA-256: '+report.sha256+(report.component?.observed_hash_match?'\nObserved public hash matched; unreviewed.':'')+'\n'+report.note+'\n\nUpload these bytes to '+path+'?';
          $('transfer-message').textContent=message;
          if(typeof window.confirm!=='function'||!window.confirm(message)){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Executable upload cancelled before console write.';return;}
          state=await api('transfer/approve',{id:state.id,consent:state.consent,confirmed:true});
          if(transferCancel){state=await api('transfer/cancel',{id:state.id});$('transfer-message').textContent='Executable upload cancelled before console write.';return;}
          if(state.phase!=='approved'||state.state!=='running')throw Error('Executable upload approval was not accepted.');
        }
        $('transfer-message').textContent=({staging:'Inspecting staged bytes before upload…',approved:'Sending approved executable to console…',sent:'Reading back and verifying full SHA-256…',verified:'Finalizing verified upload…'})[state.phase]||'Finalizing…';
      }
      state=await api('transfer/finish',{id:state.id});
    } while(state.state!=='completed');
    if(direction==='download'){
      if(hash.hex()!==state.sha256)throw Error('Download hash mismatch. File was not offered for saving.');
      const url=URL.createObjectURL(new Blob(chunks)),a=document.createElement('a');a.href=url;a.download=path.split('\\').pop();document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    }
    if(direction==='upload')$('download-path').value=path;
    $('transfer-progress').value=100;$('transfer-message').textContent=(direction==='download'?'Verified bytes; browser save requested':'Completed')+' · SHA-256 '+state.sha256;log(direction==='download'?'Console file verified; browser save requested.':'File transfer completed with hash verification.');
  }catch(error){if(state){try{state=await api('transfer/cancel',{id:state.id});}catch{}}$('transfer-message').textContent='Transfer failed. '+error.message+(state?.temporary&&(state.remote_partial_possible||error.recoveryRequired&&direction==='upload')?' Partial file may remain: '+state.temporary:'');throw error;}
  finally{$('transfer-cancel').disabled=true;}
}
async function downloadFile(path){await runTransfer('download',path);}
$('upload-form').onsubmit=e=>{e.preventDefault();task(async()=>{const file=$('upload-file').files[0],name=$('upload-name').value.trim();if(!connected||!file||!$('path').value||!$('upload-confirm').checked)throw Error('Connect, choose a destination folder and confirm the upload.');if(/[\\/\x00-\x1f]/.test(name)||['.','..'].includes(name))throw Error('Use a filename without path separators or control characters.');await runTransfer('upload',$('path').value.replace(/\\?$/,'\\')+name,file);$('upload-confirm').checked=false;});};

// Independent picker: use the same real listing API and ordering as Console storage.
async function browseDownloadFolder(path){
  if(!connected)throw Error('Connect a console first.');
  const panel=$('download-files');panel.replaceChildren();$('download-crumbs').replaceChildren();$('download-count').textContent='';
  $('download-folder').value=path||'';$('download-up').disabled=!path||!path.replace(/\\$/, '').includes('\\');
  if(!path){$('download-browser-message').textContent='No storage roots available. Choose Discover storage to retry.';return;}
  $('download-browser-message').textContent='Loading folder…';
  try{
    const result=await api('browse',{path});if(!$('download-browser-dialog').open)return;
    const folder=path.replace(/\\?$/,'\\');
    for(const file of sortedFiles(result.files)){
      const row=document.createElement('div');row.className='file-row';row.dataset.name=file.name;row.dataset.directory=String(Boolean(file.directory));
      const icon=document.createElement('span');icon.className='file-icon';icon.textContent=file.directory?'▱':'◇';
      const meta=document.createElement('div'),name=document.createElement('b'),size=document.createElement('small');name.textContent=file.name;size.textContent=file.directory?'Directory':bytesLabel(file.size||0);meta.append(name,size);row.append(icon,meta);
      row.append(button(file.directory?'Open folder →':consoleFilePickerMode==='plugin'||consoleFilePickerMode==='launch-plugin'?'Use this XEX':'Use this file',async()=>{
        if(file.directory){await browseDownloadFolder(folder+file.name+'\\');return;}
        if(consoleFilePickerMode==='launch-plugin'){
          if(!/\.xex$/i.test(file.name))throw Error('Choose an XEX plugin file.');
          const input=document.querySelector('[data-launch-plugin-slot="'+launchPluginPickerSlot+'"]');
          if(!input)throw Error('Refresh active plugin slots before choosing a file.');
          input.value=folder+file.name;updateLaunchPluginReview();
          $('download-browser-dialog').close();input.focus();
        }else if(consoleFilePickerMode==='plugin'){
          if(!/\.xex$/i.test(file.name))throw Error('Choose an XEX module file.');
          $('plugin-inspect-path').value=folder+file.name;
          $('plugin-inspect-result').textContent='Selected console file. Inspect it before loading.';
          $('download-browser-dialog').close();$('plugin-inspect-path').focus();
        }else{$('download-path').value=folder+file.name;$('download-browser-dialog').close();$('download-path').focus();}
      }));panel.append(row);
    }
    browserTools('download',folder);
    $('download-browser-message').textContent=!result.files.length?'This directory is empty.':result.listing?.truncated||result.listing?.rejected?'Some entries could not be shown. Refine the folder or check Console storage for listing details.':consoleFilePickerMode==='launch-plugin'?'Choose an XEX for this boot slot. Selection does not load it.':consoleFilePickerMode==='plugin'?'Choose an XEX to inspect. Selection does not load it.':'Choose a file to fill in the download path.';
  }catch(error){$('download-browser-message').textContent='Could not open folder. '+error.message;throw error;}
}
async function loadDownloadRoots(rediscover=false){
  const roots=rediscover?(await api('storage/discover')).drives:Array.from($('drive').options,o=>o.value).filter(Boolean);
  $('download-drive').replaceChildren();for(const root of roots)$('download-drive').append(Object.assign(document.createElement('option'),{value:root,textContent:root}));
  const current=$('download-folder').value||(consoleFilePickerMode==='download' ? $('path').value : '');
  const root=roots.find(r=>current.toLowerCase().startsWith(r.toLowerCase()))||roots[0]||'';
  $('download-drive').value=root;
  await browseDownloadFolder(root&&current.toLowerCase().startsWith(root.toLowerCase())?current:root);
}
async function openConsoleFilePicker(mode){
  if(!connected)throw Error('Connect a console first.');
  consoleFilePickerMode=mode;
  $('download-browser-title').textContent=mode==='launch-plugin'?'Choose a boot plugin XEX':mode==='plugin'?'Choose a plugin XEX to inspect':'Choose a file to download';
  $('download-search').value='';$('download-filter').value=mode==='plugin'||mode==='launch-plugin'?'xex':'all';$('download-filter').disabled=mode==='plugin'||mode==='launch-plugin';
  const selected=mode==='launch-plugin'?(document.querySelector('[data-launch-plugin-slot="'+launchPluginPickerSlot+'"]')?.value||''):mode==='plugin' ? $('plugin-inspect-path').value.trim() : $('drive').value;
  $('download-folder').value=(mode==='plugin'||mode==='launch-plugin')&&/\.xex$/i.test(selected)?selected.slice(0,selected.lastIndexOf('\\')+1):selected;
  $('download-browser-dialog').showModal();$('download-browser-message').textContent='Loading storage…';
  try{await loadDownloadRoots(true);}catch(error){$('download-browser-message').textContent='Could not load storage. '+error.message;throw error;}
}
$('download-browse').onclick=()=>task(()=>openConsoleFilePicker('download'));
$('plugin-browse').onclick=()=>task(()=>openConsoleFilePicker('plugin'));
$('download-drive').onchange=()=>task(()=>browseDownloadFolder($('download-drive').value));
$('download-discover').onclick=()=>task(async()=>{try{await loadDownloadRoots(true);}catch(error){$('download-browser-message').textContent='Storage discovery failed. '+error.message;throw error;}});
$('download-refresh').onclick=()=>task(()=>browseDownloadFolder($('download-folder').value));
$('download-up').onclick=()=>task(async()=>{const path=$('download-folder').value.replace(/\\$/,'');const i=path.lastIndexOf('\\');if(i>=0)await browseDownloadFolder(path.slice(0,i+1));});
$('download-form').onsubmit=e=>{e.preventDefault();task(async()=>{if(!connected)throw Error('Connect a console first.');const path=$('download-path').value.trim();if(!path)throw Error('Enter a console file path.');await downloadFile(path);});};
