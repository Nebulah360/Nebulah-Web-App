'use strict';
const launcherPanel=$('launcher-settings-panel');
launcherPanel.hidden=phoneBrowser;
if(!phoneBrowser){
  const launcherForm=$('launcher-settings-form'), launcherMessage=$('launcher-settings-status');
  async function loadLauncherSettings(){
    if(!browserPaired){launcherMessage.textContent='Pair this PC browser to view launcher settings.';return;}
    try{
      const settings=await api('launcher/settings');
      $('launcher-phone-access').checked=settings.phone_access;
      $('launcher-browser').value=settings.browser;
      $('launcher-open-browser').checked=settings.open_browser;
      launcherMessage.textContent='Saved settings loaded. Changes take effect on the next bridge start.';
    }catch(error){launcherMessage.textContent=error.message;}
  }
  launcherPanel.addEventListener('toggle',()=>{if(launcherPanel.open)loadLauncherSettings();});
  launcherForm.addEventListener('submit',async event=>{
    event.preventDefault();
    const button=launcherForm.querySelector('button[type="submit"]');
    button.disabled=true;
    try{
      await api('launcher/save',{
        phone_access:$('launcher-phone-access').checked,
        browser:$('launcher-browser').value,
        open_browser:$('launcher-open-browser').checked
      });
      launcherMessage.textContent='Saved. Restart Nebulah Link to apply these settings.';
    }catch(error){launcherMessage.textContent=error.message;}
    finally{button.disabled=false;}
  });
}

let appSettings=null,selectedSettingsProfile='';
function renderSettingsProfiles(){
  if(selectedSettingsProfile&&!profiles.some(profile=>profile.id===selectedSettingsProfile)){
    selectedSettingsProfile='';$('settings-profile-remove').disabled=true;
  }
  const list=$('settings-profile-list');list.replaceChildren();
  if(!profiles.length){const empty=document.createElement('p');empty.className='settings-empty';empty.textContent='No saved consoles yet. Connect to one or add a profile below.';list.append(empty);return;}
  for(const profile of profiles){
    const card=document.createElement('button');card.type='button';card.className='settings-profile-card';card.setAttribute('aria-pressed',String(profile.id===selectedSettingsProfile));
    const name=document.createElement('strong'),target=document.createElement('small');name.textContent=profile.name;target.textContent=profile.target;card.append(name,target);
    card.onclick=()=>{selectedSettingsProfile=profile.id;$('settings-profile-name').value=profile.name;$('settings-profile-target').value=profile.target;$('target').value=profile.target;$('profile-select').value=profile.id;$('settings-profile-remove').disabled=false;$('settings-profile-status').textContent='Selected '+profile.name+'. Open Connect console to use this target.';renderSettingsProfiles();};
    list.append(card);
  }
}
function renderAppSettings(){
  if(!appSettings)return;
  $('settings-default-ip').value=appSettings.default_console_ip;
  $('settings-allow-writes').checked=appSettings.allow_writes;
  $('settings-admin').textContent=appSettings.admin_control?'Disable Admin control':'Enable Admin control';
  $('settings-admin').disabled=!connected||phoneBrowser;
  $('settings-access-summary').textContent=appSettings.admin_control?'Admin control active on this PC for the current console.':appSettings.allow_writes?'Standard write access is on.':'Write access is off for paired browsers.';
}
async function loadAppSettings(){
  renderSettingsProfiles();
  if(connected){try{await loadProfiles();renderSettingsProfiles();}catch(error){$('settings-profile-status').textContent=error.message;}}
  if(phoneBrowser){$('settings-status').textContent='Open this page on the bridge PC to change connection settings.';$('settings-admin').disabled=true;return;}
  if(!browserPaired){$('settings-status').textContent='Pair this PC browser to load settings.';return;}
  try{appSettings=await api('settings/read');renderAppSettings();$('settings-status').textContent='Preferences loaded from this bridge PC.';}
  catch(error){$('settings-status').textContent=error.message;}
}
$('settings-form').onsubmit=event=>{event.preventDefault();task(async()=>{
  const button=$('settings-form').querySelector('button[type="submit"]');button.disabled=true;
  try{appSettings=await api('settings/save',{default_console_ip:$('settings-default-ip').value.trim(),allow_writes:$('settings-allow-writes').checked});renderAppSettings();$('settings-status').textContent='Saved. Blank-target connections now use this choice.';}
  finally{button.disabled=false;}
});};
$('settings-admin').onclick=()=>task(async()=>{appSettings=await api('settings/admin',{enabled:!appSettings?.admin_control});renderAppSettings();$('settings-status').textContent=appSettings.admin_control?'Admin enabled for this PC and console.':'Admin disabled.';});
$('settings-profiles-refresh').onclick=()=>task(async()=>{await loadProfiles();renderSettingsProfiles();$('settings-profile-status').textContent='Profiles refreshed from the bridge.';});
$('settings-profile-form').onsubmit=event=>{event.preventDefault();task(async()=>{
  const name=$('settings-profile-name').value.trim(),target=$('settings-profile-target').value.trim();
  if(!validConsoleTarget(target))throw Error('Use a console name or local IP without a port.');
  await api('profiles/save',{id:selectedSettingsProfile||undefined,name,target});
  await loadProfiles();selectedSettingsProfile=profiles.find(profile=>profile.name===name&&profile.target===target)?.id||'';
  $('settings-profile-remove').disabled=!selectedSettingsProfile;renderSettingsProfiles();$('settings-profile-status').textContent='Profile saved on the bridge.';
});};
$('settings-profile-remove').onclick=()=>task(async()=>{
  if(!selectedSettingsProfile)throw Error('Select a profile first.');
  await api('profiles/remove',{id:selectedSettingsProfile});selectedSettingsProfile='';
  $('settings-profile-name').value='';$('settings-profile-target').value='';$('settings-profile-remove').disabled=true;
  await loadProfiles();renderSettingsProfiles();$('settings-profile-status').textContent='Profile removed.';
});
renderSettingsProfiles();
