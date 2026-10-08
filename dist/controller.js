const controllerButtons=Array.from(document.querySelectorAll('[data-controller-button]'));
let controllerReady=false;

function setControllerConnected(available){
  if(!available){controllerReady=false;$('controller-status').textContent='Connect a console to check controller support.';}
  for(const button of controllerButtons)button.disabled=!available||!controllerReady;
  $('controller-check').disabled=!available;
}

async function refreshControllerSupport(){
  if(!connected){setControllerConnected(false);return;}
  $('controller-status').textContent='Checking Companion input support…';
  try{
    const result=await api('controller/capabilities');
    controllerReady=result.available===true;
    setControllerConnected(true);
    $('controller-status').textContent=result.reason;
  }catch(error){controllerReady=false;setControllerConnected(true);$('controller-status').textContent=error.message;throw error;}
}

$('controller-check').onclick=()=>task(refreshControllerSupport);
$('console-screen-panel').addEventListener('toggle',()=>{
  if($('console-screen-panel').open&&connected)task(refreshControllerSupport);
});
for(const button of controllerButtons)button.onclick=()=>task(async()=>{
  if(!connected||!controllerReady)throw Error('Check controller support first.');
  for(const item of controllerButtons)item.disabled=true;
  $('controller-status').textContent='Sending '+button.textContent+'…';
  try{
    const result=await api('controller/pulse',{button:button.dataset.controllerButton});
    if(result.accepted!==true)throw Error('The console did not confirm the input pulse.');
    const source=result.mode==='virtual'?'virtual controller':'connected controller';
    $('controller-status').textContent=(button.getAttribute('aria-label')||button.textContent)+' pulse accepted through '+source+'. Capturing screen…';
    try{await captureConsoleScreen();$('controller-status').textContent=(button.getAttribute('aria-label')||button.textContent)+' pulse accepted through '+source+'. Check the captured screen for a response.';}
    catch{$('controller-status').textContent=(button.getAttribute('aria-label')||button.textContent)+' pulse accepted through '+source+'. Screen capture unavailable.';}
  }catch(error){$('controller-status').textContent=error.message;throw error;}
  finally{setControllerConnected(connected);}
});
