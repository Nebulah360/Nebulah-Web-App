'use strict';
// Dependency-free DOM harness: exercise the shipped app handlers, not a second
// implementation of candidate generation. Real browser/console QA is separate.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../dist/app.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../dist/index.html'),'utf8');
const measured={file:'unknown.xex',inspection_id:'opaque-snapshot',plugin:false,verification:{status:'unknown',label:'No reviewed baseline',actual_sha256:'a'.repeat(64),actual_size:600,metadata:{title_id:'415608C3',media_id:'12345678',version:'00000001',base_version:'00000001'}}};
const candidate={id:'game-test',title:'Test game',provenance:'Synthetic bytes',filename:'unknown.xex',...measured.verification.metadata,sha256:'a'.repeat(64),size:600,state:'candidate',unmodified:false};

function harness(){
  const elements=new Map(),requests=[],downloads=[],blobs=[];
  class Element{
    constructor(tag='div'){this.tag=tag;this.hidden=false;this.value='';this.textContent='';this.children=[];this.listeners={};this.dataset={};this.open=false;this.classList={add(){},remove(){},toggle(){}};}
    append(...nodes){this.children.push(...nodes);}
    prepend(...nodes){this.children.unshift(...nodes);}
    replaceChildren(...nodes){this.children=nodes;}
    addEventListener(event,fn){this.listeners[event]=fn;}
    emit(event){this.listeners[event]?.();}
    showModal(){this.open=true;}
    close(){this.open=false;this.emit('close');}
    reset(){for(const id of ['game-candidate-title','game-candidate-provenance'])get(id).value='';}
    focus(){this.focused=true;}
    select(){this.selectionStart=0;this.selectionEnd=this.value.length;}
    click(){if(this.tag==='a')downloads.push({href:this.href,name:this.download});else this.onclick?.();}
    remove(){}
  }
  const get=id=>{
    assert.ok(html.includes('id="'+id+'"'),'Missing HTML element '+id);
    if(!elements.has(id))elements.set(id,new Element());
    return elements.get(id);
  };
  const context=vm.createContext({
    document:{getElementById:get,querySelectorAll:()=>[],addEventListener(){},createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),body:new Element('body')},
    window:{addEventListener(){}},navigator:{},Blob,AbortSignal,
    URL:{createObjectURL(blob){blobs.push(blob);return 'blob:synthetic';},revokeObjectURL(){}},
    setInterval(){},setTimeout(){},clearTimeout(){},
    fetch:async(url,options)=>{const request={action:url.slice(5),body:JSON.parse(options.body)};requests.push(request);return {ok:true,json:async()=>context.response(request)};},
    response:()=>({candidate}),measured,
  });
  vm.runInContext(app,context);
  const run=code=>vm.runInContext(code,context);
  run('connected=true; resetGameCandidate();');get('game-preview-dialog').showModal();
  async function settle(){for(let i=0;i<20&&run('busy');i++)await new Promise(resolve=>setImmediate(resolve));assert.equal(run('busy'),false);}
  function submit(){get('game-candidate-form').onsubmit({preventDefault(){}});}
  function fill(){get('game-candidate-title').value=candidate.title;get('game-candidate-provenance').value=candidate.provenance;}
  return {get,run,context,requests,downloads,blobs,submit,fill,settle};
}

test('unknown-file form requires user fields and sends only snapshot ID/title/provenance',async()=>{
  const h=harness();h.run('offerGameCandidate(measured)');
  assert.equal(h.get('game-candidate-title').value,'');
  assert.equal(h.get('game-candidate-form').hidden,false);
  h.submit();await h.settle();assert.deepEqual(h.requests,[]);
  h.fill();h.submit();await h.settle();
  assert.deepEqual(h.requests,[{action:'games/propose',body:{inspection_id:'opaque-snapshot',title:'Test game',provenance:'Synthetic bytes'}}]);
  assert.deepEqual(JSON.parse(h.get('game-candidate-json').value),candidate);
  assert.match(h.get('game-candidate-message').textContent,/Untrusted candidate/);
  assert.equal(h.context.measured.verification.status,'unknown');
});

test('copy/download preserve candidate JSON and clipboard failure selects manual fallback',async()=>{
  const h=harness();h.run('offerGameCandidate(measured)');h.fill();h.submit();await h.settle();
  let copied;h.context.navigator.clipboard={writeText:async text=>{copied=text;}};
  await h.get('game-candidate-copy').onclick();assert.equal(copied,h.get('game-candidate-json').value);
  h.get('game-candidate-download').onclick();
  assert.equal(h.downloads[0].name,'game-test.candidate.json');
  assert.equal(await h.blobs[0].text(),copied);
  delete h.context.navigator.clipboard;
  await h.get('game-candidate-copy').onclick();
  assert.equal(h.get('game-candidate-json').selectionEnd,copied.length);
  assert.match(h.get('game-candidate-message').textContent,/Copy the selected JSON manually/);
  assert.equal(h.requests.length,1);
});

test('demo and ineligible inspections cannot submit candidates',async()=>{
  const h=harness();h.run('demo=true; offerGameCandidate(measured)');
  assert.equal(h.get('game-candidate-form').hidden,true);
  h.fill();h.submit();await h.settle();assert.deepEqual(h.requests,[]);
  h.run('demo=false; offerGameCandidate({candidate_unavailable:"Missing metadata"})');
  assert.equal(h.get('game-candidate-form').hidden,true);
  assert.equal(h.get('game-candidate-help').textContent,'Missing metadata');
  h.submit();await h.settle();assert.deepEqual(h.requests,[]);
});

test('new inspection, edited fields, close and reconnect clear stale export state',async()=>{
  const h=harness();
  const generate=async()=>{h.run('offerGameCandidate(measured)');h.fill();h.submit();await h.settle();};
  await generate();h.get('game-candidate-title').emit('input');
  assert.equal(h.get('game-candidate-output').hidden,true);assert.equal(h.get('game-candidate-json').value,'');
  await generate();h.run('resetGameCandidate("Reading another file…")');
  assert.equal(h.get('game-candidate-title').value,'');assert.equal(h.get('game-candidate-output').hidden,true);
  await generate();h.run('resetGames()');
  assert.equal(h.get('game-candidate-json').value,'');assert.equal(h.get('game-candidate-form').hidden,true);
  assert.equal(h.run('candidateInspection'),null);
});

test('late proposal response after dismissal cannot restore an export',async()=>{
  const h=harness();let resolve;
  h.context.response=()=>new Promise(r=>resolve=r);
  h.run('offerGameCandidate(measured)');h.fill();h.submit();
  await new Promise(r=>setImmediate(r));
  h.get('game-preview-dialog').close();resolve({candidate});await h.settle();
  assert.equal(h.get('game-candidate-output').hidden,true);
  assert.equal(h.get('game-candidate-json').value,'');assert.equal(h.run('candidateExport'),null);
});

test('late inspection after preview closes does not offer a candidate',async()=>{
  const h=harness();let resolve;
  h.context.response=({action})=>action==='browse'?{files:[{name:'unknown.xex',directory:false}]}:new Promise(r=>resolve=r);
  const preview=h.run('previewGame({id:1,name:"Test",folder:"Test:\\\\",executable:"unknown.xex"})');
  await new Promise(r=>setImmediate(r));h.get('game-preview-dialog').close();resolve(measured);await preview;
  assert.equal(h.get('game-candidate-form').hidden,true);
  assert.equal(h.get('game-candidate-file').textContent,'');
});
