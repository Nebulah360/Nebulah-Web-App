'use strict';
const $=id=>document.getElementById(id);let token='',connected=false,selected=null,busy=false;let sessionActive=false,lastUpdated=0,authEpoch=0,browserPaired=false;
const titles={usb:['USB tools','Inspect USB disks connected to this PC.'],discover:['Discover games','Browse Xbox 360 game metadata from IGDB.'],rte:['RTE / RTM','Inspect the running title module.'],'live-editing':['Live game editing','Check the running Call of Duty title and editing availability.'],console:['Console','Power, Xbox notifications and device tools.'],settings:['Settings','Console targets, profiles and command access.'],'workspace-tools':['Companion tools','Storage capacity, library scanning and title metadata.'],games:['Games','Your game library, saved copies and XEX shortcuts.'],repositories:['Repository updates','Preset projects and your saved repositories.'],overview:['Console overview','A clear view of your console, close to home.'],library:['File transfer','Browse console storage, upload files and download verified copies.'],stream360:['Live viewer','Watch Xbox 360 video and hear audio over your local network.'],plugins:['Plugin adapters','A dedicated home for console-side extensions.'],activity:['Session activity','Connection, launch and running-title changes for this browser session.']};
function notice(t){$('notice').textContent=t}function log(t){if($('events').firstElementChild?.textContent==='No actions yet.')$('events').replaceChildren();let li=document.createElement('li'),time=document.createElement('time');time.textContent=new Date().toLocaleTimeString();li.append(time,document.createTextNode(t));$('events').prepend(li);if($('events').children.length>100)$('events').lastElementChild.remove()}
let observedTitle=null,preserveObservedTitle=false;
function recordTitleTransition(s,wasConnected){
  if(!wasConnected&&!preserveObservedTitle)observedTitle=null;
  const title=s.current_title||{},id=title.title_id,path=title.executable;
  if(!/^[0-9A-F]{8}$/.test(id||'')||typeof path!=='string'||!path)return;
  const name=path.split(/[\\/]/).pop(),key=id+'|'+name.toLowerCase();
  if(observedTitle&&observedTitle!==key)log('Running title changed: '+name+' · '+id);
  observedTitle=key;
  preserveObservedTitle=false;
}
let connectionToastTimer;
function showToast(message,tone='success'){const toast=$('connection-toast');document.body.append(toast);toast.textContent=message;toast.dataset.tone=tone;toast.setAttribute('role',tone==='error'?'alert':'status');toast.hidden=false;clearTimeout(connectionToastTimer);connectionToastTimer=setTimeout(()=>{toast.hidden=true},tone==='error'?7000:4500)}
function showConnectionToast(){showToast('Console connected through Neighborhood.')}
let consoleNotifyAvailable=false;
function setPowerControls(enabled){if(typeof setControllerConnected==='function')setControllerConnected(enabled);for(const button of document.querySelectorAll('[data-console-power]'))button.disabled=!enabled;$('console-storage-compare').disabled=!enabled;$('console-screen-capture').disabled=!enabled;if(!enabled){consoleNotifyAvailable=false;$('console-storage-result').textContent='Connect a console to compare storage paths.';$('footer-notify-status').textContent='Connect a console to check JRPC2.';$('console-screen-image').removeAttribute('src');$('console-screen-image').hidden=true;$('console-screen-status').textContent='Connect a console to capture its screen.'}else{if($('console-storage-result').textContent.startsWith('Connect a console'))$('console-storage-result').textContent='Ready to compare storage.';if($('footer-notify-status').textContent.startsWith('Connect a console'))$('footer-notify-status').textContent='Ready to check JRPC2.';if($('console-screen-status').textContent.startsWith('Connect a console'))$('console-screen-status').textContent='Ready to capture one Xbox frame.'}$('console-notify-send').disabled=!enabled||!consoleNotifyAvailable}
async function refreshConsoleControls(){if(!connected){$('console-notify-result').textContent='Connect a console to check JRPC2 notification support.';$('footer-notify-status').textContent='Connect a console to check JRPC2.';return;}const capability=await api('plugins/capabilities');consoleNotifyAvailable=capability.load===true;setPowerControls(connected);const message=consoleNotifyAvailable?'JRPC2 responding. Send a test message, then check the Xbox screen.':'JRPC2 notification unavailable. A listed module does not prove its command handler is responding.';$('console-notify-result').textContent=message;$('footer-notify-status').textContent=message}
let pendingLaunchIni=null, pendingLaunchPluginPreview=null, launchPluginPickerSlot=0, activeLaunchPluginSlots=[];
$('launch-plugin-review').hidden=true;
function updateLaunchPluginReview(){
  const inputs=Array.from(document.querySelectorAll('[data-launch-plugin-slot]'));
  inputs.forEach((input,i)=>{
    const path=input.value.trim(),card=input.closest('.launch-plugin-card'),changed=path!==activeLaunchPluginSlots[i];
    card.querySelector('h3').textContent=path?path.split(/[\\/]/).pop():'Empty slot';
    card.querySelector('.game-badge').textContent=changed?'Pending change':path?'Configured for boot':'Available';
    card.querySelector('.launch-plugin-observation').textContent=changed?'Review before saving; running modules are unchanged.':card.dataset.observation;
  });
  $('launch-plugin-review').disabled=inputs.length!==5||inputs.every((input,i)=>input.value.trim()===activeLaunchPluginSlots[i]);
}
async function refreshLaunchIniPlugins(){
  pendingLaunchPluginPreview=null;activeLaunchPluginSlots=[];
  $('launch-plugin-slots').replaceChildren();$('launch-plugin-review').disabled=true;
  $('launch-plugin-status').textContent='Reading five slots and running module names…';
  try{
    const result=await api('console/launch-ini/plugins');
    if(result.state!=='verified'||!Array.isArray(result.slots)||result.slots.length!==5)throw Error('Plugin slot read was not verified.');
    activeLaunchPluginSlots=result.slots.map(slot=>slot.path||'');
    $('launch-plugin-status').textContent='Configured in '+result.active_path+' · read-only in this beta.';
    for(const slot of result.slots){
      const row=document.createElement('article');row.className='game-card plugin-file-row launch-plugin-card';
      const heading=document.createElement('div'),number=document.createElement('small'),title=document.createElement('h3'),state=document.createElement('span');
      heading.className='plugin-file-heading';number.className='launch-plugin-slot-number';number.textContent='PLUGIN '+slot.number;
      title.textContent=slot.path?slot.path.split(/[\\/]/).pop():'Empty slot';
      state.className='game-badge unknown';state.textContent=slot.path?'Configured for boot':'Available';
      heading.append(number,title,state);
      const label=document.createElement('label');label.textContent='Console XEX path';
      const input=document.createElement('input');input.type='text';input.maxLength=512;input.spellcheck=false;
      input.placeholder='Empty slot';input.value=slot.path||'';input.readOnly=true;input.dataset.launchPluginSlot=String(slot.number);
      input.setAttribute('aria-label','Plugin '+slot.number+' console XEX path');input.oninput=updateLaunchPluginReview;
      label.append(input);
      const actions=document.createElement('div');actions.className='game-actions plugin-file-actions';
      const browse=document.createElement('button');browse.type='button';browse.className='secondary';browse.textContent='Browse XEX';
      browse.onclick=()=>task(async()=>{launchPluginPickerSlot=slot.number;await openConsoleFilePicker('launch-plugin');});
      browse.hidden=true;actions.append(browse);
      const observation=document.createElement('small');observation.className='launch-plugin-observation';
      observation.textContent=!slot.path?'Empty slot':slot.module_observation==='name-observed'?'Module filename observed running; source path not proven':slot.module_observation==='not-observed'?'Module filename not observed running':'Running module list unavailable';
      row.dataset.observation=observation.textContent;
      row.append(heading,label,observation,actions);$('launch-plugin-slots').append(row);
    }
  }catch(error){$('launch-plugin-status').textContent='Could not read active plugin slots. '+error.message;}
}
async function refreshLaunchIni(){
  pendingLaunchIni=null;
  $('launch-ini-list').replaceChildren();
  if(!connected){$('launch-ini-status').textContent='Connect a console to verify the active launch.ini.';$('launch-plugin-slots').replaceChildren();$('launch-plugin-status').textContent='Connect a console to read plugin slots.';$('launch-plugin-review').disabled=true;return;}
  $('launch-ini-status').textContent='Checking DashLaunch active source and discovered root files…';
  const result=await api('console/launch-ini');
  if(result.state!=='verified'){$('launch-ini-status').textContent='Active launch.ini not verified. '+(result.reason||'Check DashLaunch and XBDM.');$('launch-plugin-slots').replaceChildren();$('launch-plugin-status').textContent='Active file verification required before plugin editing.';$('launch-plugin-review').disabled=true;return;}
  $('launch-ini-status').textContent='Active this session: '+result.active_path;
  for(const item of result.candidates){
    const row=document.createElement('article');row.className='launch-ini-row';
    const heading=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small');
    name.textContent=item.path+(item.active?' · Active':'');
    detail.textContent=item.size+' bytes · SHA-256 '+item.sha256;
    heading.append(name,detail);row.append(heading);
    if(!item.active){const choose=document.createElement('button');choose.type='button';choose.className='secondary';choose.textContent='Use now';choose.onclick=()=>{pendingLaunchIni={path:item.path,sha256:item.sha256};$('launch-ini-choice').textContent=item.path+' · SHA-256 '+item.sha256;$('launch-ini-dialog').showModal();};row.append(choose);}
    $('launch-ini-list').append(row);
  }
  await refreshLaunchIniPlugins();
}
$('launch-plugin-review').onclick=()=>task(async()=>{
  const slots=Array.from(document.querySelectorAll('[data-launch-plugin-slot]'),input=>input.value.trim());
  $('launch-plugin-status').textContent='Inspecting changed XEX files and preparing preview…';
  const preview=await api('console/launch-ini/plugins/preview',{slots});
  if(preview.state!=='ready')throw Error('Plugin changes could not be reviewed.');
  pendingLaunchPluginPreview=preview.preview;
  $('launch-plugin-source').textContent='Active: '+preview.active_path+' · SHA-256 '+preview.source_sha256;
  $('launch-plugin-changes').replaceChildren();
  for(const change of preview.changes){
    const line=document.createElement('p');line.className='mono';
    line.textContent='Plugin '+change.slot+': '+(change.before||'(empty)')+' → '+(change.after||'(empty)');
    $('launch-plugin-changes').append(line);
  }
  for(const inspected of preview.inspections){
    const line=document.createElement('p');line.className='small';
    line.textContent='Slot '+inspected.slot+' · '+inspected.review_status+' · SHA-256 '+inspected.sha256;
    $('launch-plugin-changes').append(line);
  }
  $('launch-plugin-status').textContent='Review ready. Confirm within '+preview.expires_in+' seconds.';
  $('launch-plugin-dialog').showModal();
});
$('launch-plugin-cancel').onclick=()=>{$('launch-plugin-dialog').close();};
$('launch-plugin-dialog').addEventListener('close',()=>{if(pendingLaunchPluginPreview)$('launch-plugin-status').textContent='Preview cancelled. No launch.ini change was saved.';pendingLaunchPluginPreview=null;});
$('launch-plugin-confirm').onclick=()=>task(async()=>{
  if(!pendingLaunchPluginPreview)throw Error('Review plugin slot changes again.');
  const preview=pendingLaunchPluginPreview;pendingLaunchPluginPreview=null;
  $('launch-plugin-confirm').disabled=true;
  try{
    const result=await api('console/launch-ini/plugins/save',{preview,confirmed:true});
    $('launch-plugin-dialog').close();
    if(result.state!=='saved'){
      $('launch-plugin-status').textContent=(result.reason||'Save not confirmed. Inspect launch.ini in Neighborhood before retrying.')+
        (result.backup_path?' Backup: '+result.backup_path:'')+(result.partial_path?' Staged copy: '+result.partial_path:'');
      showToast('Plugin slot save not confirmed. Check active file and recovery copy.','warning');
      return;
    }
    showToast('Plugin slots saved. They apply on next boot.');
    notice('Plugin slots saved. Backup: '+result.backup_path);
    try{await refreshLaunchIni();}catch(error){$('launch-plugin-status').textContent='Saved and verified; refresh failed. '+error.message;}
  }finally{$('launch-plugin-confirm').disabled=false;}
});
$('launch-ini-refresh').onclick=()=>task(refreshLaunchIni);
$('launch-ini-panel').addEventListener('toggle',()=>{if($('launch-ini-panel').open&&connected)task(refreshLaunchIni);});
$('overview-favorites').addEventListener('toggle',()=>{if($('overview-favorites').open&&connected)task(showFavorites);});
$('launch-ini-cancel').onclick=()=>{$('launch-ini-dialog').close();pendingLaunchIni=null;};
$('launch-ini-dialog').addEventListener('close',()=>{pendingLaunchIni=null;});
$('launch-ini-confirm').onclick=()=>task(async()=>{
  if(!pendingLaunchIni)throw Error('Refresh launch.ini files before switching.');
  const selectedFile=pendingLaunchIni;pendingLaunchIni=null;$('launch-ini-confirm').disabled=true;
  try{const result=await api('console/launch-ini-switch',{...selectedFile,confirmed:true});$('launch-ini-dialog').close();await refreshLaunchIni();showToast('DashLaunch now uses '+result.active_path+' for this session.');}
  finally{$('launch-ini-confirm').disabled=false;}
});
function view(v){hideCpuKey();document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==v);document.querySelectorAll('[data-view]').forEach(e=>e.classList.toggle('active',e.dataset.view===v));$('nav-extra').open=['discover','usb','repositories','workspace-tools','activity'].includes(v);$('crumb').textContent=v==='library'?'File transfer':v==='rte'?'RTE / RTM':v==='live-editing'?'Live game editing':v[0].toUpperCase()+v.slice(1);$('page-title').replaceChildren(document.createTextNode(titles[v][0]),Object.assign(document.createElement('span'),{textContent:'.'}));$('page-description').textContent=titles[v][1]}
function closeMobileMenu(){document.body.classList.remove('menu-open');$('mobile-menu-toggle').setAttribute('aria-expanded','false');}
function openWorkspaceView(name){closeMobileMenu();view(name);if(typeof rteViewChanged==='function')rteViewChanged(name);if(name==='games')task(gameLibraryFiles.length?loadShortcutGames:loadGames);else if(name==='overview'&&connected&&$('overview-favorites').open)task(showFavorites);else if(name==='console')task(refreshConsoleControls);else if(name==='settings'&&typeof loadAppSettings==='function')task(loadAppSettings);else if(name==='plugins')task(showInventory);else if(name==='usb'&&typeof refreshUsbInventory==='function')task(refreshUsbInventory);else if(name==='discover'&&typeof refreshDiscover==='function')task(refreshDiscover);else if(name==='rte'&&connected&&typeof refreshRte==='function')task(refreshRte);else if(name==='live-editing'&&connected&&liveEditingTitle?.id==='415607E6')task(refreshLiveEditing);else if(name==='stream360'&&connected&&typeof refreshStream360==='function')task(refreshStream360);}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>openWorkspaceView(b.dataset.view);for(const b of document.querySelectorAll('[data-goto]'))b.onclick=()=>openWorkspaceView(b.dataset.goto);
document.querySelector('aside').id='workspace-navigation';
$('mobile-menu-toggle').onclick=()=>{const open=($('mobile-menu-toggle').getAttribute?.('aria-expanded')??$('mobile-menu-toggle')['aria-expanded'])==='true';document.body.classList.toggle('menu-open',!open);$('mobile-menu-toggle').setAttribute('aria-expanded',String(!open));};
for(const b of document.querySelectorAll('.close'))b.onclick=()=>b.closest('dialog').close();
let lastConnectionDiagnostic='',consoleRecoveryHold=false;
async function api(action,data={}){
  const epoch=authEpoch;
  const moduleAction=action==='plugins/load'?'load':action==='plugins/unload'?'unload':action==='plugins/force-release'?'force release':null;
  try {
    const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},body:JSON.stringify(data),signal:AbortSignal.timeout(['transfer/finish','transfer/chunk','games/title-update','rte/build'].includes(action)?300000:action.startsWith('console/launch-ini/plugins/')?600000:45000)});
    let j;try{j=await r.json()}catch{throw Error('The bridge returned an unreadable response. Open the URL printed by your local bridge.');}
    if(epoch!==authEpoch&&!action.startsWith('session/'))throw Error('Session ended. Reconnect before continuing.');
    if(r.status===401&&action!=='session/phone-pair'&&typeof expireBrowserSession==='function')expireBrowserSession(false);
    if(j.recovery_required||j.diagnostic?.code==='RECOVERY_REQUIRED'){consoleRecoveryHold=true;sessionActive=false;connected=false;setPowerControls(false);clearTelemetry('Recovery required');}
    if(!r.ok){const staleLaunchIni=action==='console/launch-ini'&&r.status===400&&/^Request failed validation or Neighborhood could not complete it\./.test(j.error||'');const friendly=staleLaunchIni?'The running bridge predates launch.ini support. Restart the local bridge, then reconnect.':j.diagnostic?.support_code ? j.diagnostic.reason+' Next: '+j.diagnostic.hint+' ['+j.diagnostic.support_code+']' : j.error;const e=Error(friendly||'The request did not finish. Check the bridge window.');e.diagnostic=j.diagnostic;e.recoveryRequired=Boolean(j.recovery_required);e.httpStatus=r.status;if(j.permission_required){const anchor=document.activeElement;if(anchor?.matches?.('button,[type="submit"]')&&anchor.insertAdjacentElement){const alert=document.createElement('small');alert.className='permission-alert';alert.setAttribute('role','alert');alert.textContent='RED ALERT: Write access is off. Enable it in Settings on this PC.';anchor.nextElementSibling?.classList?.contains('permission-alert')?anchor.nextElementSibling.replaceWith(alert):anchor.insertAdjacentElement('afterend',alert);}}if(moduleAction){const name=moduleAction!=='load'&&/^[A-Za-z0-9_.-]{1,128}\.xex$/i.test(data.name||'')?data.name:'Module';const message=moduleAction==='force release'?name+' force release unconfirmed. Do not retry; check the console and module inventory.':moduleAction==='unload'&&j.diagnostic?.code==='MODULE_UNLOAD_FAILED'&&j.diagnostic?.phase==='module-inventory'?name+' unload unconfirmed. Do not repeat normal unload; check Plugins for one force-release option.':moduleAction==='unload'&&/SAFE_TO_UNLOAD/.test(j.error||'')?name+' unload blocked. Wait for SAFE_TO_UNLOAD in Live viewer.':j.diagnostic?.code==='MODULE_ALREADY_LOADED'?'Module already listed on console. No load sent.':j.diagnostic?.code==='MODULE_LOAD_UNCONFIRMED'?'Module appeared after an unconfirmed load. Do not retry.':name+' '+moduleAction+' failed or was not confirmed. Check loaded modules before retrying.';showToast(message,'error');e.moduleToastShown=true;}throw e;}
    if(moduleAction){if(!j?.name||j.state!==(moduleAction==='load'?'loaded':'unloaded'))throw Error('Module '+moduleAction+' was not confirmed. Check loaded modules before retrying.');const name=/^NebulahCompanion-[A-Za-z0-9_]+\.xex$/i.test(j.name)?'NebulahCompanion.xex':j.name;showToast(name+(moduleAction==='load'?' loaded and listed on console.':moduleAction==='force release'?' force released and absent from console.':' unloaded and absent from console.'),'success');}
    return j;
  } catch(e) {if(moduleAction&&!e.moduleToastShown)showToast(moduleAction==='force release'?'Force release request did not finish. Do not retry; check the console and module inventory.':'Module '+moduleAction+' request did not finish. Check loaded modules before retrying.','error');e.action=action;throw e;}
}
function showConnectionDiagnostic(error){
  // Available even when the bridge cannot respond. Keep aligned with support/errors.json.
  const browserErrors={"PAIRING_REJECTED":{"code":"PAIRING_REJECTED","support_code":"NB-U01","title":"Your browser session expired.","reason":"Your browser session expired.","hint":"Refresh on the bridge PC to pair locally, or enter the Phone PIN on a phone."},"BROWSER_ORIGIN_REJECTED":{"code":"BROWSER_ORIGIN_REJECTED","support_code":"NB-U02","title":"This browser address is not allowed.","reason":"This browser address is not allowed.","hint":"Open the exact URL printed in the bridge window."},"CONNECTION_REQUEST_INVALID":{"code":"CONNECTION_REQUEST_INVALID","support_code":"NB-U04","title":"The connection details were not accepted.","reason":"The connection details were not accepted.","hint":"Use a console name or IP only, without http:// or a port."},"BRIDGE_UNREACHABLE":{"code":"BRIDGE_UNREACHABLE","support_code":"NB-U03","title":"The browser could not reach the bridge.","reason":"The browser could not reach the bridge.","hint":"Keep the bridge window open and use its printed URL."}};
  const fallback=browserErrors[error.httpStatus===401?'PAIRING_REJECTED':error.httpStatus===403?'BROWSER_ORIGIN_REJECTED':error.httpStatus===400?'CONNECTION_REQUEST_INVALID':'BRIDGE_UNREACHABLE'];
  const d=error.diagnostic||fallback;
  const clean=value=>typeof value==='string'?value.slice(0,1200):'';
  const code=clean(d.code),reason=clean(d.reason),fingerprint=code+'|'+reason+'|'+clean(d.phase)+'|'+clean(d.module_status);
  if(fingerprint===lastConnectionDiagnostic&&error.action!=='plugins/load')return;
  lastConnectionDiagnostic=fingerprint;
  hideCpuKey();
  $('connection-error-title').textContent=clean(d.title)||'Connection failed';
  $('connection-error-code').textContent=clean(d.support_code)||code;
  $('connection-error-reason').textContent=reason+(d.support_code?' ['+clean(d.support_code)+']':'');
  $('connection-error-hint').textContent=clean(d.hint);
  const report=['Nebulah Link support report','Support: '+(clean(d.support_code)||code),'Code: '+code,'HRESULT: '+(clean(d.hresult)||'Not reported'),'Phase: '+(clean(d.phase)||'Not reported')];
  if(['selected-path','verified-usb-alias'].includes(d.path_mode))report.push('Module path mode: '+d.path_mode);
  if(/^0x[0-9A-Fa-f]{8}$/.test(d.module_status||''))report.push('Module status: '+d.module_status);
  report.push('Byte offset: '+(Number.isSafeInteger(d.offset)&&d.offset>=0?d.offset:'Not reported'),'Recovery hold: '+(error.recoveryRequired?'yes':'not reported'),'Step: '+(clean(d.stage)||'browser / local bridge'),'PowerShell: '+(clean(d.architecture)||'Not reported'),'Reason: '+reason,'Next step: '+clean(d.hint));
  $('connection-error-report').value=report.join('\n');
  $('connection-error-copy-status').textContent='';
  $('connection-error-technical').open=false;
  if(!$('connection-error-dialog').open)$('connection-error-dialog').showModal();
  if(error.action==='plugins/load'||error.action==='plugins/unload')$('connection-error-dialog').append($('connection-toast'));
}
$('connection-error-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('connection-error-report').value);$('connection-error-copy-status').textContent='Diagnostic copied.';}catch{$('connection-error-report').focus();$('connection-error-report').select();$('connection-error-copy-status').textContent='Press Ctrl+C, or use your phone’s Copy command, to copy the selected diagnostic.';}};
$('connection-error-edit').onclick=()=>{$('connection-error-dialog').close();if(!$('connection-dialog').open)connectDialog();$('target').focus();};
async function task(fn){if(busy)return;busy=true;try{await fn()}catch(e){if(e.action==='status'&&sessionActive&&(!e.httpStatus||e.httpStatus===503)){notice('Local bridge restarting. Retrying the connection…');return;}const summary=e.diagnostic?(e.diagnostic.title||e.diagnostic.reason||'Console action failed')+(e.diagnostic.support_code?' ['+e.diagnostic.support_code+']':''):e.message;notice(summary);if(e.diagnostic||e.action==='connect'||e.action==='status')showConnectionDiagnostic(e);if(!connected){$('connection-label').textContent='Not connected';$('mode').textContent='OFFLINE';$('metric-status').textContent='Offline';$('console-name').textContent='Connection required';$('console-note').textContent='Check the bridge and reconnect.';$('footer-mode').textContent='Local connection required'}log('Action failed: '+summary)}finally{busy=false;if(typeof resumeLibraryStorageSelection==='function')resumeLibraryStorageSelection();}}
function status(s){const wasConnected=connected;lastConnectionDiagnostic='';connected=true;sessionActive=true;setPowerControls(true);if(!wasConnected)showConnectionToast();$('connection-label').textContent='Console connected';$('console-name').textContent='Console connected';$('console-note').textContent='Neighborhood connection is ready.';$('mode').textContent='CONNECTED';$('metric-status').textContent='Connected';$('metric-type').textContent=s.type||'Unavailable';$('metric-kernel').textContent=s.kernel||'Unavailable';$('metric-drives').textContent=s.drives.length;$('browse').disabled=!s.drives.length;$('game-browse').disabled=!s.drives.length;$('footer-mode').textContent='Local session · private data excluded';$('connect').textContent='Change connection';
  recordTitleTransition(s,wasConnected);
  const prev=$('drive').value,oldPath=$('path').value;$('drive').replaceChildren();for(const d of s.drives){const o=document.createElement('option');o.value=d;o.textContent=d;$('drive').append(o)}if(s.drives.includes(prev)){$('drive').value=prev;$('path').value=oldPath}else $('path').value=$('drive').value;
  syncGameDrives(s.drives);
  if(['Connect, then scan to build your library.','Reconnect to continue scanning or identification.'].includes($('games-progress').textContent))$('games-progress').textContent='Choose storage and scan to refresh your library.';
  if(!s.drives.length){$('files').textContent='No storage roots discovered. Refresh console status and open Reading details for the discovery result.';$('game-files').textContent=$('files').textContent;}
  else if(!$('files').textContent.trim()||$('files').textContent.trim()==='Connect a console to browse files.')$('files').textContent='Storage ready. Choose a root and tap Browse to select the upload folder.';
  renderTelemetry(s);
  if(typeof companionStatus==='function')companionStatus(s);
  if(typeof rteOnStatus==='function')rteOnStatus(s);
  liveEditingOnStatus(s);
}
let liveEditingTitle=null,liveEditingModule=null;
function liveEditingReset(message){
  liveEditingTitle=null;liveEditingModule=null;
  $('live-editing-title').textContent='Unavailable';$('live-editing-title-id').textContent='Title ID unavailable';
  $('live-editing-mode').textContent='Not reported';$('live-editing-module').textContent='Not checked';
  $('live-editing-module-range').textContent='Run COD4, then check its module.';
  $('live-editing-build').disabled=true;$('live-editing-build-result').textContent='Check the live title first.';
  $('live-editing-check').disabled=true;$('live-editing-status').textContent=message;
}
function liveEditingOnStatus(s){
  const title=s.current_title||{},id=title.title_id,executable=title.executable;
  const next=/^[0-9A-F]{8}$/.test(id||'')&&typeof executable==='string'&&executable?{id,executable}:null;
  if(!next||liveEditingTitle?.id!==next.id||liveEditingTitle?.executable!==next.executable){
    liveEditingModule=null;$('live-editing-build').disabled=true;$('live-editing-build-result').textContent='Check the live title first.';
    $('live-editing-module').textContent='Not checked';$('live-editing-module-range').textContent='Run COD4, then check its module.';
    $('live-editing-status').textContent=next?.id==='415607E6'?'COD4 reported. Check its live module before any edit.':'No verified edit is available for this running title.';
    liveEditingTitle=next;
  }
  $('live-editing-title').textContent=next?.id==='415607E6'?'Call of Duty 4':executable?.split(/[\\/]/).pop()||'No running title reported';
  $('live-editing-title-id').textContent=id?'Title ID '+id:'Title ID unavailable';
  $('live-editing-mode').textContent='Not reported';
  $('live-editing-check').disabled=next?.id!=='415607E6';
}
async function refreshLiveEditing(){
  if(!connected||liveEditingTitle?.id!=='415607E6')throw Error('Start COD4 and refresh console status first.');
  const title=liveEditingTitle;$('live-editing-status').textContent='Checking the running COD4 module…';
  liveEditingModule=null;$('live-editing-build').disabled=true;$('live-editing-build-result').textContent='Check the live title first.';
  try{
    const result=await api('rte/status');
    if(!connected||liveEditingTitle!==title||result.state!=='ready'||result.title_id!==title.id||result.executable!==title.executable)
      throw Error('The running title changed. Check again.');
    $('live-editing-module').textContent=result.module.name;
    $('live-editing-module-range').textContent=result.module.base+' · '+(result.module.size/1048576).toFixed(1)+' MiB mapped';
    liveEditingModule=result;$('live-editing-build').disabled=false;$('live-editing-build-result').textContent='Ready to measure the on-disk XEX.';
    $('live-editing-status').textContent='COD4 module confirmed for read-only inspection. Exact build, active title update and edit addresses remain unverified.';
  }catch(error){if(liveEditingTitle===title)$('live-editing-status').textContent='Live title check failed: '+error.message;throw error;}
}
$('live-editing-check').onclick=()=>task(refreshLiveEditing);
async function measureOnDiskXex(snapshot){
  const measured=await api('rte/build');
  if(measured.title_id!==snapshot.title_id||(measured.process_path||measured.file?.path)!==snapshot.executable||measured.scope!=='on-disk-xex-only')
    throw Error('The running title changed. Refresh before measuring again.');
  return measured;
}
function onDiskXexText(measured){
  const file=measured.file,resolution=measured.path_resolution==='dashlaunch-3.21-device-alias'?' · Device path mapped through discovered storage and DashLaunch 3.21.':'';
  return file.path+' · SHA-256 '+file.sha256+' · '+file.size+' bytes · Media ID '+file.media_id+' · XEX version '+file.version+' · Base version '+file.base_version+resolution+' On-disk file only; loaded code and active title update are unverified.';
}
$('live-editing-build').onclick=()=>task(async()=>{
  if(!connected||!liveEditingModule)throw Error('Check the live COD4 title first.');
  const title=liveEditingTitle,module=liveEditingModule,result=$('live-editing-build-result');result.textContent='Measuring the on-disk XEX…';
  try{
    const measured=await measureOnDiskXex(module);
    if(!connected||liveEditingTitle!==title||liveEditingModule!==module)throw Error('The running title changed. Check again.');
    result.textContent=onDiskXexText(measured);
  }catch(error){if(liveEditingTitle===title)result.textContent='Build inspection failed: '+error.message;throw error;}
});
$('live-editing-screenshot').onclick=()=>{openWorkspaceView('console');$('console-screen-panel').open=true;$('console-screen-capture').focus();};
function renderTelemetry(s){
  renderTelemetryDetails(s);
  lastUpdated=Date.now();document.querySelector('.live-strip').classList.remove('stale');$('quick-status').textContent='Connected';
  let count=0;for(const key of ['cpu','gpu','edram','motherboard']){const v=s.temperatures?.[key],valid=typeof v==='number'&&Number.isFinite(v)&&v>0&&v<=125;if(valid)count++;const text=valid?v.toFixed(1)+' °C':'Unavailable';$('temp-'+key).textContent=text;$('temp-'+key+'-note').textContent=valid?('Reported sensor'):'See console reading details';if(key==='cpu'||key==='gpu')$('quick-'+key).textContent=valid?text:'—';}
  const t=s.current_title||{},path=t.executable||'',name=t.name||path.split(/[\\/]/).filter(Boolean).pop()||'Unavailable';$('current-title').textContent=name;$('quick-title').textContent=name;$('current-path').textContent=path||'Running executable is not reported by this adapter.';$('current-title-id').textContent=t.title_id||'Unavailable';
  $('telemetry-state').textContent=count===4?'LIVE READINGS':count?'PARTIAL SENSOR SUPPORT':'SENSORS UNAVAILABLE';$('telemetry-note').textContent=count===4?'Readings refresh every 10 seconds while this page is visible.':'Some readings are unavailable. Open Console reading details below for the source and failure reason. Readings refresh every 10 seconds.';updateAge();
}
let telemetryCompatibilityReport='',telemetryCompatibilityMessage='Connect to read plugin support.';
function telemetryCompatibility(s){
  const support=s.plugin_support||{},observed=Array.isArray(support.observed)?support.observed:[],fields=s.telemetry_fields||{};
  if(Object.values(fields).some(f=>f?.state==='COM_BINDING_FAILED'))return 'Neighborhood connected, but Windows could not bind a telemetry COM method. Run tools/diagnose-neighborhood.ps1 to check the installed interface and bridge binding. This does not establish a plugin failure.';
  if(support.jrpc==='responding')return 'JRPC / JRPC2 telemetry is responding. Any missing fields have individual reasons below. XRPC can remain loaded alongside it.';
  if(observed.includes('jrpc2.xex')||observed.includes('jrpc.xex'))return 'JRPC / JRPC2 is visible in loaded modules, but its telemetry commands did not return usable readings. A loaded module does not prove its command handler is responding. Check the field results below; no plugin changes have been made.';
  if(observed.includes('xrpc.xex'))return 'XRPC is visible, but JRPC / JRPC2 telemetry is not responding. XRPC does not implement this consolefeatures interface. The app uses native XBDM fallbacks for available core information; temperature readings need a responding JRPC / JRPC2 handler. XRPC RPC-based sensor reads are not implemented.';
  return 'JRPC / JRPC2 telemetry could not be confirmed. '+(support.module_scan==='ok'?'No recognized JRPC or XRPC module filename was observed. Renamed plugins may not be identified.':'Loaded-plugin detection was unavailable.')+' Native XBDM fallbacks are attempted. See the per-field results before changing plugins.';
}
$('telemetry-help').onclick=()=>{$('telemetry-help-message').textContent=telemetryCompatibilityMessage;$('telemetry-help-report').value=telemetryCompatibilityReport;$('telemetry-help-copy-status').textContent='';$('telemetry-help-dialog').showModal();};
$('telemetry-help-close').onclick=()=>$('telemetry-help-dialog').close();
$('telemetry-help-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('telemetry-help-report').value);$('telemetry-help-copy-status').textContent='Copied.';}catch{$('telemetry-help-report').focus();$('telemetry-help-report').select();$('telemetry-help-copy-status').textContent='Press Ctrl+C or choose Copy to copy the selected report.';}};
function renderTelemetryDetails(s){
  telemetryCompatibilityMessage=telemetryCompatibility(s);
  $('telemetry-compatibility').textContent=telemetryCompatibilityMessage;
  $('metric-motherboard').textContent=s.motherboard||'Unavailable';
  const labels={type:'Console class',kernel:'Kernel build',motherboard:'Motherboard',cpu:'CPU temperature',gpu:'GPU temperature',edram:'eDRAM temperature',board_temperature:'Board temperature',executable:'Running executable',title_id:'Current title ID'};
  const reasons={OK:'Read successfully',UNAVAILABLE:'Not reported',CHANNEL_FAILED:'Command channel could not open',COMMAND_FAILED:'Command could not complete',COMMAND_REJECTED:'Command rejected or unsupported',INVALID_RESPONSE:'Reply format was not recognized',OUT_OF_RANGE:'Reading outside supported range',COM_BINDING_FAILED:'Windows COM method binding failed'};
  const sources={xdevkit:'Neighborhood',xbdm:'XBDM',jrpc:'JRPC',none:'No source'};
  const report=['Telemetry adapter: 10','Backend adapter: '+(s.adapter_version===10?'10':'Older or not reported'),'Storage roots discovered: '+(Array.isArray(s.drives)?s.drives.length:0),'Storage discovery: '+({xdevkit:'Neighborhood',xbdm:'XBDM fallback',none:'No source'}[s.storage?.source]||'Not reported')+' · '+({OK:'Read successfully',EMPTY:'No roots returned',FAILED:'Discovery failed',UNAVAILABLE:'Not reported'}[s.storage?.state]||'Not reported'),telemetryCompatibilityMessage];
  const list=document.createElement('dl');
  for(const [key,label] of Object.entries(labels)){
    const field=s.telemetry_fields?.[key]||{},term=document.createElement('dt'),description=document.createElement('dd');
    term.textContent=label;description.textContent=(sources[field.source]||sources.none)+' · '+(reasons[field.state]||reasons.UNAVAILABLE);list.append(term,description);report.push(term.textContent+': '+description.textContent);
  }
  telemetryCompatibilityReport=report.join('\n');
  $('telemetry-details').replaceChildren(list);
}
function clearTelemetry(reason){if(typeof resetPluginWorkspace==='function')resetPluginWorkspace();if(typeof rteReset==='function')rteReset('Console connection unavailable.');liveEditingReset('Console connection unavailable.');telemetryCompatibilityReport='No current readings.';telemetryCompatibilityMessage='Connect to read plugin support.';$('telemetry-compatibility').textContent=telemetryCompatibilityMessage;$('metric-motherboard').textContent='—';$('telemetry-details').replaceChildren();lastUpdated=0;document.querySelector('.live-strip').classList.add('stale');$('quick-status').textContent=reason;$('quick-title').textContent='Unavailable';$('quick-cpu').textContent='—';$('quick-gpu').textContent='—';$('quick-age').textContent='Not current';$('current-title').textContent='Unavailable';$('current-path').textContent='No current reading.';$('current-title-id').textContent='—';$('telemetry-state').textContent=reason.toUpperCase();for(const key of ['cpu','gpu','edram','motherboard']){$('temp-'+key).textContent='—';$('temp-'+key+'-note').textContent='No current reading';}}
function updateAge(){if(!lastUpdated)return;const seconds=Math.floor((Date.now()-lastUpdated)/1000);$('quick-age').textContent=seconds<2?'Just now':seconds+'s ago';document.querySelector('.live-strip').classList.toggle('stale',seconds>30);if(seconds>30){$('quick-status').textContent='Stale';$('telemetry-state').textContent='STALE / LAST READING';}}
async function refreshStatus(){try{status(await api('status'))}catch(e){connected=false;setPowerControls(false);clearTelemetry('Unavailable');$('connection-label').textContent='Connection unavailable';$('metric-status').textContent='Unavailable';$('mode').textContent='UNAVAILABLE';$('console-note').textContent='Status refresh failed. Retrying while this page is visible.';$('telemetry-note').textContent='Console could not be reached. Last readings have been cleared.';throw e}}
setInterval(updateAge,1000);
setInterval(()=>{if(sessionActive&&!busy&&!document.hidden&&!document.querySelector('dialog[open]'))task(refreshStatus)},10000);

function isPhoneBrowser(){return Boolean(navigator.userAgentData?.mobile||/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent||'')||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1))}
const phoneBrowser=isPhoneBrowser();
$('phone-pin-create').hidden=phoneBrowser;$('phone-pin-enter').hidden=!phoneBrowser;
function openPhonePinEntry(){closeMobileMenu();$('phone-pin-message').textContent='';$('phone-pin-input').value='';$('phone-pin-entry-dialog').showModal();$('phone-pin-input').focus()}
function connectDialog(){preserveObservedTitle=false;hideCpuKey();if(phoneBrowser&&!browserPaired){openPhonePinEntry();return;}$('token').required=false;$('hosted-help').hidden=location.hostname==='127.0.0.1'||location.hostname==='localhost'||/^192\.168\.|^10\.|^172\.(1[6-9]|2\d|3[01])\./.test(location.hostname);$('connection-dialog').showModal()}
$('connect').onclick=connectDialog;$('connection-open').onclick=connectDialog;
$('phone-pin-enter').onclick=openPhonePinEntry;
$('phone-pin-create').onclick=()=>task(async()=>{
  if(!connected||!browserPaired)throw Error('Connect the PC browser to a console first.');
  const epoch=authEpoch,result=await api('session/phone-pin',{});if(epoch!==authEpoch||!connected)return;
  $('phone-pin-code').textContent=result.pin;$('phone-pin-url').textContent=result.url;
  closeMobileMenu();$('phone-pin-create-dialog').showModal();
});
$('phone-pin-form').onsubmit=async e=>{
  e.preventDefault();const pin=$('phone-pin-input').value.trim();
  if(!/^[0-9]{6}$/.test(pin)){$('phone-pin-message').textContent='Enter the six-digit PIN shown on the PC.';return;}
  $('phone-pin-message').textContent='Checking PIN…';$('phone-pin-submit').disabled=true;
  try{const result=await api('session/phone-pair',{pin});startBrowserSession();status(result.status);$('phone-pin-entry-dialog').close();$('phone-pin-input').value='';notice('Phone connected through the PC Neighborhood bridge.');}
  catch(error){$('phone-pin-message').textContent=error.message;}
  finally{$('phone-pin-submit').disabled=false;}
};
$('connection-form').onsubmit=e=>{e.preventDefault();task(async()=>{lastConnectionDiagnostic='';token=$('token').value.trim()||token;if(!browserPaired&&!token){await pairLocalPc();return;}connected=false;sessionActive=false;setPowerControls(false);selected=null;resetGames();clearTelemetry('Connecting');$('connection-label').textContent='Connecting…';$('mode').textContent='CONNECTING';$('metric-status').textContent='Connecting';$('metric-type').textContent='—';$('metric-kernel').textContent='—';$('metric-drives').textContent='—';$('files').replaceChildren();let recoveryConfirmed=false;if(consoleRecoveryHold){recoveryConfirmed=window.confirm('Console operations are paused after a failed transfer. Confirm that the console is responsive, or has been restarted if frozen. Reconnect now?');if(!recoveryConfirmed)return;}const s=await api('connect',{target:$('target').value.trim(),recovery_confirmed:recoveryConfirmed});consoleRecoveryHold=false;if(typeof startBrowserSession==='function')startBrowserSession();status(s);$('connection-dialog').close();notice('Connected. Choose a discovered storage root to browse applications.'+(s.connection_toast==='accepted'?' Xbox toast command accepted.':''));log('Neighborhood connection established.');$('token').value='';if(typeof rememberConsole==='function')await rememberConsole($('target').value.trim());})};
$('drive').onchange=()=>{$('path').value=$('drive').value;task(browse)};
// Folders first; case-insensitive alphabetical names within each group.
const fileNameOrder=new Intl.Collator('en',{sensitivity:'base',numeric:false});
function sortedFiles(files){return [...files].sort((a,b)=>Number(Boolean(b.directory))-Number(Boolean(a.directory))||fileNameOrder.compare(a.name,b.name)||a.name.localeCompare(b.name,'en'));}
async function browse(){if(!connected)throw Error('Connect a console first.');const path=$('path').value;if(!path)throw Error('No storage root is selected. Open Reading details to check discovery.');const r=await api('browse',{path});$('files').replaceChildren();if(!r.files.length){const d=document.createElement('div');d.className='empty-state';d.textContent='This directory is empty.';$('files').append(d)}for(const f of sortedFiles(r.files)){const row=document.createElement('div');row.className='file-row';row.dataset.name=f.name;row.dataset.directory=String(Boolean(f.directory));const icon=document.createElement('span');icon.className='file-icon';icon.textContent=f.directory?'▱':'◇';const meta=document.createElement('div'),name=document.createElement('b'),sub=document.createElement('small');name.textContent=f.name;sub.textContent=f.directory?'Directory':Math.ceil((f.size||0)/1024).toLocaleString()+' KB';meta.append(name,sub);row.append(icon,meta);if(f.directory||/\.xex$/i.test(f.name)){const b=document.createElement('button');b.className='secondary';b.textContent=f.directory?'Open →':'Inspect XEX';b.onclick=()=>task(async()=>{const full=path.replace(/\\?$/,'\\')+f.name;if(f.directory){$('path').value=full+'\\';await browse()}else await inspect(full)});row.append(b)}if(typeof decorateFileRow==='function')decorateFileRow(row,f,path);$('files').append(row)}if(typeof browserTools==='function')browserTools('app',path);if(r.listing?.rejected||r.listing?.truncated)notice('Directory listing: '+r.files.length+' shown, '+r.listing.rejected+' rejected'+(r.listing.truncated?' (listing limit reached)':'')+'.');log('Console directory opened: '+r.files.length+' entries.');}
$('browse').onclick=()=>task(browse);$('up').onclick=()=>task(async()=>{const p=$('path').value.replace(/\\$/,'');const i=p.lastIndexOf('\\');if(i>=0){$('path').value=p.slice(0,i+1);await browse()}});
async function inspect(path,buildId=null){selected=null;$('launch').disabled=true;$('launch-path').textContent=path;$('validation').textContent='Reading and checking XEX…';if(!$('launch-dialog').open)$('launch-dialog').showModal();try{if(!buildId){$('expected-build').replaceChildren(Object.assign(document.createElement('option'),{value:'',textContent:'Identify by hash (no expected build)'}));{const catalog=await api('registry/list');for(const b of catalog.builds){const o=document.createElement('option');o.value=b.id;o.textContent=b.project+' / '+b.version+' / '+b.filename+' ['+b.state+']';$('expected-build').append(o)}}}const v=await api('validate',{path,build_id:buildId});selected={...v,path};$('validation').replaceChildren();for(const text of [...v.checks,'SHA-256: '+v.hash,v.plugin?'Plugin module: runtime loader required.':'Application candidate. Structural checks passed.']){const d=document.createElement('div');d.className='validation-row mono';d.textContent=text;$('validation').append(d)}{const report=v.verification||{status:'unknown'},row=document.createElement('div');row.className='validation-row mono';row.textContent='Build registry: '+report.status+(report.discrepancies?.length?' — '+report.discrepancies.join(' '):'')+(report.status==='unknown'?' — No reviewed reference. This file has only passed structural checks.':'');$('validation').append(row);if(report.expected){const expected=document.createElement('div');expected.className='validation-row mono';expected.textContent='Expected: '+report.expected.sha256+' / '+report.expected.size+' bytes. Actual: '+v.hash+' / '+v.size+' bytes.';$('validation').append(expected)}for(const match of report.matches||[]){const detail=document.createElement('div');detail.className='validation-row mono';detail.textContent=match.project+' / '+match.version+' / '+match.state+' / '+match.repository+' @ '+match.commit;$('validation').append(detail)}}
if(v.game_verification){const badge=gameBadge(v.game_verification);$('validation').append(badge);}
if(v.launch_block_reason){const reason=document.createElement('p');reason.textContent=v.launch_block_reason;$('validation').append(reason);}$('launch').disabled=!v.valid||v.plugin||(!v.ticket);$('launch').textContent='Launch application →';log('XEX structural inspection completed.')}catch(e){$('validation').textContent=e.message;throw e}}
$('launch').onclick=()=>task(async()=>{if(!selected||!selected.valid||selected.plugin)return;$('launch').disabled=true;{const result=await api('launch',{ticket:selected.ticket});if(result?.accepted!==true)throw Error('The console did not confirm the launch command.');preserveObservedTitle=true;clearTelemetry('Launching');connected=false;setPowerControls(false);}$('launch-dialog').close();notice('Launch command accepted. The console may disconnect while the title starts.');showToast('Game or app launch accepted. Waiting for console confirmation.');log('Launch command accepted.');if(typeof trackLaunchAccepted==='function')trackLaunchAccepted();selected=null});
const powerLabels={warm:'warm reboot',cold:'cold reboot',shutdown:'shutdown'};
async function captureConsoleScreen(){
  if(!connected)throw Error('Connect a console first.');
  const state=$('console-screen-status'),epoch=authEpoch;
  state.textContent='Capturing one Xbox frame…';
  try{
    const result=await api('console/screenshot');
    if(epoch!==authEpoch||!connected)return;
    if(typeof result.png!=='string'||result.png.length>12000000||result.png.length<100||
       !Number.isInteger(result.width)||!Number.isInteger(result.height))throw Error('Screen capture was incomplete.');
    const image=$('console-screen-image');
    image.src='data:image/png;base64,'+result.png;
    image.hidden=false;
    state.textContent='Captured '+result.width+' × '+result.height+' at '+new Date().toLocaleTimeString()+'.';
  }catch(error){state.textContent=error.message;throw error;}
}
$('console-screen-capture').onclick=()=>task(captureConsoleScreen);
async function checkRpcTools(){
  if(!connected)throw Error('Connect a console first.');
  const output=$('rpc-tools-result');output.textContent='Checking loaded RPC tools…';
  try{
    const inventory=await api('plugins/list');
    const seen=new Set((inventory.console?.items||[]).map(item=>String(item.name||'').split(/[\\/]/).pop().toLowerCase()));
    const observed=inventory.console?.state==='observed';
    output.textContent=[['JRPC','jrpc.xex'],['JRPC2','jrpc2.xex'],['RPC','rpc.xex'],['XRPC','xrpc.xex']]
      .map(([label,file])=>label+': '+(seen.has(file)?'loaded (handler unverified)':observed?'not detected':'inventory unavailable'))
      .join('\n');
  }catch(error){output.textContent='RPC inventory unavailable. '+error.message;throw error;}
}
$('rpc-tools-check').onclick=()=>task(checkRpcTools);
$('console-notify-refresh').onclick=()=>task(async()=>{
  await refreshConsoleControls();
  if(!consoleNotifyAvailable){$('footer-notify-status').textContent='JRPC2 is not ready; no Xbox notification was sent.';return;}
  $('footer-notify-status').textContent='Sending Xbox toast…';
  try{
    const result=await api('console/notify',{message:'You are awesome!',confirmed:true});
    if(result.accepted!==true)throw Error('Xbox notification command was not confirmed.');
    $('footer-notify-status').textContent='Toast command accepted. Check the Xbox screen.';
    showToast('Xbox toast command accepted. Check the console.');
  }catch(error){$('footer-notify-status').textContent=error.message;throw error;}
  $('console-screen-panel').open=true;
  try{await captureConsoleScreen();$('footer-notify-status').textContent='Toast accepted; screen captured in Console.';}
  catch{$('footer-notify-status').textContent='Toast accepted; screen capture unavailable. Open Console to retry.';}
});
$('console-storage-compare').onclick=()=>task(async()=>{if(!connected)throw Error('Connect a console first.');const output=$('console-storage-result');output.textContent='Checking both storage lists…';const result=await api('console/storage-compare');if(result.state!=='compared'){output.textContent='Direct XBDM did not answer. Neighborhood storage remains available when connected.';return;}const names=roots=>roots.length?roots.join(', '):'none';output.textContent='Neighborhood available: '+names(result.neighborhood)+'. Direct XBDM reported: '+names(result.xbdm)+'. '+(result.only_neighborhood.length||result.only_xbdm.length?'Lists differ (a root may be inaccessible) — Neighborhood only: '+names(result.only_neighborhood)+'; XBDM only: '+names(result.only_xbdm)+'.':'Both lists match.');});
$('console-notify-form').onsubmit=event=>{event.preventDefault();task(async()=>{if(!connected)throw Error('Connect a console first.');if(!consoleNotifyAvailable)throw Error('JRPC2 notification support is unavailable. Refresh the capability check.');const message=$('console-notify-message').value;if(!/^[ -~]{1,80}$/.test(message))throw Error('Use 1–80 printable ASCII characters.');$('console-notify-result').textContent='Sending to Xbox…';try{const result=await api('console/notify',{message,confirmed:true});if(result.accepted!==true)throw Error('Xbox notification command was not confirmed.');$('console-notify-result').textContent='Command accepted. Check the Xbox screen.';showToast('Xbox notification command accepted. Check the console.');}catch(error){$('console-notify-result').textContent=error.message;throw error;}})};
let pendingPowerMode=null;
for(const button of document.querySelectorAll('[data-console-power]'))button.onclick=()=>{
  const mode=button.dataset.consolePower;
  if(!connected){notice('Connect a console first.');return;}
  if(!Object.hasOwn(powerLabels,mode)){notice('Unsupported power action.');return;}
  pendingPowerMode=mode;
  $('console-power-message').textContent=button.id==='return-to-dash'?'Warm reboot to the configured dashboard? This interrupts the current game and transfers. DashLaunch may open a different dashboard.':'Send '+powerLabels[mode]+' to the connected console? This interrupts the current game and transfers.';
  $('console-power-dialog').showModal();
};
$('console-power-cancel').onclick=()=>{$('console-power-dialog').close();pendingPowerMode=null;};
$('console-power-dialog').addEventListener('close',()=>{pendingPowerMode=null;});
$('console-power-confirm').onclick=()=>{
  const mode=pendingPowerMode;if(!mode)return;
  $('console-power-dialog').close();
  task(async()=>{
  if(!connected)throw Error('Connect a console first.');
  const result=await api('console/power',{mode,confirmed:true});
  if(result.accepted!==true)throw Error('Console did not confirm the power command.');
  connected=false;sessionActive=false;setPowerControls(false);clearTelemetry('Reconnect required');
  $('connection-label').textContent='Reconnect required';$('console-name').textContent='Reconnect required';
  $('console-note').textContent='Console command accepted. Reconnect after it finishes.';
  $('mode').textContent='OFFLINE';$('metric-status').textContent='Offline';
  $('metric-type').textContent='—';$('metric-kernel').textContent='—';$('metric-drives').textContent='—';
  $('browse').disabled=true;$('game-browse').disabled=true;$('footer-mode').textContent='Reconnect required';
  notice('Console '+powerLabels[mode]+' command accepted. Reconnect after it finishes.');
  log('Console '+powerLabels[mode]+' command accepted.');
  });
};
$('refresh').onclick=()=>task(async()=>{if(!sessionActive)throw Error('Connect your console first.');await refreshStatus();notice('Console status refreshed.');});$('clear').onclick=()=>{$('events').replaceChildren();log('Activity cleared.');};

// CPU keys are only read following fresh explicit consent. Never log the response.
let privateTicket=null,privateGeneration=0,privateTimer=null;
function clearCpuKey(){privateGeneration++;privateTicket=null;clearTimeout(privateTimer);$('cpu-key-value').textContent='';$('cpu-key-result').hidden=true;$('cpu-key-consent').hidden=false;$('cpu-key-confirm').disabled=false;$('cpu-key-message').textContent='';$('cpu-key-cancel').textContent='Cancel';}
function hideCpuKey(){clearCpuKey();if($('cpu-key-dialog').open)$('cpu-key-dialog').close();}
$('cpu-key-dialog').addEventListener('close',clearCpuKey);
$('cpu-key-cancel').onclick=hideCpuKey;
document.addEventListener('visibilitychange',()=>{if(document.hidden)hideCpuKey()});
window.addEventListener('pagehide',hideCpuKey);
$('cpu-key-open').onclick=()=>task(async()=>{
  if(!connected)throw Error('Connect a real console before requesting private information.');
  clearCpuKey();const generation=privateGeneration;
  const consent=await api('cpu-key/prepare'); // No private console read.
  if(generation!==privateGeneration||document.hidden)return;
  privateTicket=consent.confirmation_ticket;$('cpu-key-dialog').showModal();
  privateTimer=setTimeout(()=>{privateTicket=null;$('cpu-key-confirm').disabled=true;$('cpu-key-message').textContent='Confirmation expired. Close and request again.';},60000);
});
$('cpu-key-confirm').onclick=async()=>{
  if(busy||!privateTicket||!connected)return;
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
async function showRepositories(){const data=await api('repos/list');$('repo-results').replaceChildren();for(const entry of data.repositories)renderRepository($('repo-results'),entry,entry.last_check);return data.repositories}
$('repo-pair').onclick=()=>task(async()=>{token=$('repo-token').value.trim();$('repo-token').value='';await showRepositories()});
$('repo-refresh').onclick=()=>task(showRepositories);
$('repo-save').onsubmit=e=>{e.preventDefault();task(async()=>{await api('repos/save',{repository:$('repo-name').value});$('repo-name').value='';await showRepositories()})};
$('check-updates').onclick=()=>task(async()=>{const entries=await showRepositories();$('repo-results').replaceChildren();for(const entry of entries){notice('Checking '+entry.repository+'…');let result;try{result=await api('repos/check',{repository:entry.repository})}catch{result={status:'unavailable',error:'Bridge request failed.',last_success:entry.last_check}}renderRepository($('repo-results'),entry,result)}notice('Repository checks finished. Review individual results for unavailable data.');});
async function showInventory(){
  if(!connected){$('plugin-inventory').textContent='Reconnect, then refresh the module inventory.';return;}
  const generation=gameLibraryGeneration;
  const expanded=[...$('plugin-inventory').children].map(group=>Boolean(group.open));
  $('plugin-inventory').textContent='Reading module inventory...';
  let data;
  try{data=await api('plugins/list');}
  catch(error){$('plugin-inventory').textContent='Inventory unavailable. '+error.message;throw error;}
  if(generation!==gameLibraryGeneration||!connected)return;
  $('plugin-inventory').replaceChildren();
  const consoleState=data.console?.state||'unavailable';
  const consoleSource=data.console?.source==='xbdm'?'XBDM':data.console?.source==='xdevkit'?'Neighborhood':'Unavailable';
  const groups=[
    {label:'Console modules',items:data.console?.items||[],note:'Live '+consoleSource+' names · '+consoleState+'. File paths unavailable.',empty:consoleState==='unavailable'?'Console module scan unavailable. Check the connection and retry.':consoleState==='disconnected'?'Connect a console to read loaded modules.':consoleState==='partial'?'No usable module names. Refresh the inventory.':'No modules reported.'},
    {label:'Bridge components',items:data.backend||[],note:'Running on this PC.',empty:'No bridge components reported.'},
    {label:'Registrations',items:data.user||[],note:'Saved metadata, not loaded modules.',empty:'No plugin registrations saved.'},
  ];
  for(const [index,groupData] of groups.entries()){
    const group=document.createElement('details'),header=document.createElement('summary'),heading=document.createElement('span'),count=document.createElement('span'),note=document.createElement('p'),list=document.createElement('div');
    group.className='inventory-group';group.open=expanded[index]||false;header.className='inventory-group-heading';heading.textContent=groupData.label;count.className='tag muted';count.textContent=String(groupData.items.length);header.append(heading,count);
    note.className='small';note.textContent=groupData.note;list.className='inventory-items';group.append(header,note,list);
    if(!groupData.items.length){const empty=document.createElement('p');empty.className='small';empty.textContent=groupData.empty;list.append(empty);}
    for(const item of groupData.items){
      const row=document.createElement('article'),main=document.createElement('div'),name=document.createElement('strong'),actions=document.createElement('div');
      row.className='inventory-row'+(groupData.label==='Console modules'&&/\.xex$/i.test(item.name)?' inventory-row-loaded-xex':'');main.className='inventory-row-main';name.textContent=groupData.label==='Console modules'&&/^NebulahCompanion-[A-Za-z0-9_]+\.xex$/i.test(item.name)?'NebulahCompanion.xex':item.name;
      main.append(name);actions.className='inventory-row-actions';
      if(groupData.label==='Console modules'&&item.unload_uncertain){const warning=document.createElement('small');warning.textContent='Unload attempted; module still listed. Do not repeat normal unload.';main.append(warning);}
      if(groupData.label==='Registrations'&&item.version){const version=document.createElement('small');version.textContent=item.version;main.append(version);}
      if(groupData.label==='Console modules'&&item.unload_ready)actions.append(button('Unload module',()=>unloadModule(item.name)));
      if(item.state==='registered-not-loaded')actions.append(button('Remove registration',async()=>{await api('plugins/remove',{name:item.name});await showInventory();}));
      row.append(main);if(actions.children.length)row.append(actions);
      if(groupData.label==='Registrations'&&item.repository){const repository=document.createElement('small');repository.className='inventory-repository';repository.textContent=item.repository;row.append(repository);}
      list.append(row);
    }
    if(groupData.label==='Console modules'&&data.console&&Number.isInteger(data.console.received)&&(data.console.rejected||data.console.truncated)){
      const counts=document.createElement('p');counts.className='small';counts.textContent=data.console.received+' returned · '+data.console.rejected+' rejected'+(data.console.truncated?' · listing limit reached':'');group.append(counts);
    }
    $('plugin-inventory').append(group);
  }
}

async function unloadModule(name){
  if(!connected)throw Error('Connect a console first.');
  try{const result=await api('plugins/unload',{name,confirmed:true,route:'component'});notice(result.name+' unloaded.');}
  catch(error){try{await showInventory();}catch{}throw error;}
  await showInventory();
  if(name.toLowerCase()==='xbox360stream.xex'&&typeof refreshStream360==='function')await refreshStream360();
}

$('inventory-refresh').onclick=()=>task(showInventory);
$('plugin-register').onsubmit=e=>{e.preventDefault();task(async()=>{await api('plugins/register',{name:$('plugin-name').value,version:$('plugin-version').value,repository:$('plugin-repo').value});await showInventory()})};

function resetGames(){if(typeof resetCompanion==='function')resetCompanion();if($('game-preview-dialog').open)$('game-preview-dialog').close(); $('game-shortcuts').replaceChildren();$('game-files').replaceChildren();$('game-drive').replaceChildren();$('game-folder').value='';$('game-executable').value='';$('game-mode').value='';$('game-name').value=''; }
function gameLibraryRoots(drives){
  const withoutMirrors=drives.length>1?drives.filter(root=>!/^(?:game|nfinite(?:data)?|xbguard(?:data)?|tethered(?:data)?|teathered(?:data)?):\\$/i.test(root)):drives;
  return withoutMirrors.some(root=>/^usb\d+:\\$/i.test(root))?withoutMirrors.filter(root=>!/^usb:\\$/i.test(root)):withoutMirrors;
}
function gameLibraryPathVisible(path){const drives=Array.from($('game-drive').options).map(option=>option.value),visible=gameLibraryRoots(drives);return !drives.some(root=>path.toLowerCase().startsWith(root.toLowerCase())&&!visible.includes(root));}
function syncGameDrives(drives){
  const currentDrives=Array.from($('game-drive').options).map(option=>option.value);
  if(currentDrives.length===drives.length&&currentDrives.every((root,index)=>root===drives[index]))return;
  const previous=$('game-drive').value,selected=$('games-scan-location').value,scanSelected=$('plugin-scan-location').value,libraryRoots=gameLibraryRoots(drives);
  const allOption=()=>Object.assign(document.createElement('option'),{value:'all',textContent:'All discovered storage'});
  $('game-drive').replaceChildren();$('games-scan-location').replaceChildren(allOption());$('plugin-scan-location').replaceChildren(allOption());
  for(const root of drives){$('game-drive').append(Object.assign(document.createElement('option'),{value:root,textContent:root}));if(libraryRoots.includes(root))for(const id of ['games-scan-location','plugin-scan-location'])$(id).append(Object.assign(document.createElement('option'),{value:root,textContent:root}));}
  $('games-scan-location').value=libraryRoots.find(root=>root.toLowerCase()===selected.toLowerCase())||'all';
  $('plugin-scan-location').value=libraryRoots.find(root=>root.toLowerCase()===scanSelected.toLowerCase())||'all';
  $('game-drive').value=drives.find(root=>root.toLowerCase()===previous.toLowerCase())||(drives[0]||'');
  if(!drives.some(root=>root.toLowerCase()===previous.toLowerCase())){$('game-folder').value=$('game-drive').value;$('game-files').replaceChildren();$('game-executable').value='';$('game-mode').value='';}
  if(typeof gameLibraryList!=='undefined'&&gameLibraryList)renderGameLibrary(gameLibraryFiles);
}
$('games-scan-location').onchange=()=>{
  const root=$('games-scan-location').value;
  if(root!=='all'){$('game-drive').value=root;$('game-folder').value=root;$('game-files').replaceChildren();$('game-executable').value='';$('game-mode').value='';}
  gameLibraryShown=100;renderGameLibrary(gameLibraryFiles);
  if(gameLibraryOtherResult)gameLibraryOtherResult.replaceChildren();
  if(typeof requestLibraryStorageSelection==='function')requestLibraryStorageSelection(root);
};
function requireGameConnection(){if(!connected)throw Error('Connect a console before using game paths.');}
function renderShortcutCover(container,source,name){container.replaceChildren();container.textContent='XBOX 360';if(source){container.textContent='';const img=document.createElement('img');img.loading='lazy';img.decoding='async';img.src=source;img.alt=name+' cover';img.onerror=()=>{container.replaceChildren();container.textContent='Artwork unavailable';};container.append(img);}}
async function loadGames(){requireGameConnection();const generation=gameLibraryGeneration;const entries=(await api('games/list')).shortcuts;if(generation!==gameLibraryGeneration||!connected)return;$('game-shortcuts').replaceChildren();if(!entries.length){const empty=document.createElement('p');empty.className='empty-state';empty.textContent='No shortcuts for this console connection. Browse a folder below to add one.';$('game-shortcuts').append(empty);}for(const entry of entries){const card=document.createElement('article');card.className='game-card';card.dataset.shortcutId=entry.id;const title=document.createElement('h3'),path=document.createElement('p'),actions=document.createElement('div');title.textContent=entry.name+(entry.mode?' · '+gameModeLabel(entry.mode):'');path.className='mono';path.textContent=entry.folder+entry.executable;actions.className='game-actions';const button=(label,fn)=>{const b=document.createElement('button');b.className='secondary';b.textContent=label;b.onclick=()=>task(fn);actions.append(b);};button('Open folder',async()=>{requireGameConnection();$('game-folder').value=entry.folder;$('game-executable').value='';$('game-mode').value='';await browseGames();});if(entry.executable)button('Validate & launch',async()=>{requireGameConnection();await inspect(entry.folder+entry.executable);});button('Edit shortcut',async()=>{$('games-path-tools').open=true;$('game-folder').value=entry.folder;$('game-executable').value=entry.executable;$('game-name').value=entry.name;$('game-mode').value=entry.mode||'';$('game-name').focus();});button('Remove shortcut',async()=>{requireGameConnection();await api('games/remove',{id:entry.id});await loadGames();});const cover=document.createElement('div');cover.className='game-cover mini';renderShortcutCover(cover,entry.cover,entry.name);if(entry.executable){const getCover=document.createElement('button');getCover.className='secondary cover-action';getCover.textContent=entry.cover?'Refresh cover art':'Get cover art';getCover.onclick=()=>task(async()=>{notice('Reading Title ID and fetching cover art…');const result=await api('games/cover',{id:entry.id});await loadGames();notice(result.cover?'Cover art saved locally.':'Title found, but cover art is unavailable.');});cover.append(getCover);}const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Shortcut options';details.append(summary,path,actions);const preview=document.createElement('button');preview.className='secondary';preview.textContent='Game preview';preview.onclick=()=>task(async()=>{requireGameConnection();await previewGame(entry);});card.append(cover,title,preview,details);$('game-shortcuts').append(card);}}
async function browseGames(){requireGameConnection();$('games-path-tools').open=true;if(!$('game-folder').value)throw Error('No storage root is selected. Open Reading details to check discovery.');const folder=$('game-folder').value.replace(/\\?$/,'\\');const files=(await api('browse',{path:folder})).files;$('game-folder').value=folder;$('game-files').replaceChildren();$('game-executable').value='';$('game-mode').value='';if(!files.some(f=>f.directory||/\.xex$/i.test(f.name)))$('game-files').textContent=files.length?'This folder contains files, but no subfolders or XEX launch files.':'This folder is empty.';for(const f of sortedFiles(files)){if(!f.directory&&!/\.xex$/i.test(f.name))continue;const row=document.createElement('div');row.className='file-row';row.dataset.name=f.name;row.dataset.directory=String(Boolean(f.directory));const label=document.createElement('b'),action=document.createElement('button');label.textContent=f.name;action.className='secondary';action.textContent=f.directory?'Open folder →':'Use launch file';action.onclick=()=>task(async()=>{if(f.directory){$('game-folder').value=folder+f.name+'\\';await browseGames();}else{$('game-folder').value=folder;$('game-executable').value=f.name;$('game-mode').value='';if(!$('game-name').value)$('game-name').value=folder.split('\\').filter(Boolean).pop();$('game-name').focus();}});row.append(label,action);$('game-files').append(row);}if(typeof browserTools==='function')browserTools('game',folder);}
$('game-browse').onclick=()=>task(browseGames);
$('games-refresh').onclick=()=>task(loadGames);
$('games-open-scan').onclick=()=>{openWorkspaceView('plugins');$('plugin-scan-panel').open=true;};
$('game-drive').onchange=()=>task(async()=>{$('game-folder').value=$('game-drive').value;await browseGames();});
$('game-folder').oninput=()=>{$('game-files').replaceChildren();$('game-executable').value='';$('game-mode').value='';};
$('game-up').onclick=()=>task(async()=>{const folder=$('game-folder').value.replace(/\\$/,'');const i=folder.lastIndexOf('\\');if(i>=0){$('game-folder').value=folder.slice(0,i+1);await browseGames();}});
function gameModeLabel(mode){return ({campaign:'Campaign',multiplayer:'Multiplayer',zombies:'Zombies',other:'Other'})[mode]||'Unspecified';}
let gameLibraryList=null,gameLibrarySummary=null,gameLibraryFiles=[],gameLibraryGroups=[],gameLibraryCovers={},gameLibraryGeneration=0;
let gameLibraryQuery='',gameLibrarySort='name',gameLibraryView='covers',gameLibraryFilter='all',gameLibraryCategory='all',gameLibraryChips=null,gameLibraryShown=100,gameLibraryOtherResult=null,gameLibrarySearch=null;
const gameCategoryLabels={all:'All',favorites:'Favorites',recent:'Recent launches',games:'Games',homebrew:'Homebrew',emulators:'Emulators',apps:'Apps',uncategorized:'Uncategorized',plugins:'Plugins',stealth:'Stealth Server'};
function libraryModule(group){return ['plugin','stealth'].includes(group.kind)||group.copies.some(item=>item.inspection?.plugin)||['plugins','stealth'].some(category=>group.categories?.includes(category));}
function gameCategoryMatches(group,category){
  const plugin=libraryModule(group),stealth=group.kind==='stealth'||group.categories?.includes('stealth');
  if(category==='all')return true;
  if(category==='plugins')return plugin&&!stealth;
  if(category==='stealth')return stealth;
  if(category==='favorites')return group.favorite||group.copies.some(item=>item.label?.favorite);
  if(category==='recent')return group.copies.some(item=>item.last_launch);
  return !plugin&&(Array.isArray(group.categories)?group.categories.includes(category):group.copies.some(item=>(item.label?.category||'uncategorized')===category));
}
function libraryDisplayName(path){const parts=path.split('\\'),filename=parts.pop();return /\.xex$/i.test(filename)&&parts.length>1?parts.pop():filename.replace(/\.(xex|iso)$/i,'');}
let libraryOrganization=null;
function openLibraryOrganizer(copies,name){
  libraryOrganization={copies,generation:gameLibraryGeneration};
  const select=$('library-organize-path');select.replaceChildren();
  for(const item of copies)select.append(Object.assign(document.createElement('option'),{value:item.path,textContent:item.path}));
  select.value=copies[0].path;$('library-organize-title').textContent='Organize '+name;fillLibraryOrganizer();$('library-organize-dialog').showModal();
}
function fillLibraryOrganizer(){
  const item=libraryOrganization?.copies.find(item=>item.path===$('library-organize-path').value);if(!item)return;
  const group=gameLibraryGroups.find(group=>(group.paths||[]).includes(item.path));
  const label=item.label||{};$('library-organize-name').value=label.name||'';$('library-organize-category').value=label.category||'uncategorized';$('library-organize-mode').value=label.mode||'';$('library-organize-mode').disabled=!/\.xex$/i.test(item.path)||Boolean(item.inspection?.plugin)||Boolean(group&&libraryModule({...group,copies:[item]}));$('library-organize-favorite').checked=label.favorite===true;
}
$('library-organize-path').onchange=fillLibraryOrganizer;
$('library-organize-dialog').addEventListener('close',()=>{libraryOrganization=null;});
$('library-organize-form').onsubmit=event=>{event.preventDefault();task(async()=>{
  requireGameConnection();const generation=libraryOrganization?.generation;
  if(generation!==gameLibraryGeneration)throw Error('Library changed. Choose this file again.');
  const selected=gameLibraryGroups.some(item=>(item.paths||[]).includes($('library-organize-path').value));
  if(!selected&&!$('library-organize-name').value.trim()&&$('library-organize-category').value==='uncategorized'&&!$('library-organize-mode').value&&!$('library-organize-favorite').checked)throw Error('Give this launch entry a name, category, mode or favorite to include it.');
  await api('library/label',{path:$('library-organize-path').value,name:$('library-organize-name').value,category:$('library-organize-category').value,mode:$('library-organize-mode').disabled?'':$('library-organize-mode').value,favorite:$('library-organize-favorite').checked});
  if(generation!==gameLibraryGeneration||!connected)return;
  $('library-organize-dialog').close();await loadGameLibrary();notice('Name, category and favorite saved for this console.');
});};
function ensureGameLibrary(){
  if(gameLibraryList)return gameLibraryList;
  const host=$('game-library-host');
  const panel=document.createElement('div');panel.className='panel';
  const heading=document.createElement('div');heading.className='section-heading';
  const title=document.createElement('h2');title.textContent='Your library';
  const refresh=document.createElement('button');refresh.className='secondary';refresh.type='button';refresh.textContent='Refresh library';refresh.onclick=()=>task(loadGameLibrary);
  const actions=document.createElement('div');actions.className='games-library-actions';
  actions.append(refresh,$('games-identify'),$('games-prune'));
  heading.append(title,actions);
  const help=document.createElement('p');help.className='small';
  gameLibraryList=document.createElement('div');gameLibraryList.id='game-library';gameLibraryList.className='game-grid';
  const controls=document.createElement('div');controls.className='browser-controls';
  const search=document.createElement('input');gameLibrarySearch=search;search.type='search';search.placeholder='Search title, ID or location';search.setAttribute('aria-label','Search discovered games');search.oninput=()=>{gameLibraryQuery=search.value;gameLibraryShown=100;renderGameLibrary(gameLibraryFiles);};
  const filter=document.createElement('select');filter.setAttribute('aria-label','Filter library');
  for(const [value,label] of [['all','All formats'],['copies','Multiple launch entries'],['xex','XEX'],['iso','ISO candidates'],['god','GOD layout candidates'],['uninspected','Not inspected']])filter.append(Object.assign(document.createElement('option'),{value,textContent:label}));
  filter.onchange=()=>{gameLibraryFilter=filter.value;gameLibraryShown=100;renderGameLibrary(gameLibraryFiles);};
  const sort=document.createElement('select');sort.setAttribute('aria-label','Sort discovered games');
  for(const [value,label] of [['name','Name'],['size','Largest file'],['newest','Recently scanned']])sort.append(Object.assign(document.createElement('option'),{value,textContent:label}));
  sort.onchange=()=>{gameLibrarySort=sort.value;gameLibraryShown=100;renderGameLibrary(gameLibraryFiles);};
  controls.append(search,filter,sort);
  for(const mode of ['list','covers']){const button=document.createElement('button');button.className='secondary library-view-button';button.dataset.libraryView=mode;button.textContent=mode==='list'?'List':'Covers';button.setAttribute('aria-pressed',String(mode===gameLibraryView));button.onclick=()=>{gameLibraryView=mode;for(const other of controls.querySelectorAll('.library-view-button'))other.setAttribute('aria-pressed',String(other===button));renderGameLibrary(gameLibraryFiles);};controls.append(button);}
  help.textContent='Game folders plus recognized apps/services anywhere on discovered storage. Selecting a device scans its library. Duplicate known XEX names prefer HDD. Game copies collapse after identification when their launcher SHA-256 matches. Exact filenames and hashes stay in entry details. Launching checks the current file; names never establish trust.';
  gameLibraryChips=document.createElement('div');gameLibraryChips.className='library-chips';gameLibraryChips.setAttribute('aria-label','Library categories');
  gameLibrarySummary=document.createElement('p');gameLibrarySummary.className='small';gameLibrarySummary.setAttribute('aria-live','polite');
  const other=document.createElement('details');other.className='library-other-files';
  const otherSummary=document.createElement('summary');otherSummary.textContent='Choose another launch file';
  const otherHelp=document.createElement('p');otherHelp.className='small';otherHelp.textContent='For a nonstandard app or alternate mode, choose a saved XEX and give it a name, category or mode. Only selected entries appear on its install card. Confirmed plugins use Plugins.';
  const showOther=document.createElement('button');showOther.className='secondary';showOther.textContent='Show saved XEX files';
  const otherResult=document.createElement('div');otherResult.className='browser-controls';gameLibraryOtherResult=otherResult;
  showOther.onclick=()=>task(async()=>{
    requireGameConnection();const generation=gameLibraryGeneration,root=$('games-scan-location').value||'all';otherResult.replaceChildren();
    const inventory=await api('library/list',root==='all'?{}:{root});if(generation!==gameLibraryGeneration||!connected||root.toLowerCase()!==($('games-scan-location').value||'all').toLowerCase())return;
    const selected=new Set(gameLibraryGroups.flatMap(item=>item.paths||[]).map(path=>path.toLowerCase()));
    const candidates=(inventory.files||[]).filter(item=>/^[^\\]+\\(Games|Plugins|Homebrew|Apps|Emulators)\\.+\.xex$/i.test(item.path)&&!item.inspection?.plugin&&!selected.has(item.path.toLowerCase()));
    if(!candidates.length){const empty=document.createElement('p');empty.textContent='No additional saved title XEX files. Use the folder browser to inspect a custom launcher.';otherResult.append(empty);return;}
    const select=document.createElement('select');select.setAttribute('aria-label','Choose an additional launch file');
    for(const item of candidates)select.append(Object.assign(document.createElement('option'),{value:item.path,textContent:item.path}));select.value=candidates[0].path;
    const choose=document.createElement('button');choose.className='secondary';choose.textContent='Organize selected entry';
    choose.onclick=()=>task(async()=>{requireGameConnection();if(generation!==gameLibraryGeneration)throw Error('Library changed. Refresh saved files.');const item=candidates.find(item=>item.path===select.value);if(item)openLibraryOrganizer([item],libraryDisplayName(item.path));});
    otherResult.append(select,choose);
  });
  other.append(otherSummary,otherHelp,showOther,otherResult);
  panel.append(heading,help,controls,gameLibraryChips,gameLibrarySummary,gameLibraryList,other);host.append(panel);return gameLibraryList;
}
function renderGameLibrary(files,groups=null){
  const list=ensureGameLibrary();list.replaceChildren();
  gameLibraryFiles=Array.isArray(files)?files.filter(item=>item&&typeof item.path==='string'):[];
  if(groups!==null)gameLibraryGroups=Array.isArray(groups)?groups:[];
  list.className=gameLibraryView==='list'?'game-library-list':'game-grid';
  const byPath=new Map(gameLibraryFiles.map(item=>[item.path.toLowerCase(),item]));
  // The server's physical catalogue is authoritative, including an empty collection.
  const source=gameLibraryGroups;
  const root=$('games-scan-location').value;
  const collection=source.map(group=>({...group,copies:(group.paths||[]).map(path=>byPath.get(path.toLowerCase())).filter(item=>item&&gameLibraryPathVisible(item.path)&&(!root||root==='all'||item.path.toLowerCase().startsWith(root.toLowerCase())))})).filter(group=>group.copies.length);
  gameLibraryChips.replaceChildren();
  for(const [category,label] of Object.entries(gameCategoryLabels)){
    const count=collection.filter(group=>gameCategoryMatches(group,category)).length;
    const chip=document.createElement('button');chip.type='button';chip.className='secondary library-chip';chip.textContent=label+' · '+count;chip.setAttribute('aria-pressed',String(category===gameLibraryCategory));chip.onclick=()=>{gameLibraryCategory=category;gameLibraryShown=100;renderGameLibrary(gameLibraryFiles);};gameLibraryChips.append(chip);
  }
  const query=gameLibraryQuery.toLowerCase();
  const games=collection.filter(group=>{
    if(!group.copies.length)return false;
    if(!gameCategoryMatches(group,gameLibraryCategory))return false;
    if(gameLibraryFilter==='copies'&&group.copies.length<2)return false;
    if(['xex','iso','god'].includes(gameLibraryFilter)&&group.format!==gameLibraryFilter)return false;
    if(gameLibraryFilter==='uninspected'&&group.copies.some(item=>item.inspection))return false;
    return [group.name,group.title_id,...group.copies.flatMap(item=>[item.path,item.label?.name,item.label?.mode])].join(' ').toLowerCase().includes(query);
  });
  const largest=group=>Math.max(0,...group.copies.map(item=>item.size||0)),newest=group=>Math.max(0,...group.copies.map(item=>item.scanned||0));
  games.sort((a,b)=>gameLibrarySort==='size'?largest(b)-largest(a):gameLibrarySort==='newest'?newest(b)-newest(a):(a.name||'').localeCompare(b.name||''));
  gameLibrarySummary.textContent=games.length+' installs · '+games.reduce((count,group)=>count+group.copies.length,0)+' entries shown'+(games.length>gameLibraryShown?' · first '+gameLibraryShown+' installs displayed':'');
  if(!games.length){const empty=document.createElement('p');empty.className='empty-state';empty.textContent=collection.length?'No titles match these filters. Choose All or clear your search.':'Your library is empty. Use Scan for games above; no folder hunting needed.';list.append(empty);return;}
  const generation=gameLibraryGeneration;
  const requireCurrentLibrary=()=>{requireGameConnection();if(generation!==gameLibraryGeneration)throw Error('Library changed. Refresh and choose this file again.');};
  for(const group of games.slice(0,gameLibraryShown)){
    const card=document.createElement('article');card.className='game-card library-group';card.dataset.groupId=group.id||group.copies[0].path;
    const displayTitle=group.name+(group.location_hint?' · '+group.location_hint:'');
    const cover=document.createElement('div');cover.className='game-cover mini';renderShortcutCover(cover,gameLibraryCovers[group.cover_title_id]||null,group.name);
    if(!gameLibraryCovers[group.cover_title_id]){cover.textContent=group.name;cover.className+=' no-artwork';}
    const name=document.createElement('h3');name.textContent=displayTitle||group.copies[0].path;
    const badge=document.createElement('span');badge.className='game-badge unknown';
    const module=libraryModule(group);
    badge.textContent=module?(group.plugin_confirmed||group.copies.some(item=>item.inspection?.plugin)?'DLL/plugin inspected · launch blocked':'Module name hint · launch blocked'):group.format==='iso'?'ISO candidate — not verified':group.format==='god'?'GOD layout candidate — not verified':group.copies.some(item=>item.inspection)?'Saved inspection':'Inspect on launch';
    const copies=document.createElement('details');copies.className='library-copies';copies.open=false;
    const summary=document.createElement('summary');summary.textContent=group.copies.length+' '+(group.copies.length===1?'entry':'launch entries');copies.append(summary);
    for(const item of group.copies){
      const row=document.createElement('div');row.className='library-copy';row.dataset.gamePath=item.path;
      const path=document.createElement('p');path.className='mono';path.textContent=item.path;
      const meta=document.createElement('p');meta.className='small';meta.textContent=(Number.isSafeInteger(item.size)?bytesLabel(item.size):'Size unavailable')+' · scanned '+(item.scanned?new Date(item.scanned*1000).toLocaleString():'unknown');
      if(item.label)meta.textContent+=(item.label.name?' · '+item.label.name:'')+' · '+(gameCategoryLabels[item.label.category]||'Uncategorized')+(item.label.mode?' · '+gameModeLabel(item.label.mode):'');
      row.append(path,meta);
      if(item.inspection){
        const snapshot=item.inspection,metadata=snapshot.metadata||{};
        const details=document.createElement('p');details.className='small library-inspection';
        details.textContent=(snapshot.plugin?'DLL/plugin · title launch blocked. ':'')+'Last read '+new Date(snapshot.inspected_at*1000).toLocaleString()+' · Title ID '+(metadata.title_id||'unavailable')+' · Media ID '+(metadata.media_id||'unavailable')+' · Disc '+(metadata.disc||'?')+'/'+(metadata.disc_count||'?')+' · Version '+(metadata.version||'?')+' / base '+(metadata.base_version||'?');
        const hash=document.createElement('p');hash.className='mono small';hash.textContent='Measured XEX SHA-256: '+snapshot.sha256;
        row.append(details,hash);
      }
      const actions=document.createElement('div');actions.className='game-actions';
      if(/\.xex$/i.test(item.path)){
        const read=document.createElement('button');read.className='secondary';read.textContent=item.inspection?'Re-read metadata':'Read metadata';
        const readStatus=document.createElement('p');readStatus.className='small library-read-status';readStatus.setAttribute('role','status');
        read.onclick=()=>{
          if(busy){readStatus.textContent='Wait for the current console operation, then retry.';return;}
          task(async()=>{read.disabled=true;readStatus.textContent='Reading metadata from console…';try{
            requireCurrentLibrary();if(module){await inspectPluginFile(item.path);await loadGameLibrary();return;}
            const result=await api('games/inspect',{path:item.path});if(generation!==gameLibraryGeneration||!connected)return;
            let lookupNote='';const titleId=result.verification?.metadata?.title_id;
            if(group.categories?.includes('games')&&/^[0-9A-F]{8}$/i.test(titleId||'')&&titleId!=='00000000'){
              try{const cached=await api('metadata/lookup',{title_id:titleId});if(cached.state==='not-cached')await api('metadata/lookup',{title_id:titleId,online:true});}
              catch(error){lookupNote=' Community name or cover unavailable: '+error.message;}
            }
            if(generation!==gameLibraryGeneration||!connected)return;
            await loadGameLibrary();if(generation===gameLibraryGeneration&&connected)notice('Inspection saved. '+result.verification.label+lookupNote);
          }catch(error){readStatus.textContent='Read failed. '+error.message;throw error;}
          finally{read.disabled=false;}});
        };
        actions.append(read);
        row.append(readStatus);
        if(!module&&!item.inspection?.plugin){const launch=document.createElement('button');launch.className='secondary';launch.textContent='Validate & launch';launch.onclick=()=>task(async()=>{requireCurrentLibrary();await inspect(item.path);});actions.append(launch);}
      }
      row.append(actions);copies.append(row);
    }
    card.append(cover,name,badge,copies);
    const identity=document.createElement('p');identity.className='small library-title-info';
    const plugin=module;
    const first=group.copies[0],metadata=first.inspection?.metadata||{};
    identity.textContent=(group.categories||['uncategorized']).map(category=>gameCategoryLabels[category]||category).join(' / ')+' · '+({'custom':'Your label','community':'Community title','aurora':'Aurora title','folder':'Folder name','filename':'Filename','known':'Known component hint'})[group.name_source||'folder']+(first.label?.mode?' · '+gameModeLabel(first.label.mode):'')+(metadata.disc_count>1?' · Disc '+metadata.disc+'/'+metadata.disc_count:'')+(group.title_id&&!group.component?' · '+group.title_id:'');
    if(group.component?.observed_hash_match)identity.textContent+=' · Observed public hash, unreviewed';
    card.append(identity);
    const quick=document.createElement('div');quick.className='library-quick-actions';
    const launchable=group.copies.filter(item=>!module&&group.format==='xex'&&!item.inspection?.plugin);
    if(launchable.length){
      let chosen=launchable.length===1?launchable[0]:null;
      const launch=document.createElement('button');launch.type='button';launch.className='primary';launch.textContent='Launch';launch.disabled=!chosen;
      if(launchable.length>1){const select=document.createElement('select');select.setAttribute('aria-label','Choose launch entry for '+group.name);select.append(Object.assign(document.createElement('option'),{value:'',textContent:'Choose an entry…'}));for(const item of launchable){const metadata=item.inspection?.metadata||{};select.append(Object.assign(document.createElement('option'),{value:item.path,textContent:item.path+(item.label?.mode?' · '+gameModeLabel(item.label.mode):'')+(metadata.disc_count>1?' · Disc '+metadata.disc+'/'+metadata.disc_count:'')}));}select.onchange=()=>{chosen=launchable.find(item=>item.path===select.value)||null;launch.disabled=!chosen;};quick.append(select);}
      launch.onclick=()=>task(async()=>{requireCurrentLibrary();if(!chosen)throw Error('Choose a launch location.');await inspect(chosen.path);});quick.append(launch);
    }else if(plugin){const open=document.createElement('button');open.className='secondary';open.textContent='Open Plugins';open.onclick=()=>{$('plugin-inspect-path').value=first.path;openWorkspaceView('plugins');};quick.append(open);}
    const organize=document.createElement('button');organize.className='secondary';organize.textContent='Organize';organize.onclick=()=>{requireCurrentLibrary();openLibraryOrganizer(group.copies,group.name);};quick.append(organize);
    card.append(quick);
    if(!module&&group.format==='xex'&&gameCategoryMatches(group,'games')){
      const addons=document.createElement('details');addons.className='library-addons';
      const heading=document.createElement('summary');heading.textContent='Trainers, title updates & mods';
      const help=document.createElement('p');help.className='small';help.textContent='Find files on your console. An unread game launcher is inspected for its Title ID. Found files are candidates; active title update status is unknown.';
      const find=document.createElement('button');find.type='button';find.className='secondary';find.textContent='Find installed content';
      const results=document.createElement('div');results.className='library-addon-results';results.setAttribute('aria-live','polite');
      find.onclick=()=>task(async()=>{
        requireCurrentLibrary();const first=group.copies[0],selectedRoot=$('games-scan-location').value||'all';
        const current=()=>generation===gameLibraryGeneration&&connected&&selectedRoot.toLowerCase()===($('games-scan-location').value||'all').toLowerCase()&&Array.from(list.children).includes(card);
        find.disabled=true;results.textContent='Checking console folders…';
        try{
          if(!/^[0-9A-F]{8}$/i.test(first.inspection?.metadata?.title_id||'')){
            const inspected=await api('games/inspect',{path:first.path});if(!current())return;
            if(inspected.plugin){results.textContent='This XEX is a plugin; game content lookup is unavailable.';return;}
          }
          const discovered=await api('games/addons',{path:first.path});if(!current())return;
          results.replaceChildren();
          for(const [key,label] of [['trainers','Trainers'],['title_updates','Title updates'],['mods','Mods'],['mod_menus','Mod menus']]){
            const section=document.createElement('section');section.className='library-addon-kind';
            const title=document.createElement('h4');const entries=discovered.items?.[key]||[];title.textContent=label+' · '+entries.length;section.append(title);
            for(const entry of entries){const row=document.createElement('div');row.className='library-addon-file';
              const name=document.createElement('strong');name.textContent=entry.name;
              const path=document.createElement('p');path.className='mono';path.textContent=entry.path;
              const source=document.createElement('p');source.className='small';source.textContent=entry.source+' · '+bytesLabel(entry.size);
              row.append(name,path,source);
              if(key==='title_updates'){
                const inspectUpdate=document.createElement('button');inspectUpdate.type='button';inspectUpdate.className='secondary';inspectUpdate.textContent='Inspect update';
                const inspection=document.createElement('p');inspection.className='small';inspection.setAttribute('role','status');
                inspectUpdate.onclick=()=>task(async()=>{
                  requireCurrentLibrary();inspectUpdate.disabled=true;inspection.textContent='Reading selected update…';
                  try{const result=await api('games/title-update',{game_path:first.path,path:entry.path});if(!current())return;
                    const header=result.header,assessment={'matching-media-id':'Media ID matches saved game','different-release':'Media ID differs from saved game','different-title':'Title ID differs from saved game',unknown:'Match cannot be assessed'}[result.assessment]||'Match cannot be assessed';
                    const names=[header.display_name?'Package: '+header.display_name:null,header.title_name&&header.title_name!==header.display_name?'Title: '+header.title_name:null].filter(Boolean);
                    inspection.textContent=(names.length?names.join(' · ')+' · ':'')+'Title ID '+header.title_id+' · Media ID '+header.media_id+' · version '+header.version+' · '+assessment+' · SHA-256 '+result.sha256+'. '+result.note;
                  }catch(error){if(current())inspection.textContent='Inspection stopped. '+error.message;throw error;}
                  finally{inspectUpdate.disabled=false;}
                });row.append(inspectUpdate,inspection);
              }
              section.append(row);}
            results.append(section);
          }
          const note=document.createElement('p');note.className='small';note.textContent=(discovered.title_id?'Matched Title ID '+discovered.title_id+'. ':'No measured Title ID; checked the game folder only. ')+(discovered.incomplete?'Some folders could not be checked. ':'')+'Files are listed only; active update state and compatibility are unknown.';results.prepend(note);
          find.textContent='Check again';
        }catch(error){if(current())results.textContent='Content search stopped. '+error.message;throw error;}
        finally{find.disabled=false;}
      });
      const plan=document.createElement('details');plan.className='library-install-plan';
      const planHeading=document.createElement('summary');planHeading.textContent='Preview content placement';
      const planHelp=document.createElement('p');planHelp.className='small';planHelp.textContent='Choose a local file to preview its destination. This does not upload or activate content.';
      const kind=document.createElement('select');kind.setAttribute('aria-label','Content type');
      for(const [value,label] of [['mods','Mods'],['mod_menus','Mod menus'],['trainers','Trainers']])kind.append(Object.assign(document.createElement('option'),{value,textContent:label}));kind.value='mods';
      const file=document.createElement('input');file.type='file';file.setAttribute('aria-label','Local content file');
      const preview=document.createElement('button');preview.type='button';preview.className='secondary';preview.textContent='Preview destination';
      const outcome=document.createElement('p');outcome.className='small mono';outcome.setAttribute('role','status');
      preview.onclick=()=>task(async()=>{requireCurrentLibrary();const selected=file.files?.[0];if(!selected)throw Error('Choose a local file.');
        const selectedRoot=$('games-scan-location').value||'all';const current=()=>generation===gameLibraryGeneration&&connected&&selectedRoot.toLowerCase()===($('games-scan-location').value||'all').toLowerCase()&&Array.from(list.children).includes(card);
        outcome.textContent='Checking destination…';const result=await api('games/install-plan',{game_path:first.path,kind:kind.value,name:selected.name,size:selected.size});if(!current())return;
        outcome.textContent=result.destination+' · '+bytesLabel(result.size)+' · '+(result.folder_exists?'folder exists':'folder must be created')+' · '+(result.conflict?'name conflict':'no name conflict')+' · '+(result.free===null?'free space unknown':bytesLabel(result.free)+' free')+' · '+(result.enough_space===false?'insufficient reported space':'space check '+(result.enough_space===true?'passes':'unknown'))+'. '+result.note;
      });
      plan.append(planHeading,planHelp,kind,file,preview,outcome);
      addons.append(heading,help,find,results,plan);card.append(addons);
    }
    list.append(card);
  }
  if(games.length>gameLibraryShown){const more=document.createElement('button');more.className='secondary library-more';more.textContent='Show '+Math.min(100,games.length-gameLibraryShown)+' more';more.onclick=()=>{gameLibraryShown+=100;renderGameLibrary(gameLibraryFiles);};list.append(more);}
}
async function loadGameLibrary(){requireGameConnection();const generation=gameLibraryGeneration,root=$('games-scan-location').value||'all';const result=await api('library/list',{view:'installs',...(root!=='all'?{root}: {})});if(generation!==gameLibraryGeneration||!connected||root.toLowerCase()!==($('games-scan-location').value||'all').toLowerCase())return;gameLibraryCovers=result.covers||{};renderGameLibrary(result.files,result.items||[]);if(!Array.isArray(result.items))gameLibrarySummary.textContent='Restart the updated local bridge to load physical installs.';}
let quickFindItems=[],quickFindLoading=false;
function renderQuickFind(){
  const host=$('quick-find-results'),query=$('quick-find-input').value.trim().toLowerCase();host.replaceChildren();
  if(quickFindLoading){host.textContent='Loading saved installs…';return;}
  const matches=quickFindItems.filter(item=>[item.name,item.title_id,...(item.paths||[])].join(' ').toLowerCase().includes(query)).slice(0,12);
  if(!matches.length){host.textContent=quickFindItems.length?'No saved installs match.':'No saved installs yet. Scan storage from Games.';return;}
  for(const item of matches){const button=document.createElement('button');button.type='button';button.className='quick-find-result';button.textContent=item.name+' · '+((item.categories||[]).map(key=>gameCategoryLabels[key]||key).join(' / ')||'Library')+(item.title_id?' · '+item.title_id:'');
    button.onclick=()=>{$('quick-find-dialog').close();$('games-scan-location').value='all';gameLibraryCategory='all';gameLibraryFilter='all';gameLibraryQuery=item.paths?.[0]||item.name;gameLibraryShown=100;if(gameLibrarySearch)gameLibrarySearch.value=gameLibraryQuery;openWorkspaceView('games');};host.append(button);}
}
async function openQuickFind(){
  const dialog=$('quick-find-dialog');dialog.showModal();$('quick-find-input').value='';$('quick-find-input').focus();
  const generation=gameLibraryGeneration,epoch=authEpoch;quickFindItems=[];quickFindLoading=connected;$('quick-find-results').textContent=connected?'Loading saved installs…':'Connect a console to search saved installs.';
  if(!connected)return;
  try{const result=await api('library/list',{view:'installs'});if(!dialog.open||generation!==gameLibraryGeneration||epoch!==authEpoch||!connected)return;
    quickFindItems=Array.isArray(result.items)?result.items.filter(item=>item.kind==='installation'):[];quickFindLoading=false;renderQuickFind();
  }catch(error){if(dialog.open){quickFindLoading=false;$('quick-find-results').textContent='Quick Find unavailable. '+error.message;}}
}
$('quick-find-open').onclick=()=>task(openQuickFind);
$('quick-find-input').oninput=renderQuickFind;
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key?.toLowerCase()==='k'){event.preventDefault();if(!$('quick-find-dialog').open)task(openQuickFind);}
  if(event.key==='Escape')closeMobileMenu();});
$('games-health-check').onclick=()=>task(async()=>{
  requireGameConnection();const generation=gameLibraryGeneration,host=$('games-health-result');host.textContent='Checking discovered storage…';
  const report=await api('storage/health',{});if(generation!==gameLibraryGeneration||!connected)return;
  host.replaceChildren();const roots=document.createElement('div');roots.className='storage-health-roots';
  for(const entry of report.roots){const row=document.createElement('p');row.className='small';row.textContent=entry.root+' · '+entry.state+' · '+entry.saved_count+' saved files'+(entry.last_scanned?' · last scanned '+new Date(entry.last_scanned*1000).toLocaleString():'');roots.append(row);}
  if(!report.roots.length)roots.textContent='No discovered or saved storage roots.';
  const copies=document.createElement('details'),heading=document.createElement('summary');heading.textContent='Matching XEX bytes · '+report.matching_xex.length;copies.append(heading);
  for(const group of report.matching_xex){const row=document.createElement('p');row.className='mono small';row.textContent=group.paths.join(' ↔ ')+(group.more_paths?' · more paths omitted':'');copies.append(row);}
  const note=document.createElement('p');note.className='small';note.textContent=report.note+(report.incomplete?' More matches were omitted.':'');host.append(roots,copies,note);
});
const loadShortcutGames=loadGames;loadGames=async()=>{const generation=gameLibraryGeneration;await loadShortcutGames();if(generation===gameLibraryGeneration&&connected)await loadGameLibrary();};
const resetShortcutGames=resetGames;resetGames=()=>{gameLibraryGeneration++;gameLibraryFiles=[];gameLibraryGroups=[];gameLibraryCovers={};quickFindItems=[];quickFindLoading=false;if($('quick-find-dialog').open)$('quick-find-dialog').close();gameLibraryCategory='all';libraryOrganization=null;if($('library-organize-dialog').open)$('library-organize-dialog').close();resetShortcutGames();for(const id of ['games-scan-location','plugin-scan-location']){$(id).replaceChildren(Object.assign(document.createElement('option'),{value:'all',textContent:'All discovered storage'}));$(id).value='all';}if(gameLibraryList)gameLibraryList.replaceChildren();if(gameLibraryOtherResult)gameLibraryOtherResult.replaceChildren();if(gameLibraryChips)gameLibraryChips.replaceChildren();if(gameLibrarySummary)gameLibrarySummary.textContent='';};
renderGameLibrary([]);
$('game-executable').oninput=()=>{$('game-mode').value='';};
$('game-save').onsubmit=e=>{e.preventDefault();task(async()=>{requireGameConnection();const entry={name:$('game-name').value.trim(),folder:$('game-folder').value.replace(/\\?$/,'\\'),executable:$('game-executable').value.trim(),mode:$('game-mode').value};if(!entry.name)throw Error('Enter a shortcut name.');await api('games/save',entry);await loadGames();notice('Game shortcut saved on your local bridge.');});};

function gameBadge(result){const badge=document.createElement('span');const status=result.status;badge.className='game-badge '+(status==='verified'?'verified':['mismatch','revoked'].includes(status)?'mismatch':'unknown');badge.textContent=(status==='verified'||['mismatch','revoked'].includes(status)?'✓ ':'? ')+result.label;return badge;}
function showGameMetadata(result,fallback){const report=result.verification,metadata=report.metadata||{},game=report.game;$('game-preview-name').textContent=game?.title||fallback;$('game-preview-source').textContent=game?.source||'File metadata from console XEX; artwork not available';$('game-cover').replaceChildren();if(game?.cover){const img=document.createElement('img');img.src=game.cover;img.alt=(game.title||fallback)+' cover';img.onerror=()=>{$('game-cover').textContent='Artwork unavailable';};$('game-cover').append(img);}else $('game-cover').textContent='XBOX 360';const container=$('game-metadata');container.replaceChildren();for(const [label,key] of [['Title ID','title_id'],['Media ID','media_id'],['File version (hex)','version'],['Base version (hex)','base_version'],['Disc','disc'],['Disc count','disc_count']])detail(container,label,metadata[key]);}
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
    if(!connected||!candidateInspection)throw Error('Inspect a real console file before exporting a candidate.');
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
  if(typeof resetPreviewLookup==='function')resetPreviewLookup();
  const generation=++gamePreviewGeneration;
  const current=()=>generation===gamePreviewGeneration&&$('game-preview-dialog').open;
  resetGameCandidate();
  $('game-preview-name').textContent=entry.name;$('game-preview-source').textContent='Reading game folder…';
  $('game-metadata').replaceChildren();$('game-cover').textContent='XBOX 360';$('game-launch-files').replaceChildren();
  $('game-preview-dialog').showModal();
  const files=(await api('browse',{path:entry.folder})).files;
  if(!current())return;
  const xex=sortedFiles(files).filter(f=>!f.directory&&/\.xex$/i.test(f.name));
  $('game-preview-source').textContent='Select a file to read metadata and verify its current bytes.';
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
        const result=await api('games/inspect',{path});
        if(!current())return;
        const fresh=gameBadge(result.verification);badge.className=fresh.className;badge.textContent=fresh.textContent;
        showGameMetadata(result,entry.name);offerGameCandidate(result);if(typeof offerTitleLookup==='function')await offerTitleLookup(result.verification.metadata?.title_id);
        const card=Array.from(document.querySelectorAll('.game-card')).find(c=>c.dataset.shortcutId===String(entry.id));
        if(card&&result.verification.game){
          card.querySelector('h3').textContent=result.verification.game.title+(entry.mode?' · '+gameModeLabel(entry.mode):'');
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

async function discoverStorage(){
  if(!connected)throw Error('Connect a console first.');
  notice('Discovering accessible console storage…');
  const result=await api('storage/discover');
  $('drive').replaceChildren();
  for(const root of result.drives)$('drive').append(Object.assign(document.createElement('option'),{value:root,textContent:root}));
  $('path').value=result.drives[0]||'';
  syncGameDrives(result.drives);
  $('game-folder').value=result.drives[0]||'';
  $('metric-drives').textContent=result.drives.length;
  $('browse').disabled=!result.drives.length;$('game-browse').disabled=!result.drives.length;
  $('files').replaceChildren();$('game-files').replaceChildren();
  const message=result.storage.state==='PARTIAL'?'Discovery reached its time limit; retry to check remaining roots.':result.drives.length?'Accessible storage refreshed. Select a root and Browse.':'No accessible roots found. Check storage in Neighborhood and run the storage diagnostic.';
  notice(message);$('files').textContent=message;$('game-files').textContent=message;
  log('Storage discovery: '+result.drives.length+' accessible; '+result.storage.unavailable+' unavailable.');
}
$('storage-discover').onclick=()=>task(discoverStorage);
$('game-discover').onclick=()=>task(discoverStorage);
