let rteSnapshot=null,rteLastRead=null,rtePokeTicket=null;
document.querySelector('.rte-poke').hidden=true;

function rteReset(message){
  rteSnapshot=null;rteLastRead=null;rtePokeTicket=null;
  $('rte-cod4').hidden=true;$('rte-cod4-status').textContent='Ready for a read-only module check.';
  if($('rte-poke-dialog').open)$('rte-poke-dialog').close();
  $('rte-poke-address').value='';$('rte-poke-current').value='';$('rte-poke-new').value='';
  $('rte-poke-preview').disabled=true;$('rte-poke-status').textContent='Read memory first. This tool does not save or replay edits.';
  $('rte-address').value='';
  $('rte-watch').checked=false;$('rte-watch').disabled=true;
  $('rte-read').disabled=true;$('rte-use-base').disabled=true;
  $('rte-build').disabled=true;$('rte-build-result').textContent='Refresh a running title first.';
  $('rte-title').textContent='Unavailable';$('rte-title-id').textContent='Title ID unavailable';
  $('rte-module').textContent='Unavailable';$('rte-module-range').textContent='Start a game to inspect its module.';
  $('rte-state').textContent='Unavailable';$('rte-message').textContent=message;
  $('rte-bytes').textContent='Read a title address to see its bytes.';$('rte-read-time').textContent='No read yet';
}

function rteOnStatus(status){
  const title=status.current_title||{},name=(title.executable||'').split(/[\\/]/).pop();
  if(rteSnapshot&&(rteSnapshot.title_id!==title.title_id||rteSnapshot.executable.toLowerCase()!==(title.executable||'').toLowerCase()))
    rteReset('The running title changed. Refresh before reading memory.');
  $('rte-title').textContent=name||'No running title reported';
  $('rte-title-id').textContent=title.title_id?'Title ID '+title.title_id:'Title ID unavailable';
}

function rteViewChanged(name){
  if(name!=='rte'&&rteSnapshot)rteReset('Memory result cleared when you left RTE / RTM.');
}

async function refreshRte(){
  if(!connected){rteReset('Connect a console first.');return;}
  $('rte-state').textContent='Checking';$('rte-message').textContent='Checking the running title and XBDM module bounds…';
  try{
    const snapshot=await api('rte/status');
    if(snapshot.state!=='ready'||!snapshot.module?.base||!snapshot.title_id)throw Error('Title module was not confirmed.');
    if(rteSnapshot&&(rteSnapshot.title_id!==snapshot.title_id||rteSnapshot.module.base!==snapshot.module.base))
      rteReset('The running title changed. Previous memory result was cleared.');
    rteSnapshot=snapshot;
    $('rte-cod4').hidden=snapshot.title_id!=='415607E6';
    $('rte-cod4-status').textContent='Ready for a read-only module check.';
    $('rte-title').textContent=snapshot.executable.split(/[\\/]/).pop();
    $('rte-title-id').textContent='Title ID '+snapshot.title_id;
    $('rte-module').textContent=snapshot.module.name;
    $('rte-module-range').textContent=snapshot.module.base+' · '+(snapshot.module.size/1048576).toFixed(1)+' MiB mapped';
    $('rte-state').textContent='Read ready';$('rte-message').textContent='Read-only XBDM access confirmed for this running title.';
    $('rte-read').disabled=false;$('rte-use-base').disabled=false;$('rte-watch').disabled=false;
    $('rte-build').disabled=false;$('rte-build-result').textContent='Ready to measure the on-disk XEX.';
  }catch(error){rteReset(error.message||'Title inspection unavailable.');throw error;}
}

async function readRte(){
  if(!connected||!rteSnapshot)throw Error('Refresh the running title first.');
  const address=$('rte-address').value.trim(),length=Number($('rte-length').value);
  if(!/^0x[0-9a-fA-F]{8}$/.test(address))throw Error('Enter an address such as 0x82000000.');
  try{
    const result=await api('rte/read',{title_id:rteSnapshot.title_id,executable:rteSnapshot.executable,module_base:rteSnapshot.module.base,module_size:rteSnapshot.module.size,address,length});
    const pairs=result.hex.match(/.{2}/g)||[],lines=[];
    for(let offset=0;offset<pairs.length;offset+=16)
      lines.push('0x'+(parseInt(result.address,16)+offset).toString(16).toUpperCase().padStart(8,'0')+'  '+pairs.slice(offset,offset+16).join(' '));
    $('rte-bytes').textContent=lines.join('\n');$('rte-read-time').textContent='Read at '+new Date().toLocaleTimeString();
    rteLastRead={title_id:result.title_id,executable:result.executable,module_base:result.module_base,module_size:result.module_size,address:result.address,expected:result.hex.slice(0,8)};
    rtePokeTicket=null;$('rte-poke-address').value=result.address;$('rte-poke-current').value=rteLastRead.expected;
    const gameTitle=result.title_id!=='FFFE07D1'&&rteSnapshot.module.name.toLowerCase()!=='dash.xex';
    $('rte-poke-preview').disabled=!gameTitle;
    $('rte-poke-status').textContent=gameTitle?'Current four bytes captured. Enter a replacement to review.':'Start a game before editing memory; dashboard edits are disabled.';
    $('rte-message').textContent='Read '+result.length+' bytes from the running '+result.title_id+' title.';
  }catch(error){$('rte-watch').checked=false;rteLastRead=null;$('rte-poke-preview').disabled=true;$('rte-message').textContent='Read stopped: '+(error.message||'Console read unavailable.');throw error;}
}

$('rte-refresh').onclick=()=>task(refreshRte);
$('rte-build').onclick=()=>task(async()=>{
  if(!connected||!rteSnapshot)throw Error('Refresh the running title first.');
  const snapshot=rteSnapshot,result=$('rte-build-result');result.textContent='Measuring the on-disk XEX…';
  try{
    const measured=await measureOnDiskXex(snapshot);
    if(rteSnapshot!==snapshot)
      throw Error('The running title changed. Refresh before measuring again.');
    result.textContent=onDiskXexText(measured);
  }catch(error){result.textContent='Build inspection failed: '+error.message;throw error;}
});
$('rte-cod4-check').onclick=()=>task(async()=>{
  if(!connected||rteSnapshot?.title_id!=='415607E6')throw Error('Refresh a running COD4 title first.');
  const state=$('rte-cod4-status');state.textContent='Reading the active COD4 mapped module header…';
  try{
    const result=await api('rte/read',{title_id:rteSnapshot.title_id,executable:rteSnapshot.executable,module_base:rteSnapshot.module.base,module_size:rteSnapshot.module.size,address:rteSnapshot.module.base,length:4});
    if(result.title_id!=='415607E6'||result.module_base!==rteSnapshot.module.base)throw Error('COD4 changed during the check. Refresh title.');
    state.textContent=/^4D5A[0-9A-F]{4}$/.test(result.hex)
      ?'MZ mapped-image header read from the active COD4 module. This does not verify the game build or mod offsets.'
      :'Active module header differs from MZ. Check the running title before using a memory recipe.';
  }catch(error){state.textContent='COD4 module check failed: '+error.message;throw error;}
});
$('rte-use-base').onclick=()=>{if(rteSnapshot){$('rte-address').value=rteSnapshot.module.base;$('rte-address').focus();}};
$('rte-read-form').onsubmit=event=>{event.preventDefault();task(readRte);};
$('rte-address').oninput=()=>{$('rte-watch').checked=false;rteLastRead=null;$('rte-poke-preview').disabled=true;};
$('rte-length').onchange=()=>{$('rte-watch').checked=false;};
$('rte-watch').onchange=()=>{if($('rte-watch').checked&&!busy)task(readRte);};
function clearPokePreview(){rtePokeTicket=null;}
$('rte-poke-new').oninput=clearPokePreview;
$('rte-poke-form').onsubmit=event=>{event.preventDefault();task(async()=>{
  if(!rteLastRead||!rteSnapshot)throw Error('Read the address before preparing an edit.');
  $('rte-watch').checked=false;
  const replacement=$('rte-poke-new').value.trim().toUpperCase();
  if(!/^[0-9A-F]{8}$/.test(replacement)||replacement===rteLastRead.expected)throw Error('Enter eight changed hexadecimal digits.');
  const preview=await api('rte/poke-preview',{...rteLastRead,replacement});
  rtePokeTicket=preview.ticket;
  $('rte-poke-review').textContent=preview.title_id+' at '+preview.address+'\n'+preview.expected+'  →  '+preview.replacement;
  $('rte-poke-status').textContent='Edit ready. Confirm within '+preview.expires_in+' seconds.';
  $('rte-poke-dialog').showModal();
});};
$('rte-poke-cancel').onclick=()=>$('rte-poke-dialog').close();
$('rte-poke-dialog').addEventListener('close',clearPokePreview);
$('rte-poke-confirm').onclick=()=>task(async()=>{
  if(!rtePokeTicket)throw Error('Review the edit again.');
  const ticket=rtePokeTicket;rtePokeTicket=null;
  $('rte-poke-dialog').close();
  try{
    const result=await api('rte/poke-apply',{ticket,confirmed:true});
    if(result.state!=='verified')throw Error('Memory write was not verified.');
    $('rte-poke-status').textContent='Four bytes written and read back at '+result.address+'.';
    showToast('Title memory edit verified.');log('Title memory edit verified.');
    rteLastRead=null;$('rte-poke-preview').disabled=true;
  }catch(error){$('rte-poke-status').textContent=error.message;throw error;}
});
setInterval(()=>{
  if($('rte-watch').checked&&connected&&!busy&&!document.hidden&&!$('rte').hidden&&!document.querySelector('dialog[open]'))task(readRte);
},10000);
