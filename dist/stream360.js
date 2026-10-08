'use strict';
$('stream360-unload').hidden=true;
// Poll one bounded JPEG frame through the existing paired-browser API.
let stream360Polling=false,stream360FrameBusy=false,stream360FrameActive=false;
let stream360FrameSequence=0,stream360FrameRetry=0;
let stream360AudioContext=null,stream360AudioActive=false,stream360AudioBusy=false;
let stream360AudioSequence=0,stream360AudioNext=0;
function renderStream360(state){
  const listening=state.state==='listening',live=state.connected;
  $('stream360-state').textContent=({stopped:'Stopped',listening:'Listening for console',connected:'Console connected',receiving:'Receiving console packets'})[state.state]||'Unavailable';
  $('stream360-counts').textContent=state.video_frames+' video frames · '+state.audio_packets+' audio packets';
  $('stream360-signal').textContent=state.unload_uncertain?'Unload call accepted, but Xbox360Stream.xex remains listed. Do not retry. A cold reboot can clear this runtime load.':state.safe_to_unload?'SAFE_TO_UNLOAD received. Use your console module loader or a cold reboot; direct unload in Nebulah is paused.':state.preparing_unload?'Waiting for SAFE_TO_UNLOAD. Do not unload the module yet.':state.last_status||'No console status yet.';
  $('stream360-error').textContent=state.safe_to_unload?'':state.last_error==='invalid-packet'?'Console packet rejected. Check the exact 360Stream version.':state.last_error==='connection-closed'?'Console stream disconnected. The receiver remains ready.':listening&&state.waiting_seconds>=20?'No console TCP connection after '+state.waiting_seconds+' seconds. If the module is loaded, check the game and USB0 root INI. The receiver remains ready.':'';
  $('stream360-start').disabled=state.state!=='stopped';
  $('stream360-audio').disabled=state.state==='stopped';
  $('stream360-audio').textContent=stream360AudioContext?'Disable audio':'Enable audio';
  stream360AudioActive=live&&state.audio_enabled===true;
  if((state.state==='stopped'||state.audio_enabled===false)&&stream360AudioContext)closeStream360Audio();
  $('stream360-prepare').disabled=!live||state.safe_to_unload||state.preparing_unload;
  $('stream360-unload').disabled=state.state==='stopped'||!state.safe_to_unload||Boolean(state.unload_uncertain);
  $('stream360-clear').hidden=!state.unload_uncertain;
  $('stream360-clear').disabled=!connected;
  $('stream360-stop').disabled=state.state==='stopped'||live&&!state.safe_to_unload;
  $('stream360-ip').disabled=state.state!=='stopped';
  $('stream360-listening').hidden=!listening||state.safe_to_unload;
  stream360FrameActive=live&&state.video_codec==='jpeg'&&state.browser_frame_available;
  if(!live){
    $('stream360-preview').src='';
    $('stream360-preview').hidden=true;
    $('stream360-preview-message').textContent=listening?'Waiting for the console stream.':'Start the receiver, then load an inspected 360Stream XEX to view JPEG video.';
  }else if(state.video_codec==='i420'){
    $('stream360-preview').src='';
    $('stream360-preview').hidden=true;
    $('stream360-preview-message').textContent='Raw I420 video is arriving. Browser output for this mode is pending.';
  }else if(!state.browser_frame_available){
    $('stream360-preview-message').textContent='Waiting for a browser-ready JPEG frame.';
  }
}
async function refreshStream360(){
  if(!connected||stream360Polling)return;
  if(!$('stream360-ip').value&&/^\d{1,3}(?:\.\d{1,3}){3}$/.test($('target').value.trim()))$('stream360-ip').value=$('target').value.trim();
  stream360Polling=true;
  try{renderStream360(await api('stream360/status'));}
  finally{stream360Polling=false;}
}
async function refreshStream360Frame(){
  if(!stream360FrameActive||stream360FrameBusy||busy||document.hidden||$('stream360').hidden||Date.now()<stream360FrameRetry)return;
  stream360FrameBusy=true;
  try{
    const frame=await api('stream360/frame',{after:stream360FrameSequence});
    if(frame.jpeg&&frame.sequence>stream360FrameSequence){
      stream360FrameSequence=frame.sequence;
      $('stream360-preview').src='data:image/jpeg;base64,'+frame.jpeg;
      $('stream360-preview').hidden=false;
      $('stream360-preview-message').textContent='Live JPEG preview.';
    }
    stream360FrameRetry=0;
  }catch(error){
    stream360FrameRetry=Date.now()+1500;
    $('stream360-error').textContent=error.message;
  }finally{stream360FrameBusy=false;}
}
function closeStream360Audio(){
  const context=stream360AudioContext;stream360AudioContext=null;stream360AudioActive=false;stream360AudioNext=0;
  if(context)context.close().catch(()=>{});
  $('stream360-audio').textContent='Enable audio';
}
function playStream360Audio(packet){
  const context=stream360AudioContext,rate=packet.rate,bits=packet.bits;
  if(!context||![12000,24000,44100,48000].includes(rate)||![8,16].includes(bits))return;
  const bytes=atob(packet.pcm),stride=bits===16?4:2;
  if(!bytes.length||bytes.length%stride)return;
  const frames=bytes.length/stride,buffer=context.createBuffer(2,frames,rate);
  const left=buffer.getChannelData(0),right=buffer.getChannelData(1);
  for(let i=0;i<frames;i++){
    if(bits===8){left[i]=(bytes.charCodeAt(i*2)-128)/128;right[i]=(bytes.charCodeAt(i*2+1)-128)/128;}
    else{
      const offset=i*4;
      const l=bytes.charCodeAt(offset)|(bytes.charCodeAt(offset+1)<<8);
      const r=bytes.charCodeAt(offset+2)|(bytes.charCodeAt(offset+3)<<8);
      left[i]=(l>32767?l-65536:l)/32768;right[i]=(r>32767?r-65536:r)/32768;
    }
  }
  if(stream360AudioNext>context.currentTime+0.25)return;
  if(stream360AudioNext<context.currentTime)stream360AudioNext=context.currentTime+0.02;
  const source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);
  source.start(stream360AudioNext);stream360AudioNext+=frames/rate;
}
async function refreshStream360Audio(){
  if(!stream360AudioContext||!stream360AudioActive||stream360AudioBusy||document.hidden||$('stream360').hidden)return;
  stream360AudioBusy=true;
  try{
    const result=await api('stream360/audio',{after:stream360AudioSequence});
    for(const packet of result.packets||[])playStream360Audio(packet);
    stream360AudioSequence=result.sequence;
  }catch(error){$('stream360-error').textContent=error.message;}
  finally{stream360AudioBusy=false;}
}
$('stream360-audio').onclick=()=>task(async()=>{
  if(stream360AudioContext){await api('stream360/audio-enable',{enabled:false});closeStream360Audio();return;}
  const Audio=window.AudioContext||window.webkitAudioContext;
  if(!Audio)throw Error('This browser cannot play console audio.');
  const context=new Audio();
  try{await context.resume();const state=await api('stream360/audio-enable',{enabled:true});stream360AudioContext=context;stream360AudioSequence=0;renderStream360(state);}
  catch(error){await context.close();throw error;}
});
$('stream360-start').onclick=()=>task(async()=>{
  if(!connected)throw Error('Connect Neighborhood to the console first.');
  const state=await api('stream360/start',{console_ip:$('stream360-ip').value.trim()});
  renderStream360(state);
});
$('stream360-prepare').onclick=()=>task(async()=>renderStream360(await api('stream360/prepare-unload')));
$('stream360-open-plugins').onclick=()=>openWorkspaceView('plugins');
$('stream360-unload').onclick=()=>task(async()=>{const result=await api('plugins/unload',{name:'Xbox360Stream.xex',confirmed:true});notice(result.name+' unloaded.');renderStream360(await api('stream360/status'));});
$('stream360-clear').onclick=()=>document.querySelector('[data-console-power="cold"]').click();
$('stream360-stop').onclick=()=>task(async()=>{renderStream360(await api('stream360/stop'));closeStream360Audio();});
$('stream360-refresh').onclick=()=>task(refreshStream360);
setInterval(()=>{if(connected&&!busy&&!document.hidden&&!$('stream360').hidden)refreshStream360().catch(error=>{$('stream360-error').textContent=error.message;});},1500);
setInterval(()=>{if(connected)refreshStream360Frame();},125);
setInterval(()=>{if(connected)refreshStream360Audio();},100);
