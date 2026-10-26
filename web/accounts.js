// Account secrets stay in the dialog's memory; never in browser storage or URLs.
export function initAccounts({getState, api, exportBackup, onResume}) {
  const $=s=>document.querySelector(s), dialog=$('#account-dialog');
  let pending=false, receipt=false, forcedLogin=false;
  const message=(value,error=false)=>{const el=$('#account-status');el.textContent=value;el.classList.toggle('error',error);};
  function render() {
    const name=getState().account?.username;
    $('#account-open').textContent=name?`账号 · ${name}`:'登录 / 注册';
    $('#account-guest').hidden=!!name&&!forcedLogin;
    $('#account-known').hidden=!name||forcedLogin;
    $('#account-name').textContent=name?`当前账号：${name}`:'';
    mode();
  }
  function mode() {
    const value=$('#account-mode').value, login=value==='login', recover=value==='recover';
    $('#account-confirm-field').hidden=login;
    $('#account-confirm').disabled=login;
    $('#account-recover-field').hidden=!recover;
    $('#account-recovery').disabled=!recover;
    $('#account-recovery').required=recover;
    $('#account-password').minLength=login?1:8;
    $('#account-password').maxLength=login?128:20;
    $('#account-password').autocomplete=login?'current-password':'new-password';
    $('#account-password-label').textContent=recover?'新密码':'密码';
    $('#account-password-hint').hidden=login;
    const switching=login&&!getState().account?.username&&getState().records.length>0;
    $('#account-switch').hidden=!switching;
    $('#account-switch-confirm').required=switching;
    $('#account-submit').textContent=login?'登录个人账号':recover?'验证恢复码并重设密码':'注册并认领当前记录';
  }
  function clearSecrets() {
    for(const id of ['#account-password','#account-confirm','#account-recovery','#account-current-password','#account-code']) $(id).value='';
  }
  function showCode(result) {
    receipt=true; clearSecrets();
    $('#account-guest').hidden=true;$('#account-known').hidden=true;
    $('#account-receipt').hidden=false;$('#account-close').hidden=true;
    $('#account-code').value=result.recovery_code;
    $('#account-code-saved').checked=false;$('#account-done').disabled=true;
    message(result.login_required?'密码已重设，保存新恢复码后请使用新密码登录。':`账号 ${result.username} 已保存。`);
    dialog.scrollTop=0;
  }
  async function run(button, action) {
    if(pending)return;
    pending=true;button.disabled=true;$('#account-mode').disabled=true;$('#account-close').disabled=true;message('正在处理，请稍候……');
    try {await action();} catch(error){message(error.message,true);}
    finally {pending=false;button.disabled=false;$('#account-mode').disabled=false;$('#account-close').disabled=false;}
  }
  $('#account-open').onclick=()=>{if(pending)return;clearSecrets();message('');render();dialog.showModal();};
  $('#account-mode').onchange=()=>{clearSecrets();message('');$('#account-switch-confirm').checked=false;mode();};
  $('#account-close').onclick=()=>{if(!pending&&!receipt)dialog.close();};
  dialog.addEventListener('cancel',e=>{if(pending||receipt)e.preventDefault();});
  dialog.addEventListener('close',()=>{clearSecrets();message('');});
  $('#account-export').onclick=()=>run($('#account-export'),async()=>{await exportBackup();message('已请求下载备份，请确认文件已保存，再勾选并登录。');});
  $('#account-form').onsubmit=e=>{
    e.preventDefault();const value=$('#account-mode').value;
    if(value!=='login'&&$('#account-password').value!==$('#account-confirm').value){message('两次输入的密码不一致',true);return;}
    run($('#account-submit'),async()=>{
      const result=await api('/api/account/'+value,{username:$('#account-username').value,password:$('#account-password').value,
        ...(value==='recover'?{recovery_code:$('#account-recovery').value}:{}),switch_confirmed:$('#account-switch-confirm').checked});
      clearSecrets();
      if(result.recovery_code)showCode(result);
      else if(result.username===getState().account?.username){forcedLogin=false;await onResume();dialog.close();}
      else location.reload();
    });
  };
  $('#account-logout').onclick=()=>{
    if(!confirm('退出个人账号？账号里的记录会保留，当前尚未保存的填写内容不会保留。'))return;
    run($('#account-logout'),async()=>{await api('/api/account/logout',{});location.reload();});
  };
  $('#account-rotate-form').onsubmit=e=>{e.preventDefault();run(e.target.querySelector('button'),async()=>{
    const result=await api('/api/account/recovery-code',{password:$('#account-current-password').value});showCode(result);
  });};
  $('#account-copy').onclick=async()=>{
    try{await navigator.clipboard.writeText($('#account-code').value);message('恢复码已复制，请粘贴到密码管理器保存。');}
    catch{const code=$('#account-code');code.focus();code.select();message('请长按恢复码选择并复制，保存到密码管理器。');}
  };
  $('#account-code-saved').onchange=()=>$('#account-done').disabled=!$('#account-code-saved').checked;
  $('#account-done').onclick=()=>{if(!$('#account-code-saved').checked)return;clearSecrets();location.reload();};
  function requireLogin() {
    if(pending||receipt)return;
    forcedLogin=true;clearSecrets();$('#account-mode').value='login';
    $('#account-username').value=getState().account?.username||'';
    render();message('登录已过期。重新登录同一账号后，当前未保存的填写内容会保留。',true);
    if(!dialog.open)dialog.showModal();
  }
  return {render,requireLogin};
}
