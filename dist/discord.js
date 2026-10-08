'use strict';
const discordPanel=$('discord-presence-panel');
discordPanel.hidden=phoneBrowser;
if(!phoneBrowser){
  const form=$('discord-presence-form'),start=$('discord-presence-start'),stop=$('discord-presence-stop');
  const client=$('discord-client-id'),imageKey=$('discord-image-key'),message=$('discord-presence-status');
  try{client.value=localStorage.getItem('nebulah-discord-client-id')||'1557343557046640750';}
  catch{client.value='1557343557046640750';}
  function renderDiscord(state){
    const active=state.state==='active';
    $('brandmark').classList.toggle('presence-active',active);
    $('brandmark').title=active?'Discord activity active':'Nebulah Link';
    start.disabled=state.enabled||!connected;
    stop.disabled=!state.enabled;
    message.textContent={active:'Sharing Xbox 360 activity through Discord on this PC.',
      connecting:'Connecting to Discord desktop…',unavailable:'Discord desktop did not accept the connection. Check the application ID and restart Discord.',
      disabled:'Stopped.'}[state.state]||'Discord status unavailable.';
  }
  async function refreshDiscord(){
    if(!browserPaired)return;
    try{renderDiscord(await api('discord/status'));}
    catch(error){message.textContent=error.message;}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!connected){message.textContent='Connect the console first.';return;}
    start.disabled=true;
    try{
      const result=await api('discord/start',{client_id:client.value.trim(),image_key:imageKey.value.trim()});
      try{localStorage.setItem('nebulah-discord-client-id',client.value.trim());}catch{}
      renderDiscord(result);
    }catch(error){message.textContent=error.message;start.disabled=false;}
  });
  stop.addEventListener('click',async()=>{
    stop.disabled=true;
    try{renderDiscord(await api('discord/stop'));}
    catch(error){message.textContent=error.message;stop.disabled=false;}
  });
  discordPanel.addEventListener('toggle',()=>{if(discordPanel.open)refreshDiscord();});
  setInterval(refreshDiscord,10000);
}
