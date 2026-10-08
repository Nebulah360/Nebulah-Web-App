'use strict';
async function refreshUsbInventory(){
  const host=$('usb-disks');host.replaceChildren();
  $('usb-status').textContent='Reading connected Windows USB disks…';
  try{
    const result=await api('usb/inventory');
    $('usb-status').textContent=result.disks.length===0?'No USB disk is currently reported by Windows.':
      result.disks.length+' USB '+(result.disks.length===1?'disk':'disks')+' reported by Windows.';
    for(const disk of result.disks){
      const card=document.createElement('article');card.className='usb-disk';
      const heading=document.createElement('h3');heading.textContent=disk.model+' · Disk '+disk.number;
      const meta=document.createElement('p');meta.className='small';
      meta.textContent=bytesLabel(disk.bytes)+' · '+disk.partition_style+' · '+disk.operational_status+
        (disk.read_only?' · Windows read-only':'')+(disk.system||disk.boot?' · System/boot disk':'');
      card.append(heading,meta);
      if(!disk.volumes.length){const empty=document.createElement('p');empty.textContent='No mounted volume reported.';card.append(empty);}
      for(const volume of disk.volumes){
        const row=document.createElement('div');row.className='usb-volume';
        const name=document.createElement('strong');name.textContent=volume.letter+' '+volume.label;
        const detail=document.createElement('small');detail.textContent=volume.filesystem+' · '+bytesLabel(volume.free_bytes)+' free of '+bytesLabel(volume.bytes)+' · '+volume.health;
        row.append(name,detail);card.append(row);
      }
      host.append(card);
    }
  }catch(error){$('usb-status').textContent=error.message||'Windows USB inventory unavailable.';throw error;}
}
$('usb-refresh').onclick=()=>task(refreshUsbInventory);
