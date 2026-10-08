'use strict';
// Local, bounded XDVDFS/XEX2 header inspection. No console or bridge file read.
const localIso=(()=>{
  const sector=2048, magic='MICROSOFT*XBOX*MEDIA';
  const partitions=[0,0x18300000,0x0FD90000,0x02080000];
  const hex=value=>value.toString(16).toUpperCase().padStart(8,'0');
  async function read(file,offset,length){
    if(!Number.isSafeInteger(offset)||!Number.isSafeInteger(length)||offset<0||length<0||offset+length>file.size)
      throw Error('Disc image ends before the requested header.');
    const bytes=new Uint8Array(await file.slice(offset,offset+length).arrayBuffer());
    if(bytes.length!==length)throw Error('Disc image read was incomplete.');
    return bytes;
  }
  function word(bytes,offset,little=false){return new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength).getUint32(offset,little);}
  function entry(table){
    const view=new DataView(table.buffer,table.byteOffset,table.byteLength),stack=[0],seen=new Set();
    let originalXbox=false;
    while(stack.length){
      const offset=stack.pop();
      if(seen.has(offset))continue;
      if(seen.size>=4096||offset+14>table.length)throw Error('Disc directory table is malformed or too large.');
      seen.add(offset);
      const left=view.getUint16(offset,true),right=view.getUint16(offset+2,true);
      const nameLength=table[offset+13];
      if(offset+14+nameLength>table.length)throw Error('Disc directory entry is incomplete.');
      const name=String.fromCharCode(...table.subarray(offset+14,offset+14+nameLength)).toLowerCase();
      if(name==='default.xex'&&!(table[offset+12]&0x10))
        return {sector:view.getUint32(offset+4,true),size:view.getUint32(offset+8,true)};
      if(name==='default.xbe')originalXbox=true;
      for(const child of [left,right])if(child&&child!==0xffff)stack.push(child*4);
    }
    throw Error(originalXbox?'Original Xbox disc image; no Xbox 360 default.xex.':'Disc has no default.xex in its root directory.');
  }
  function xex(bytes){
    if(String.fromCharCode(...bytes.subarray(0,4))!=='XEX2'||bytes.length<24)throw Error('Disc launcher has no XEX2 header.');
    const count=word(bytes,0x14);
    if(count>128||0x18+count*8>bytes.length)throw Error('Disc launcher optional headers are incomplete.');
    for(let i=0;i<count;i++){
      const at=0x18+i*8;
      if(word(bytes,at)!==0x00040006)continue;
      const info=word(bytes,at+4);
      if(info+20>bytes.length)throw Error('Disc launcher execution info exceeds the 64 KiB read limit.');
      return {mediaId:hex(word(bytes,info)),version:hex(word(bytes,info+4)),baseVersion:hex(word(bytes,info+8)),
        titleId:hex(word(bytes,info+12)),disc:bytes[info+18],discCount:bytes[info+19]};
    }
    throw Error('Disc launcher has no execution info.');
  }
  async function inspect(file){
    if(!file||!Number.isSafeInteger(file.size)||file.size<sector*33)throw Error('Choose a complete local Xbox 360 disc image.');
    for(const base of partitions){
      const at=base+32*sector;
      if(at+28>file.size)continue;
      const descriptor=await read(file,at,28);
      if(String.fromCharCode(...descriptor.subarray(0,20))!==magic)continue;
      const rootSector=word(descriptor,20,true),rootSize=word(descriptor,24,true);
      if(!rootSize||rootSize>1024*1024)throw Error('Disc root table exceeds the 1 MiB inspection limit.');
      const root=await read(file,base+rootSector*sector,rootSize);
      const launcher=entry(root);
      if(launcher.size<24)throw Error('Disc launcher is too small for XEX2 metadata.');
      const header=await read(file,base+launcher.sector*sector,Math.min(launcher.size,65536));
      return {fileName:file.name||'Local image',imageSize:file.size,partitionOffset:base,launcherSize:launcher.size,...xex(header)};
    }
    throw Error('No supported Xbox 360 disc partition was found.');
  }
  return {inspect};
})();

if(typeof document!=='undefined'){
  const input=document.getElementById('iso-file'),button=document.getElementById('iso-inspect'),output=document.getElementById('iso-result');
  input.onchange=()=>{output.textContent='No image inspected.';};
  button.onclick=async()=>{
    const file=input.files?.[0];if(!file){output.textContent='Choose a local ISO file first.';return;}
    button.disabled=true;output.textContent='Reading disc headers locally…';
    try{
      const result=await localIso.inspect(file);
      output.textContent=result.fileName+' · '+(result.imageSize/1073741824).toFixed(2)+' GiB · Title ID '+result.titleId+
        ' · Media ID '+result.mediaId+' · disc '+result.disc+'/'+result.discCount+
        ' · XEX version '+result.version+' · partition 0x'+result.partitionOffset.toString(16).toUpperCase()+
        '. Header data only; image integrity and console compatibility are unverified.';
    }catch(error){output.textContent='Could not identify image: '+error.message;}
    finally{button.disabled=false;}
  };
}
