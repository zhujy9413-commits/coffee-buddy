const roasts=new Set(['未知','浅烘','中浅烘','中烘','中深烘','深烘']);
const fields=['product','bean','roaster','origin','processing','batch','brew'];

export function draftsFromItems(items, makeId=()=>crypto.randomUUID()) {
  if(!Array.isArray(items)||!items.length||items.length>20)throw new Error('一次请核对 1–20 款产品');
  return items.map(item=>({id:makeId(),...Object.fromEntries(fields.map(key=>[key,typeof item[key]==='string'?item[key].trim():''])),
    roast:roasts.has(item.roast)?item.roast:'未知',
    label_flavors:Array.isArray(item.label_flavors)?item.label_flavors.filter(x=>typeof x==='string').join('、'):''}));
}

export function parseMenuText(raw, brew='', makeId=()=>crypto.randomUUID()) {
  if(typeof raw!=='string'||raw.length>12000)throw new Error('文字过长，请分批整理');
  const lines=raw.split(/\r?\n/).map((text,index)=>({text:text.trim(),line:index+1})).filter(x=>x.text);
  if(!lines.length||lines.length>20)throw new Error('每行一款，每次请粘贴 1–20 行');
  const items=lines.map(({text,line})=>{
    const parts=text.split(/[|｜\t]/).map(x=>x.trim());
    if(parts.length>4)throw new Error(`第 ${line} 行超过 4 列，请按产品、豆子、烘焙、风味整理`);
    const [product,bean='',roast='未知',flavors='']=parts;
    if(!product)throw new Error(`第 ${line} 行缺少产品名称`);
    if(roast&&!roasts.has(roast))throw new Error(`第 ${line} 行烘焙度无法确认，请改为浅烘、中浅烘、中烘、中深烘、深烘或未知`);
    return {product,bean,roast:roast||'未知',brew,label_flavors:flavors.split(/[、，,；;]/).map(x=>x.trim()).filter(Boolean)};
  });
  return draftsFromItems(items,makeId);
}
