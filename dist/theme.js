/* Local appearance preference only; no console data or tokens are persisted. */
'use strict';
const ThemeColor=(()=>{
  function parseHex(value){let s=String(value).trim().replace(/^#/,'');if(/^[\da-f]{3}$/i.test(s))s=s.split('').map(c=>c+c).join('');if(!/^[\da-f]{6}$/i.test(s))return null;return [0,2,4].map(i=>parseInt(s.slice(i,i+2),16));}
  function hex(rgb){return '#'+rgb.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('').toUpperCase();}
  function rgb(h,s,v){let c=v*s,x=c*(1-Math.abs((h/60)%2-1)),m=v-c;let a=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];return a.map(n=>Math.round((n+m)*255));}
  function hsv(a){let [r,g,b]=a.map(v=>v/255),hi=Math.max(r,g,b),lo=Math.min(r,g,b),d=hi-lo;let h=!d?0:hi===r?60*((g-b)/d%6):hi===g?60*((b-r)/d+2):60*((r-g)/d+4);return [(h+360)%360,hi?d/hi:0,hi];}
  function luminance(a){return a.map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);}
  function ink(a){return luminance(a)>.179?'#000000':'#FFFFFF';}
  function readable(a){let b=[...a];while((luminance(b)+.05)/(luminance([25,31,29])+.05)<4.5)b=b.map(v=>Math.min(255,v+8));return hex(b);}
  return {parseHex,hex,rgb,hsv,ink,readable};
})();
if(typeof module!=='undefined')module.exports=ThemeColor;
if(typeof document!=='undefined'){
  const el=id=>document.getElementById(id),canvas=el('color-wheel'),ctx=canvas.getContext('2d');let hsv=[0,0,1];
  function wheel(){const n=canvas.width,r=n/2,img=ctx.createImageData(n,n);for(let y=0;y<n;y++)for(let x=0;x<n;x++){let dx=x-r,dy=y-r,s=Math.hypot(dx,dy)/(r-5),i=(y*n+x)*4;if(s>1)continue;const rgb=ThemeColor.rgb((Math.atan2(dy,dx)*180/Math.PI+360)%360,s,hsv[2]);img.data.set([...rgb,255],i);}ctx.putImageData(img,0,0);const a=hsv[0]*Math.PI/180,x=r+Math.cos(a)*hsv[1]*(r-5),y=r+Math.sin(a)*hsv[1]*(r-5);ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.lineWidth=4;ctx.strokeStyle='#000';ctx.stroke();ctx.lineWidth=2;ctx.strokeStyle='#fff';ctx.stroke();canvas.setAttribute('aria-valuenow',Math.round(hsv[0]));canvas.setAttribute('aria-valuetext',`Hue ${Math.round(hsv[0])} degrees, saturation ${Math.round(hsv[1]*100)} percent`);}
  function apply(rgb,fromWheel=false,save=true){const color=ThemeColor.hex(rgb);if(!fromWheel)hsv=ThemeColor.hsv(rgb);const style=document.documentElement.style;style.setProperty('--accent',color);style.setProperty('--accent-ink',ThemeColor.ink(rgb));style.setProperty('--accent-text',ThemeColor.readable(rgb));el('accent-hex').value=color;el('accent-hex').setCustomValidity('');['r','g','b'].forEach((k,i)=>{el('accent-'+k).value=rgb[i];el('accent-'+k).setCustomValidity('')});el('brightness').value=Math.round(hsv[2]*100);el('color-value').textContent=color;el('color-error').textContent='';wheel();if(save)try{localStorage.setItem('nebulah.accent',color)}catch{el('color-error').textContent='Color applied for this session. Browser storage is unavailable.'}}
  function fromWheel(){apply(ThemeColor.rgb(...hsv),true)}
  function point(e){const rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left)*canvas.width/rect.width-canvas.width/2,y=(e.clientY-rect.top)*canvas.height/rect.height-canvas.height/2;hsv[0]=(Math.atan2(y,x)*180/Math.PI+360)%360;hsv[1]=Math.min(1,Math.hypot(x,y)/(canvas.width/2-5));fromWheel()}
  canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);point(e)};canvas.onpointermove=e=>{if(canvas.hasPointerCapture(e.pointerId))point(e)};canvas.onpointerup=e=>canvas.releasePointerCapture(e.pointerId);
  canvas.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();const n=e.shiftKey?10:1;if(e.key==='ArrowLeft')hsv[0]=(hsv[0]-n+360)%360;if(e.key==='ArrowRight')hsv[0]=(hsv[0]+n)%360;if(e.key==='ArrowUp')hsv[1]=Math.min(1,hsv[1]+n/100);if(e.key==='ArrowDown')hsv[1]=Math.max(0,hsv[1]-n/100);fromWheel()};
  el('brightness').oninput=e=>{hsv[2]=Number(e.target.value)/100;fromWheel()};
  el('accent-hex').oninput=e=>{const rgb=ThemeColor.parseHex(e.target.value);e.target.setCustomValidity(rgb?'':'Enter 3 or 6 hexadecimal digits.');el('color-error').textContent=rgb?'':'Enter a HEX value such as #C4F581.';if(rgb){const typed=e.target.value;apply(rgb);e.target.value=typed}};
  for(const k of ['r','g','b'])el('accent-'+k).oninput=()=>{const inputs=['r','g','b'].map(k=>el('accent-'+k));const values=inputs.map(e=>Number(e.value));if(inputs.some(e=>e.value===''||!e.checkValidity())||values.some(v=>!Number.isInteger(v)||v<0||v>255)){el('color-error').textContent='RGB channels must be whole numbers from 0 to 255.';return}apply(values)};
  el('appearance-open').onclick=()=>el('appearance-dialog').showModal();el('accent-reset').onclick=()=>apply([196,245,129]);
  let initial=null;try{initial=ThemeColor.parseHex(localStorage.getItem('nebulah.accent')||'')}catch{}apply(initial||[196,245,129],false,false);
}
