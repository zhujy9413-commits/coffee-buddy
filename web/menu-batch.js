import {parseMenuText,draftsFromItems} from './menu-drafts.js';

export function initMenuBatch({getState,getContext,api,onSaved,toast,today}) {
  const $=selector=>document.querySelector(selector);
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let drafts=[], context={}, initialized=false;
  const dialog=$('#menu-batch-dialog');
  function message(text,error=false){$('#batch-status').textContent=text;$('#batch-status').classList.toggle('error',error);}
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
    $('#batch-save').disabled=!drafts.length;
    $('#batch-preview').innerHTML=drafts.map((row,index)=>{
      const input=(field,label,max=160)=>`<label for="menu-${row.id}-${field}">${label}</label><input id="menu-${row.id}-${field}" data-menu-id="${row.id}" data-menu-field="${field}" value="${esc(row[field])}" maxlength="${max}" ${field==='product'?'required':''}>`;
      return `<fieldset class="menu-draft"><legend>第 ${index+1} 款</legend><div class="draft-head"><span>核对产品资料</span><button type="button" class="quiet danger" data-remove-menu="${row.id}">移除此款</button></div>${input('product','产品名称 *')}<div class="field-row"><div><label for="menu-${row.id}-brew">饮品类型 *</label><select id="menu-${row.id}-brew" data-menu-id="${row.id}" data-menu-field="brew" required>${brewOptions(row.brew)}</select></div><div><label for="menu-${row.id}-roast">烘焙深度</label><select id="menu-${row.id}-roast" data-menu-id="${row.id}" data-menu-field="roast">${['未知','浅烘','中浅烘','中烘','中深烘','深烘'].map(value=>`<option ${row.roast===value?'selected':''}>${value}</option>`).join('')}</select></div></div>${input('bean','豆子（不知道可留空）')}${input('label_flavors','标注风味（不知道可留空）',1500)}<details><summary>补充烘焙商、产地和批次</summary>${input('roaster','品牌 / 烘焙商')}${input('origin','产地')}${input('processing','处理方式')}${input('batch','批次 / 烘焙日期')}</details><label class="menu-reviewed"><input type="checkbox" data-menu-reviewed="${row.id}" ${row.reviewed?'checked':''} required>已核对这一款</label></fieldset>`;
    }).join('');
    $('#batch-preview').querySelectorAll('[data-remove-menu]').forEach(button=>button.onclick=()=>{drafts=drafts.filter(row=>row.id!==button.dataset.removeMenu);render();message(`当前保留 ${drafts.length} 款草稿，核对后再保存。`);});
  }
  function edit(event){
    const field=event.target.dataset.menuField, id=event.target.dataset.menuId;
    if(field){
      const row=drafts.find(row=>row.id===id);if(!row)return;
      row[field]=event.target.value;row.reviewed=false;
      const check=$('#batch-preview').querySelector(`[data-menu-reviewed="${id}"]`);if(check)check.checked=false;
    }else if(event.target.dataset.menuReviewed){
      const row=drafts.find(row=>row.id===event.target.dataset.menuReviewed);if(row)row.reviewed=event.target.checked;
    }
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
      drafts=parseMenuText($('#batch-text').value,$('#batch-brew').value);render();message(`已生成 ${drafts.length} 款草稿，请逐项核对后保存。`);
    }catch(error){message(error.message,true);}
  };
  $('#menu-batch-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!drafts.length||drafts.some(row=>!row.reviewed)){message('请逐款核对并勾选确认后再保存。',true);return;}
    const button=$('#batch-save');button.disabled=true;
    const state=getState();
    const items=drafts.map(row=>({...row,kind:'menu',cafe:$('#batch-cafe').value,address:$('#batch-address').value,
      source_note:$('#batch-source').value,observed_on:$('#batch-date').value,
      provider_id:context.provider_id||'',location:context.location||null,
      brew_category:state.brew_catalog?.[row.brew]||state.preferences.brew_categories?.[row.brew]||'unknown'}));
    try{
      const result=await api('/api/menu-batch',{items});await onSaved();
      drafts=[];$('#batch-text').value='';render();dialog.close();
      toast(result.created?`已新增 ${result.created} 款豆单资料`:'这批豆单已保存，没有重复添加');
    }catch(error){message(error.message,true);}finally{button.disabled=!drafts.length;}
  });
  return {addPhotoItems(items){
    try{
      initialize();if(drafts.length+items.length>20)throw new Error('草稿合计超过 20 款，请先保存或移除部分产品');
      const additions=draftsFromItems(items);additions.forEach(row=>{row.brew=row.brew||$('#batch-brew').value;});
      drafts.push(...additions);if(!$('#batch-source').value)$('#batch-source').value='用户核对后的豆单照片';
      render();message('识别结果已加入草稿，请核对产品、饮品类型和共同资料后保存。');dialog.showModal();
    }catch(error){toast(error.message);}
  }};
}
