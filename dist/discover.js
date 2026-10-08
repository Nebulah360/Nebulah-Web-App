'use strict';
let discoverReady=false,discoverOffset=0,discoverInstalls=[];
const discoverResults=$('discover-results'),discoverMore=$('discover-more');
const discoverSuggestTimers={},discoverSuggestGeneration={series:0,developer:0};
function discoverNameKey(name){return String(name||'').normalize('NFKD').toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ');}
function discoverMatches(name){const key=discoverNameKey(name);return key?discoverInstalls.filter(item=>discoverNameKey(item.name)===key):[];}
function discoverCover(id,size='t_cover_big'){
  return /^[A-Za-z0-9_]{1,64}$/.test(id||'')?'https://images.igdb.com/igdb/image/upload/'+size+'/'+id+'.png':'';
}
function discoverImage(item){
  const url=discoverCover(item.cover_id);
  if(!url){const placeholder=document.createElement('span');placeholder.className='discover-cover-empty';placeholder.textContent='No cover';return placeholder;}
  const image=document.createElement('img');image.src=url;image.alt='';image.loading='lazy';image.referrerPolicy='no-referrer';return image;
}
async function refreshDiscover(){
  const status=await api('discover/status');
  discoverReady=status.configured===true;
  $('discover-status').textContent=discoverReady?'IGDB ready. Search or browse Xbox 360 titles.':
    'IGDB needs a Twitch application. Set NEBULAH_IGDB_CLIENT_ID and NEBULAH_IGDB_CLIENT_SECRET on the bridge PC, then restart it.';
  if(connected){
    try{discoverInstalls=(await api('library/list',{view:'installs'})).items.filter(item=>item.categories?.includes('games')&&item.kind==='installation');}
    catch{discoverInstalls=[];}
  }else discoverInstalls=[];
  if(!discoverReady)return;
  if($('discover-genre').options.length===1){
    const filters=await api('discover/filters');
    for(const [field,select] of [['genres','discover-genre'],['themes','discover-theme'],['game_modes','discover-mode'],['age_rating_categories','discover-age']]){
      for(const item of filters[field]||[]){
        const option=document.createElement('option');option.value=item.id;option.textContent=item.name;
        $(select).append(option);
      }
    }
  }
  if(!discoverResults.children.length)await searchDiscover(false);
}
async function searchDiscover(more){
  if(!discoverReady)throw Error('Configure IGDB on the bridge PC first.');
  const offset=more?discoverOffset:0;
  $('discover-status').textContent='Searching IGDB…';
  const result=await api('discover/search',{query:$('discover-query').value.trim(),
    genre:Number($('discover-genre').value),theme:Number($('discover-theme').value),mode:Number($('discover-mode').value),
    age:Number($('discover-age').value),series:Number($('discover-series').value),developer:Number($('discover-developer').value),
    online_coop:$('discover-online-coop').checked,local_coop:$('discover-local-coop').checked,
    year_from:Number($('discover-year-from').value),year_to:Number($('discover-year-to').value),
    rating:Number($('discover-rating').value),offset});
  if(!more)discoverResults.replaceChildren();
  for(const item of result.items){
    const card=document.createElement('button');card.type='button';card.className='discover-card';
    const name=document.createElement('strong');name.textContent=item.name;
    const meta=document.createElement('small');
    meta.textContent=[item.release?new Date(item.release*1000).getUTCFullYear():null,
      item.rating!=null?Math.round(item.rating)+'/100':null,(item.genres||[]).join(', ')].filter(Boolean).join(' · ');
    card.append(discoverImage(item),name,meta);
    if(discoverMatches(item.name).length){const hint=document.createElement('small');hint.textContent='Possible match in your library';card.append(hint);}
    card.onclick=()=>task(()=>showDiscoverDetail(item.id));
    discoverResults.append(card);
  }
  discoverOffset=offset+result.items.length;
  discoverMore.hidden=result.items.length<20||discoverOffset>=500;
  $('discover-status').textContent=discoverOffset+' Xbox 360 '+(discoverOffset===1?'game':'games')+' shown from IGDB.';
}
async function showDiscoverDetail(id){
  const game=await api('discover/detail',{id});
  const host=$('discover-detail');host.replaceChildren();
  const heading=document.createElement('h2');heading.textContent=game.name;
  host.append(heading,discoverImage(game));
  const meta=document.createElement('p');meta.className='small';
  meta.textContent=[game.release?new Date(game.release*1000).getUTCFullYear():null,
    game.rating!=null?Math.round(game.rating)+'/100':null,
    ...(game.developers||[])].filter(Boolean).join(' · ');
  host.append(meta);
  const matches=discoverMatches(game.name);
  if(matches.length){
    const match=document.createElement('p');match.className='small';
    match.textContent=matches.length+' possible saved install'+(matches.length===1?'':'s')+' by name. Confirm the Title ID in Games; this is not a verified match.';
    const open=document.createElement('button');open.type='button';open.className='secondary';open.textContent='Find in Games';
    open.onclick=()=>{$('discover-detail-dialog').close();openWorkspaceView('games');gameLibraryQuery=matches[0].name;if(gameLibrarySearch){gameLibrarySearch.value=gameLibraryQuery;gameLibrarySearch.oninput();}};
    host.append(match,open);
  }
  for(const [label,content] of [['Genres',(game.genres||[]).join(', ')],['Themes',(game.themes||[]).join(', ')],
    ['Modes',(game.game_modes||[]).join(', ')],['Series',(game.series||[]).join(', ')],
    ['Age ratings',(game.age_ratings||[]).join(', ')],
    ['Co-op',game.coop?.online||game.coop?.local?[game.coop.online?'Online':null,game.coop.local?'Local':null].filter(Boolean).join(' and '):''],
    ['About',game.summary],['Story',game.storyline]]){
    if(!content)continue;
    const title=document.createElement('h3');title.textContent=label;
    const body=document.createElement('p');body.textContent=content;
    host.append(title,body);
  }
  $('discover-detail-dialog').showModal();
}
$('discover-form').onsubmit=event=>{event.preventDefault();task(()=>searchDiscover(false));};
discoverMore.onclick=()=>task(()=>searchDiscover(true));
for(const kind of ['series','developer']){
  const input=$('discover-'+kind+'-query'),select=$('discover-'+kind),placeholder=select.options?.[0]?.textContent||'Any '+kind;
  input.oninput=()=>{
    const generation=++discoverSuggestGeneration[kind],query=input.value.trim();
    clearTimeout(discoverSuggestTimers[kind]);
    select.replaceChildren(Object.assign(document.createElement('option'),{value:'0',textContent:placeholder}));
    if(!discoverReady||query.length<2)return;
    discoverSuggestTimers[kind]=setTimeout(async()=>{
      try{
        const result=await api('discover/suggest',{kind,query});
        if(generation!==discoverSuggestGeneration[kind])return;
        for(const item of result.items){select.append(Object.assign(document.createElement('option'),{value:item.id,textContent:item.name}));}
      }catch(error){if(generation===discoverSuggestGeneration[kind])$('discover-status').textContent=error.message;}
    },400);
  };
}
