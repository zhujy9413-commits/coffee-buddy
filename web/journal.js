// A new tasting copies product facts, never the old entry ID or judgment.
export function tastingDraft(record, today) {
  const fields=['product','bean','roaster','origin','processing','batch','roast','brew','brew_category','cafe','address','provider_id','source_note'];
  const draft=Object.fromEntries(fields.map(key=>[key,record[key]||'']));
  return {...draft,id:'',kind:'tasting',observed_on:today,reaction:'neutral',
    label_flavors:[...(record.label_flavors||[])],tasted_flavors:[],note:'',
    location:record.location?{...record.location}:null};
}

// A photo creates menu facts, never edits the old entry or imports its reaction.
export function photoMenuDraft(item, context, today) {
  const value=key=>typeof item[key]==='string'?item[key]:'';
  const facts=Object.fromEntries(['product','bean','roaster','origin','processing','batch'].map(key=>[key,value(key)]));
  const roasts=new Set(['未知','浅烘','中浅烘','中烘','中深烘','深烘']);
  const common=Object.fromEntries(['cafe','address','provider_id','source_note'].map(key=>[key,typeof context[key]==='string'?context[key]:'']));
  return {...tastingDraft({...facts,...common,location:context.location,
      brew:value('brew')||context.brew||'',roast:roasts.has(item.roast)?item.roast:'未知'},today),
    kind:'menu',source_note:common.source_note||'用户核对后的豆单 / 包装照片',
    label_flavors:Array.isArray(item.label_flavors)?item.label_flavors.filter(x=>typeof x==='string'):[]};
}
