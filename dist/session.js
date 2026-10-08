'use strict';
let resumeRetryTimer=null,resumeRetryUntil=0;
function stopResumeRetry(){clearTimeout(resumeRetryTimer);resumeRetryTimer=null;resumeRetryUntil=0;}
function startBrowserSession(){stopAutoConnect();stopResumeRetry();browserPaired=true;token='';$('session-sign-out').hidden=false;}
function expireBrowserSession(sendLogout=true){
  if(!browserPaired)return;
  stopAutoConnect();stopResumeRetry();browserPaired=false;$('session-sign-out').hidden=true;authEpoch++;token='';connected=false;sessionActive=false;selected=null;setPowerControls(false);
  hideCpuKey();resetGames();clearTelemetry('Signed out');
  $('token').value='';$('token').required=false;$('connect').textContent='Connect console';$('connection-label').textContent='Not paired';$('metric-status').textContent='Signed out';$('mode').textContent='OFFLINE';
  $('console-note').textContent='Reconnect to resume Neighborhood access.';
  for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
  notice('Browser pairing ended. Pair again to continue.');
  if(sendLogout)api('session/logout').catch(()=>{});
}
async function resumeBrowserSession(){
  try{const result=await api('session/resume');if(result.awaiting_console){await waitForConsole();return;}startBrowserSession();status(result.status);}
  catch(error){
    if(error.httpStatus===401){stopResumeRetry();if(!phoneBrowser)await pairLocalPc();return;}
    if(!resumeRetryUntil)resumeRetryUntil=Date.now()+180000;
    if(Date.now()<resumeRetryUntil){
      notice('Local bridge restarting. Reconnecting to the previous console…');
      clearTimeout(resumeRetryTimer);resumeRetryTimer=setTimeout(resumeBrowserSession,5000);
    }else{stopResumeRetry();notice('Could not restore the console session. Pair again with the PC bridge.');}
  }
}
async function pairLocalPc(){
  try{const result=await api('session/local-pair');if(result.awaiting_console)await waitForConsole();}
  catch(error){notice('PC pairing unavailable. Open the bridge URL on this PC.');}
}
let autoConnectTimer=null,autoConnectPending=false,awaitingConsole=false;
function stopAutoConnect(){awaitingConsole=false;clearTimeout(autoConnectTimer);autoConnectTimer=null;}
async function waitForConsole(){
  browserPaired=true;$('session-sign-out').hidden=false;token='';awaitingConsole=true;
  $('token').required=false;
  await autoConnectConsole();
}
async function autoConnectConsole(){
  autoConnectTimer=null;
  if(!awaitingConsole||autoConnectPending||consoleRecoveryHold||connected)return;
  if(busy){autoConnectTimer=setTimeout(autoConnectConsole,15000);return;}
  autoConnectPending=true;busy=true;
  try{
    const result=await api('connect',{target:'',recovery_confirmed:false});
    startBrowserSession();status(result);
    notice('Connected automatically.'+(result.connection_toast==='accepted'?' Xbox toast command accepted.':''));
  }catch(error){
    if(!awaitingConsole)return;
    const absent=['DEFAULT_CONSOLE_EMPTY','CONSOLE_OPEN_FAILED'].includes(error.diagnostic?.code);
    if(absent&&!error.recoveryRequired&&!consoleRecoveryHold){
      notice('Pairing saved. Waiting for your console. Checking again in 15 seconds.');
      autoConnectTimer=setTimeout(autoConnectConsole,15000);
    }else{
      stopAutoConnect();notice('Pairing saved. '+error.message);showConnectionDiagnostic(error);
    }
  }finally{autoConnectPending=false;busy=false;}
}
async function startupPairing(){
  const match=typeof location!=='undefined'&&/^#pair=([A-Za-z0-9_-]{32,128})$/.exec(location.hash||'');
  if(!match){await resumeBrowserSession();return;}
  history.replaceState(null,'',location.pathname+location.search);
  token=match[1];
  try{const result=await api('session/pair');token='';
    if(result.awaiting_console){await waitForConsole();return;}
    throw Error('Startup pairing response was incomplete. Restart the local bridge.');
  }
  catch(error){token='';if(!phoneBrowser)await pairLocalPc();}
}
$('session-sign-out').onclick=()=>expireBrowserSession();
startupPairing();
