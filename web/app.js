import {getLocation} from './location.js';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let state = {records: [], preferences: {}, services: {}};
let currentTab = 'nearby', selectedBrew = '冰美式', center = null, recordLocation = null, photoData = null, cafes = [];
const brewDescriptions = {'冰美式':'日常的清醒','手冲':'留一点慢时间','热美式':'热饮也合适','冷萃':'换个口味试试','意式浓缩':'浓缩的一杯'};
const preferenceLabels = {any:'黑咖、奶咖都可以',black:'只喝黑咖',milk:'只喝奶咖'};
let draftBrews = [], draftCategories = {};
const searchLabels={nearby:'就近原则',taste:'口味原则',destination:'想去哪就去哪'};
const searchDescriptions={nearby:'先看距离，结果不足时再向外找，口味作为参考。',taste:'先看有依据的口味匹配，距离只作参考。可以从已有记录里找，也可以选地点扩展查询。',destination:'你来定城市和目的地，围绕那里找咖啡。无需获取当前位置。'};
let resultMeta={};
const searchMode=()=>$('#search-mode').value;
function categoryOf(name, categories=state.preferences.brew_categories||{}) { return state.brew_catalog?.[name] || categories[name] || 'unknown'; }
function recommendationBrews() { const preference=state.preferences.coffee_preference||'any';return (state.preferences.brews||[]).filter(b=>preference==='any'||categoryOf(b)===preference); }
const esc = v => String(v ?? '').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const formatTags = values => (values || []).map(v => `<span>${esc(v)}</span>`).join('');
const localDate = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0,10);
function status(id, message, error=false) { const el = $(id); el.textContent=message; el.classList.toggle('error',error); }
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,3500); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {credentials:'same-origin'} : {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Coffee-Client':'web-v1'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作未完成，请重试');
  return result;
}
function tab(name) { currentTab=name; $$('.view').forEach(e=>e.hidden=e.id!==name); $$('[data-tab]').forEach(e=>e.setAttribute('aria-selected',String(e.dataset.tab===name))); if(name==='nearby'&&center&&cafes.length) searchNearby(); }
$$('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
$$('[data-action="record"]').forEach(b=>b.addEventListener('click',()=>tab('record')));
async function refresh() {
  state=await api('/api/state');
  $('#record-count').textContent=state.records.filter(r=>r.kind==='tasting').length;
  $('#taste-tags').innerHTML=formatTags([...(state.preferences.flavors||[]),preferenceLabels[state.preferences.coffee_preference||'any']]);
  $('#intro-tags').innerHTML=formatTags([...(state.preferences.brews||[]).slice(0,3),`${state.preferences.city} · ${state.preferences.area}`]);
  renderBrewTypes();
  if(!$('#search-city').value) $('#search-city').value=state.preferences.city||'';
  syncSearchMode();
  renderHistory();
  if(!state.services.maps) status('#location-status','地图服务尚未配置。现在可以先记录和整理口味，配置后再查附近店铺。');
  if(!state.services.vision) status('#photo-status','照片识别尚未配置，可先看着照片手动填写。');
}
function syncKind() {
  const menu=$('#kind').value==='menu'; $('#tasting-fields').hidden=menu;
  $('#source-required').hidden=!menu; $('#source_note').required=menu; $('#cafe').required=menu;
  if(menu) $('#record-form details').open=true;
}
$('#kind').addEventListener('change',syncKind);
function resetForm() { $('#record-form').reset(); syncBrewOptions(); $('#observed_on').value=localDate(); $('#observed_on').max=localDate(); $('#form-title').textContent='记住这一杯。'; recordLocation=null; status('#save-status',''); syncKind(); }
$('#reset-record').addEventListener('click',resetForm);
$('#record-form').addEventListener('submit',async e=>{
  e.preventDefault(); const button=$('#save-record'); button.disabled=true;
  const data=Object.fromEntries(new FormData(e.target)); data.location=recordLocation;
  data.brew_category=categoryOf(data.brew);
  try { await api('/api/records',data); await refresh(); resetForm(); toast('已保存。给下一杯多一点依据。'); tab('history'); }
  catch(error) { status('#save-status',error.message,true); }
  finally { button.disabled=false; }
});
function editRecord(id) {
  const r=state.records.find(x=>x.id===id); if(!r) return;
  resetForm();
  syncBrewOptions(r.brew);
  for(const [key,value] of Object.entries(r)) {
    const field=$('#record-form').elements.namedItem(key); if(!field) continue;
    if(key==='reaction') field.value=value; else field.value=Array.isArray(value)?value.join('、'):value??'';
  }
  recordLocation=r.location; $('#form-title').textContent='修改这条记录。'; syncKind(); tab('record'); window.scrollTo({top:0,behavior:'smooth'});
}
function renderHistory() {
  const query=$('#filter-text').value.trim().toLowerCase(); const brew=$('#filter-brew').value, reaction=$('#filter-reaction').value, roast=$('#filter-roast').value;
  const rows=state.records.filter(r=>(!brew||r.brew===brew)&&(!reaction||(r.kind==='tasting'&&r.reaction===reaction))&&(!roast||r.roast===roast)&&(!query||[r.product,r.bean,r.cafe,r.address,r.note,r.label_flavors.join(' '),r.tasted_flavors.join(' ')].join(' ').toLowerCase().includes(query)));
  const reactions={like:'♡ 喜欢',neutral:'还说不准',dislike:'不太喜欢'};
  $('#history-results').innerHTML=rows.length?rows.map(r=>`<article class="journal-card"><div class="card-head"><div><small>${esc(r.observed_on)} · ${r.kind==='menu'?'豆单资料':esc(r.brew)}</small><h3>${esc(r.product)}</h3><small>${esc(r.cafe||'未填写店铺')}${r.bean?' · '+esc(r.bean):''}</small></div><span class="pill ${esc(r.reaction)}">${r.kind==='menu'?'待尝试':reactions[r.reaction]}</span></div><div class="tags">${formatTags([r.roast,...r.label_flavors])}</div>${r.tasted_flavors.length?`<p>实际喝到：${esc(r.tasted_flavors.join('、'))}</p>`:''}${r.note?`<p>${esc(r.note)}</p>`:''}${r.source_note?`<p class="hint">来源：${esc(r.source_note)}</p>`:''}<div class="card-actions"><button class="quiet" data-edit="${r.id}">修改记录</button><button class="quiet danger" data-delete="${r.id}">删除</button></div></article>`).join(''):`<div class="empty"><span class="empty-mark">◡</span><h3>${state.records.length?'还没有符合筛选条件的记录':'你的第一杯，值得被记住'}</h3><p>${state.records.length?'换个关键词或筛选条件试试。':'从店名、喝了什么和喜不喜欢开始。'}</p></div>`;
  $$('[data-edit]').forEach(b=>b.onclick=()=>editRecord(b.dataset.edit));
  $$('[data-delete]').forEach(b=>b.onclick=async()=>{
    if(!confirm('删除这条记录？此操作无法撤销。')) return;
    try{await api('/api/delete',{id:b.dataset.delete});await refresh();toast('记录已删除');}catch(e){toast(e.message);}
  });
}
['#filter-text','#filter-brew','#filter-reaction','#filter-roast'].forEach(id=>$(id).addEventListener('input',renderHistory));
function syncBrewOptions(extraBrew='') {
  const favorites=state.preferences.brews||[], select=$('#brew'), previous=select.value;
  const editing=state.records.find(r=>r.id===$('#record-form').elements.id.value);
  const choices=[...new Set([...favorites,...(extraBrew?[extraBrew]:[]),...(editing?[editing.brew]:[])])];
  select.innerHTML=choices.length?choices.map(b=>`<option value="${esc(b)}">${esc(b)}</option>`).join(''):'<option value="">请先添加咖啡类型</option>';
  if(choices.includes(previous)) select.value=previous;
  const filter=$('#filter-brew'), oldFilter=filter.value;
  filter.innerHTML='<option value="">所有饮品</option>'+[...new Set([...favorites,...state.records.map(r=>r.brew)])].map(b=>`<option value="${esc(b)}">${esc(b)}</option>`).join('');
  filter.value=[...filter.options].some(o=>o.value===oldFilter)?oldFilter:'';
}
function renderBrewTypes() {
  const brews=recommendationBrews();
  if(!brews.includes(selectedBrew)) selectedBrew=brews[0]||'';
  $('#brew-choice').innerHTML=brews.length?brews.map(b=>`<button type="button" class="${b===selectedBrew?'selected':''}" data-brew="${esc(b)}" aria-pressed="${b===selectedBrew}"><strong>${esc(b)}</strong><small>${esc(brewDescriptions[b]||(categoryOf(b)==='milk'?'我的奶咖选择':'我的常喝类型'))}</small></button>`).join(''):`<p class="hint">${state.preferences.brews?.length?'当前常喝类型没有符合饮品偏好的选项。请在「管理类型」中添加对应类型，或在「我的口味」中调整偏好。':'还没有常喝的类型，点击「管理类型」添加。'}</p>`;
  $$('[data-brew]').forEach(b=>b.onclick=()=>{selectedBrew=b.dataset.brew;renderBrewTypes();if(center||searchMode()==='taste')searchNearby();});
  $('#locate').disabled=!brews.length;$('#landmark-form button').disabled=!brews.length;
  $('#taste-search').disabled=!brews.length;
  syncBrewOptions();
}
function renderBrewDraft() {
  $('#brew-draft-count').textContent=`${draftBrews.length} / 20`;
  $('#my-brews').innerHTML=draftBrews.length?draftBrews.map((b,i)=>`<div class="brew-item"><button type="button" class="brew-chip" data-remove-brew="${i}" aria-label="移除 ${esc(b)}">${esc(b)} <span aria-hidden="true">×</span></button>${state.brew_catalog?.[b]?`<small>${categoryOf(b,draftCategories)==='milk'?'奶咖':'黑咖'}</small>`:`<select data-category-brew="${i}" aria-label="${esc(b)}的分类"><option value="unknown">待分类</option><option value="black" ${draftCategories[b]==='black'?'selected':''}>黑咖</option><option value="milk" ${draftCategories[b]==='milk'?'selected':''}>奶咖</option></select>`}</div>`).join(''):'<p class="hint">从下方选择，或输入自己的类型。</p>';
  $('#brew-suggestions').innerHTML=['black','milk'].map(category=>`<div class="brew-group"><p>${category==='black'?'黑咖':'奶咖'}</p><div class="brew-suggestions">${Object.entries(state.brew_catalog||{}).filter(([,c])=>c===category).map(([b])=>`<button type="button" class="${draftBrews.includes(b)?'selected':''}" aria-pressed="${draftBrews.includes(b)}" data-suggest-brew="${esc(b)}">${draftBrews.includes(b)?'✓ ': '＋ '}${esc(b)}</button>`).join('')}</div></div>`).join('');
  $$('[data-remove-brew]').forEach(b=>b.onclick=()=>{draftBrews.splice(Number(b.dataset.removeBrew),1);renderBrewDraft();});
  $$('[data-suggest-brew]').forEach(b=>b.onclick=()=>{const name=b.dataset.suggestBrew;if(draftBrews.includes(name)){draftBrews=draftBrews.filter(x=>x!==name);renderBrewDraft();}else addDraftBrew(name);});
  $$('[data-category-brew]').forEach(s=>s.onchange=()=>{draftCategories[draftBrews[Number(s.dataset.categoryBrew)]]=s.value;});
}
function addDraftBrew(name) {
  name=name.trim();
  if(!name||name.length>24){status('#brews-status','请填写 1–24 个字的咖啡类型。',true);return;}
  if(draftBrews.includes(name)){status('#brews-status','这个类型已经在常喝列表里了。');return;}
  if(draftBrews.length>=20){status('#brews-status','最多保存 20 个类型，可以先移除不常喝的。',true);return;}
  const category=state.brew_catalog?.[name]||$('#custom-category').value;
  if(!category){status('#brews-status','请为自定义类型选择「黑咖」或「奶咖」。',true);return;}
  draftCategories[name]=category;draftBrews.push(name);$('#custom-brew').value='';status('#brews-status','');renderBrewDraft();
}
$$('[data-manage-brews]').forEach(b=>b.onclick=()=>{draftBrews=[...(state.preferences.brews||[])];draftCategories={...(state.preferences.brew_categories||{})};$('#custom-brew').value='';$('#custom-category').value=state.preferences.coffee_preference==='milk'?'milk':state.preferences.coffee_preference==='black'?'black':'';status('#brews-status','');renderBrewDraft();$('#brews-dialog').showModal();});
$('#add-brew').onclick=()=>addDraftBrew($('#custom-brew').value);
$('#custom-brew').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();addDraftBrew(e.target.value);}});
$('#brews-close').onclick=()=>$('#brews-dialog').close();
$('#brews-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const pending=$('#custom-brew').value.trim();
  if(pending&&!draftBrews.includes(pending)){const count=draftBrews.length;addDraftBrew(pending);if(draftBrews.length===count)return;}
  const button=$('#save-brews');button.disabled=true;
  try{
    await api('/api/preferences',{...state.preferences,brews:draftBrews,brew_categories:draftCategories});
    ++searchVersion;await refresh();$('#brews-dialog').close();toast('常喝的咖啡类型已保存');
    cafes=[];$('#nearby-results').innerHTML='<div class="empty"><span class="empty-mark">⌖</span><h3>按新的口味，找下一杯</h3><p>选择类型后，使用当前位置或手动选择地点。</p></div>';
    if((center||searchMode()==='taste')&&selectedBrew)searchNearby();
  }catch(error){status('#brews-status',error.message,true);}finally{button.disabled=false;}
});
function syncSearchMode() {
  const mode=searchMode(), destination=mode==='destination';
  $('#mode-description').textContent=searchDescriptions[mode];
  $('#locate').hidden=destination;$('#location-hint').hidden=destination;
  $('#taste-search').hidden=mode!=='taste';
  $('#landmark-label').textContent=destination?'想去的商圈、地铁站或地标':'商圈、地铁站或地标';
  $('#landmark-form button').textContent=destination?'去这里找':'查找';
}
$('#search-mode').addEventListener('change',()=>{
  ++searchVersion;const mode=searchMode();
  if(mode==='destination')center=null;
  cafes=[];$('#place-choices').replaceChildren();syncSearchMode();
  $('#nearby-results').innerHTML='<div class="empty"><span class="empty-mark">⌖</span><h3>'+esc(mode==='destination'?'下一站，想去哪里？':'用喜欢的方式，找下一杯')+'</h3><p>'+esc(mode==='destination'?'输入想去的城市和地标，再选择具体地点。':'选一个地点，或按口味看看已有记录。')+'</p></div>';
  status('#location-status','');
  if(mode==='destination')$('#landmark').focus();
  else if(selectedBrew&&(mode==='taste'||center))searchNearby(mode==='taste');
});
$('#taste-search').onclick=()=>searchNearby(true);
function queryData(historyOnly=false) {return {brew:selectedBrew,mode:searchMode(),city:$('#search-city').value.trim(),...(!historyOnly&&center?center:{})};}
let searchVersion=0;
async function searchNearby(historyOnly=false) {
  if(!selectedBrew){status('#location-status','请先在「管理类型」中添加常喝的咖啡。',true);return;}
  const version=++searchVersion;
  status('#location-status','正在查找附近店铺……'); $('#place-choices').replaceChildren();
  try {
    const result=await api('/api/nearby',queryData(historyOnly)); if(version!==searchVersion)return;
    if(result.places) {
      if(!result.places.length) {status('#location-status','没有找到这个地点，试试更具体的名称。',true);return;}
      status('#location-status','请选择你想搜索的具体地点：');
      $('#place-choices').innerHTML=result.places.map((p,i)=>`<button class="places-button" data-place="${i}"><strong>${esc(p.name)}</strong><small>${esc(p.address)}</small></button>`).join('');
      $$('[data-place]').forEach(b=>b.onclick=()=>{const p=result.places[Number(b.dataset.place)]; center={location:p.location,center_label:p.name,source:searchMode()==='destination'?'destination':'manual'}; $('#landmark').value=p.name; searchNearby();});
      return;
    }
    cafes=result.cafes;resultMeta=result;status('#location-status',`${searchLabels[result.mode]} · 找到 ${cafes.length} 家候选店铺`);renderCafes();
  } catch(e) {if(version===searchVersion){cafes=[];$('#nearby-results').innerHTML='<div class="empty"><h3>这次查询未完成</h3><p>可以稍后重试，或先记下喝过的一杯。</p></div>';status('#location-status',e.message,true);}}
}
$('#locate').addEventListener('click',async()=>{
  const button=$('#locate');button.disabled=true;status('#location-status','等待定位授权与结果……');
  try{const point=await getLocation();center={location:point,source:'current',center_label:'当前位置'};await searchNearby();}
  catch(e){status('#location-status',e.message,true);$('#landmark').focus();}
  finally{button.disabled=false;}
});
$('#landmark-form').addEventListener('submit',e=>{e.preventDefault();center={landmark:$('#landmark').value.trim()};searchNearby();});
$('#search-city').addEventListener('input',()=>{++searchVersion;center=null;$('#place-choices').replaceChildren();});
function distanceLabel(cafe) {const value=cafe.distance;return Number.isFinite(value)?(value>=1000?(value/1000).toFixed(1)+' km':value+' m'):'距离待确认';}
function renderCafes() {
  const count=cafes.filter(c=>c.products.length).length;
  $('#nearby-results').innerHTML=cafes.length?`<p class="results-head">${esc(resultMeta.scope_label||'候选店铺')} · ${cafes.length} 家店 · ${count} 家有产品资料<br>${esc(resultMeta.notice||'')}</p>`+cafes.map((c,i)=>`<article class="cafe-card"><div class="card-head"><div><small>${esc(c.source)}</small><h3>${esc(c.name)}</h3><small>${esc(c.address)}</small></div><span class="distance">${esc(distanceLabel(c))}</span></div>${c.products.length?`<div class="products">${c.products.map(p=>`<div class="product"><strong>${esc(p.product)}</strong><div class="tags">${formatTags([p.brew,p.roast,...p.flavors])}</div><p>${p.reasons.map(esc).join('；')}</p><p class="hint">${esc(p.observed_on)} · ${esc(p.source)}<br>${esc(p.availability)}</p><button class="quiet" data-try-record="${p.record_id}" data-cafe-index="${i}">喝完记一杯 ↗</button></div>`).join('')}</div>`:'<p class="no-menu">店铺候选 · 暂无可推荐的产品资料，尚不能判断是否符合你的口味。</p>'}<div class="card-actions"><button class="secondary" data-cafe="${i}" data-kind="tasting">在这家记一杯</button><button class="quiet" data-cafe="${i}" data-kind="menu">补充豆单</button></div></article>`).join(''):`<div class="empty"><h3>${resultMeta.mode==='taste'?'还没有可参考的店铺资料':'暂时没有找到合适的店铺'}</h3><p>${resultMeta.mode==='taste'?'先保存一条带店铺名称、地址或地图关联的饮用记录，也可以选择地点扩展查询。':'换一个地点或找店方式试试。'}</p><p class="hint">${esc(resultMeta.notice||'')}</p></div>`;
  $$('[data-cafe]').forEach(b=>b.onclick=()=>prefillCafe(cafes[Number(b.dataset.cafe)],b.dataset.kind));
  $$('[data-try-record]').forEach(b=>b.onclick=()=>{
    const record=state.records.find(r=>r.id===b.dataset.tryRecord); if(!record)return;
    prefillCafe(cafes[Number(b.dataset.cafeIndex)],'tasting');
    ['product','bean','roaster','origin','processing','batch','roast'].forEach(k=>$('#record-form').elements.namedItem(k).value=record[k]);
    $('#label_flavors').value=record.label_flavors.join('、');
  });
}
function prefillCafe(cafe,kind) { resetForm();$('#kind').value=kind;$('#cafe').value=cafe.name;$('#address').value=cafe.address;$('#brew').value=selectedBrew;$('#record-form').elements.provider_id.value=cafe.id;recordLocation=cafe.location;syncKind();tab('record'); }
// A manually changed branch cannot keep coordinates from the previous branch.
['#cafe','#address'].forEach(id=>$(id).addEventListener('input',()=>{recordLocation=null;$('#record-form').elements.provider_id.value='';}));
$('#photo').addEventListener('change',async e=>{
  const file=e.target.files[0];photoData=null;$('#extract').disabled=true;$('#photo-preview').hidden=true;$('#photo-items').replaceChildren();
  if(!file)return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>15*1024*1024){status('#photo-status','请选择小于 15 MB 的 JPG、PNG 或 WebP 图片。',true);return;}
  const url=URL.createObjectURL(file), image=new Image();
  image.onload=()=>{
    const scale=Math.min(1,1600/Math.max(image.width,image.height));const canvas=document.createElement('canvas');canvas.width=Math.round(image.width*scale);canvas.height=Math.round(image.height*scale);
    const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0,canvas.width,canvas.height);
    photoData=canvas.toDataURL('image/jpeg',.82);$('#photo-preview').src=photoData;$('#photo-preview').hidden=false;$('#extract').disabled=false;URL.revokeObjectURL(url);
    status('#photo-status',state.services.vision?'照片已准备好，点击识别后核对草稿。':'可以先看着照片填写，识别服务尚未配置。');
  };
  image.onerror=()=>{URL.revokeObjectURL(url);status('#photo-status','图片无法读取，请换一张照片。',true);};image.src=url;
});
$('#extract').addEventListener('click',async()=>{
  if(!photoData)return;$('#extract').disabled=true;status('#photo-status','正在识别，请稍候……');
  try{
    const result=await api('/api/extract',{image:photoData});status('#photo-status',result.uncertain);
    $('#photo-items').innerHTML=result.items.length?result.items.map((p,i)=>`<button type="button" class="photo-item" data-photo-item="${i}">${esc(p.product||p.bean||'未命名项目')} · 填入表单 ↗</button>`).join(''):'<p class="hint">没有识别出清晰的产品文字，可尝试更清楚的照片。</p>';
    $$('[data-photo-item]').forEach(b=>b.onclick=()=>{
      const item=result.items[Number(b.dataset.photoItem)];
      for(const [key,value] of Object.entries(item)){const field=$('#record-form').elements.namedItem(key);if(field&&value&&(Array.isArray(value)?value.length:true))field.value=Array.isArray(value)?value.join('、'):value;}
      if(!$('#source_note').value)$('#source_note').value='用户核对后的豆单 / 包装照片';toast('已填入草稿，请核对后保存');
    });
  }catch(e){status('#photo-status',e.message,true);}finally{$('#extract').disabled=false;}
});
$('#prefs-open').onclick=()=>{const f=$('#prefs-form');f.elements.flavors.value=state.preferences.flavors.join('、');f.elements.city.value=state.preferences.city;f.elements.area.value=state.preferences.area;f.elements.coffee_preference.value=state.preferences.coffee_preference||'any';$('#prefs-dialog').showModal();};
$('#prefs-close').onclick=()=>$('#prefs-dialog').close();
$('#prefs-form').addEventListener('submit',async e=>{e.preventDefault();const f=e.target;try{await api('/api/preferences',{...state.preferences,flavors:f.elements.flavors.value,city:f.elements.city.value,area:f.elements.area.value,coffee_preference:f.elements.coffee_preference.value});++searchVersion;await refresh();$('#prefs-dialog').close();toast('口味偏好已更新');cafes=[];$('#nearby-results').innerHTML='<div class="empty"><h3>按新的偏好，找下一杯</h3><p>选择喜欢的类型和地点后重新查询。</p></div>';if((center||searchMode()==='taste')&&selectedBrew)searchNearby();}catch(error){status('#prefs-status',error.message,true);}});
$('#export').onclick=async()=>{try{const data=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='coffee-buddy-'+localDate()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message);}};
$('#import-file').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>6*1024*1024)throw new Error('备份文件过大');const data=JSON.parse(await file.text());if(!confirm('将备份记录合并到当前记录中？相同编号的记录会更新，其他记录保留。'))return;const result=await api('/api/import',data);await refresh();toast(`已导入 ${result.count} 条记录`);}catch(error){toast(error.message);}finally{e.target.value='';}});
resetForm();
refresh().catch(e=>{status('#location-status','无法连接本地服务：'+e.message,true);toast('加载失败，请确认本地服务正在运行后刷新页面。');});
