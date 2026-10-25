import {parseMenuText,draftsFromItems} from './menu-drafts.js';

export function initMenuBatch({getState,getContext,api,onSaved,toast,today}) {
  const $=selector=>document.querySelector(selector);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let drafts=[], context={}, initialized=false;
  const sourcePhotos=new Map();
  const dialog=$('#menu-batch-dialog');
  function message(text,error=false){$('#batch-status').textContent=text;$('#batch-status').classList.toggle('error',error);}
  function updateReviewCount(){
    const pending=drafts.filter(row=>!row.reviewed).length;
    $('#batch-review-count').textContent=drafts.length?`共 ${drafts.length} 款 · 待确认 ${pending} 款`:'';
    $('#batch-save').disabled=!drafts.length||pending>0;
  }
  function showPhoto(row,index){
    const image=sourcePhotos.get(row.id);if(!image)return;
    $('#batch-photo-reference').hidden=false;$('#batch-photo-reference').open=true;
    $('#batch-photo-image').src=image;$('#batch-photo-caption').textContent=`第 ${index+1} 款的来源照片；参考文字也可能有错，请以原图为准。`;
    $('#batch-photo-reference').scrollIntoView({block:'nearest'});
  }
  function brewOptions(current=''){
    const state=getState(), names=[...new Set([...Object.keys(state.brew_catalog||{}),...(state.preferences.brews||[]),...drafts.map(d=>d.brew),current])].filter(Boolean);
    return '<option value="">请选择饮品类型</option>'+names.map(name=>`<option value="${esc(name)}" ${current===name?'selected':''}>${esc(name)}</option>`).join('');
  }
  function initialize(){
    if(initialized)return;
    context=getContext();
    const demo=getState().demo?.enabled?getState().records[0]:null;
    $('#batch-cafe').value=context.cafe||demo?.cafe||'';
    $('#batch-address').value=context.address||demo?.address||'';
    $('#batch-source').value=context.source_note||demo?.source_note||'';
    $('#batch-date').value=today();$('#batch-date').max=today();
    $('#batch-brew').innerHTML=brewOptions();
    initialized=true;
  }
  function render(){
    updateReviewCount();
    $('#batch-preview').innerHTML=drafts.map((row,index)=>{
      const badge=field=>(row.review_fields||[]).includes(field)?'<span class="review-badge" data-review-status>待核对</span>':'';
      const input=(field,label,max=160)=>`<div class="review-field ${(row.review_fields||[]).includes(field)?'needs-review':''}"><label for="menu-${row.id}-${field}">${label} ${badge(field)}</label><input id="menu-${row.id}-${field}" data-menu-id="${row.id}" data-menu-field="${field}" value="${esc(row[field])}" maxlength="${max}" ${field==='product'?'required':''}></div>`;
      const reference=row.source_text?`<details class="source-transcription"><summary>参考文字（仍需对照原图）</summary><p>${esc(row.source_text)}</p></details>`:'';
      const notes=(row.review_notes||[]).length?`<ul class="review-notes">${row.review_notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul>`:'';
      const photo=sourcePhotos.has(row.id)?`<button type="button" class="secondary" data-compare-photo="${row.id}">对照原图</button>`:'';
      return `<fieldset class="menu-draft"><legend>第 ${index+1} 款</legend><div class="draft-head"><span>核对产品资料</span><button type="button" class="quiet danger" data-remove-menu="${row.id}">移除此款</button></div>${photo}${notes}${reference}${input('product','产品名称 *')}<div class="field-row"><div class="review-field"><label for="menu-${row.id}-brew">饮品类型 * ${badge('brew')}</label><select id="menu-${row.id}-brew" data-menu-id="${row.id}" data-menu-field="brew" required>${brewOptions(row.brew)}</select></div><div class="review-field"><label for="menu-${row.id}-roast">烘焙深度 ${badge('roast')}</label><select id="menu-${row.id}-roast" data-menu-id="${row.id}" data-menu-field="roast">${['未知','浅烘','中浅烘','中烘','中深烘','深烘'].map(value=>`<option ${row.roast===value?'selected':''}>${value}</option>`).join('')}</select></div></div>${input('bean','豆子（不知道可留空）')}${input('label_flavors','标注风味（不知道可留空）',1500)}<details><summary>补充烘焙商、产地和批次</summary>${input('roaster','品牌 / 烘焙商')}${input('origin','产地')}${input('processing','处理方式')}${input('batch','批次 / 烘焙日期')}</details><label class="menu-reviewed"><input type="checkbox" data-menu-reviewed="${row.id}" ${row.reviewed?'checked':''} required>已对照并核对这一款</label></fieldset>`;
    }).join('');
    $('#batch-preview').querySelectorAll('[data-remove-menu]').forEach(button=>button.onclick=()=>{sourcePhotos.delete(button.dataset.removeMenu);drafts=drafts.filter(row=>row.id!==button.dataset.removeMenu);render();message(`当前保留 ${drafts.length} 款草稿，核对后再保存。`);});
    $('#batch-preview').querySelectorAll('[data-compare-photo]').forEach(button=>button.onclick=()=>{const index=drafts.findIndex(row=>row.id===button.dataset.comparePhoto);showPhoto(drafts[index],index);});
  }
  function edit(event){
    const field=event.target.dataset.menuField, id=event.target.dataset.menuId;
    if(field){
      const row=drafts.find(row=>row.id===id);if(!row)return;
      row[field]=event.target.value;row.reviewed=false;
      row.review_fields=(row.review_fields||[]).filter(key=>key!==field);
      event.target.closest('.review-field')?.classList.remove('needs-review');
      event.target.closest('.review-field')?.querySelector('[data-review-status]')?.remove();
      const check=$('#batch-preview').querySelector(`[data-menu-reviewed="${id}"]`);if(check)check.checked=false;
    }else if(event.target.dataset.menuReviewed){
      const row=drafts.find(row=>row.id===event.target.dataset.menuReviewed);if(row)row.reviewed=event.target.checked;
    }
    updateReviewCount();
  }
  $('#batch-preview').addEventListener('input',edit);
  $('#batch-preview').addEventListener('change',edit);
  ['#batch-cafe','#batch-address'].forEach(selector=>$(selector).addEventListener('input',()=>{context.provider_id='';context.location=null;}));
  $('#batch-brew').addEventListener('change',()=>{drafts.forEach(row=>{row.brew=$('#batch-brew').value;row.reviewed=false;});render();});
  $('#batch-open').onclick=()=>{initialize();render();message('');dialog.showModal();};
  $('#batch-close').onclick=()=>dialog.close();
  $('#batch-parse').onclick=()=>{
    try{
      if(drafts.length&&!confirm('用粘贴的文字重新生成草稿？当前未保存的逐款修改会被替换。'))return;
      drafts=parseMenuText($('#batch-text').value,$('#batch-brew').value);sourcePhotos.clear();$('#batch-photo-reference').hidden=true;$('#batch-photo-image').removeAttribute('src');render();message(`已生成 ${drafts.length} 款草稿，请逐项核对后保存。`);
    }catch(error){message(error.message,true);}
  };
  $('#menu-batch-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!drafts.length||drafts.some(row=>!row.reviewed)){message('请逐款核对并勾选确认后再保存。',true);return;}
    const button=$('#batch-save');button.disabled=true;
    const state=getState();
    const keys=['id','product','bean','roaster','origin','processing','batch','brew','roast','label_flavors'];
    const items=drafts.map(row=>({...Object.fromEntries(keys.map(key=>[key,row[key]])),kind:'menu',cafe:$('#batch-cafe').value,address:$('#batch-address').value,
      source_note:$('#batch-source').value,observed_on:$('#batch-date').value,
      provider_id:context.provider_id||'',location:context.location||null,
      brew_category:state.brew_catalog?.[row.brew]||state.preferences.brew_categories?.[row.brew]||'unknown'}));
    try{
      const result=await api('/api/menu-batch',{items});await onSaved();
      drafts=[];sourcePhotos.clear();$('#batch-photo-reference').hidden=true;$('#batch-photo-image').removeAttribute('src');$('#batch-text').value='';render();dialog.close();
      toast(result.created?`已新增 ${result.created} 款豆单资料`:'这批豆单已保存，没有重复添加');
    }catch(error){message(error.message,true);}finally{updateReviewCount();}
  });
  return {hasDrafts:()=>drafts.length>0,open(){initialize();render();message('');dialog.showModal();},addPhotoItems(items,{image='',warnings=[]}={}){
    try{
      initialize();
      const unique=items.filter(item=>!item.photo_key||!drafts.some(row=>row.photo_key===item.photo_key));
      if(drafts.length+unique.length>20)throw new Error('草稿合计超过 20 款，请先保存或移除部分产品');
      const additions=unique.length?draftsFromItems(unique):[];additions.forEach(row=>{row.brew=row.brew||$('#batch-brew').value;if(image)sourcePhotos.set(row.id,image);});
      drafts.push(...additions);if(!$('#batch-source').value)$('#batch-source').value='用户核对后的豆单照片';
      render();message([...warnings,'识别结果仅是草稿；逐款对照原图，修改或移除读不清的项，确认后保存。'].join(' '));dialog.showModal();
      if(additions.length&&image){$('#batch-photo-reference').hidden=false;$('#batch-photo-image').src=image;$('#batch-photo-caption').textContent='核对时可展开原图；照片仅保留在当前页面。';}
      return true;
    }catch(error){toast(error.message);return false;}
  }};
}
