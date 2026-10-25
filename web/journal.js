// A new tasting copies product facts, never the old entry ID or judgment.
export function tastingDraft(record, today) {
  const fields=['product','bean','roaster','origin','processing','batch','roast','brew','brew_category','cafe','address','provider_id','source_note'];
  const draft=Object.fromEntries(fields.map(key=>[key,record[key]||'']));
  return {...draft,id:'',kind:'tasting',observed_on:today,reaction:'neutral',
    label_flavors:[...(record.label_flavors||[])],tasted_flavors:[],note:'',
    location:record.location?{...record.location}:null};
}
