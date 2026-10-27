export const reactionLabels = Object.freeze({like:'喜欢',okay:'一般',neutral:'还说不准',dislike:'不太喜欢'});

export function feedbackLines(feedback) {
  if(!feedback)return [];
  const lines=[`上次评价：${reactionLabels[feedback.reaction]||'还说不准'} · ${feedback.observed_on}`];
  if(feedback.tasted_flavors?.length)lines.push(`实际喝到：${feedback.tasted_flavors.join('、')}`);
  return lines;
}

export function shopLinkHint(record) {
  if(!record.cafe)return '尚未填写店铺，暂不参与具体分店推荐。';
  if(!record.address&&!record.provider_id)return '已保存体验；补充分店地址或地图关联后，才能参与具体分店匹配。';
  return '';
}

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
