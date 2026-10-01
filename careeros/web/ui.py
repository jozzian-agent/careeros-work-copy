"""Shared controls using the accepted shell tokens."""
from flask import render_template
from careeros.web.theme import page_shell

CSS = """
button,.button,input,textarea,select {font:inherit;color:var(--text-primary);background:var(--bg-elevated);border:1px solid var(--border-standard);border-radius:6px;padding:9px 12px;}
button,.button {cursor:pointer;text-decoration:none;display:inline-block;font-size:13px;} button:hover,.button:hover {border-color:var(--accent-indigo);} .primary {background:var(--accent-indigo);} .danger {color:var(--status-fail);}
input,textarea {width:100%;} textarea {min-height:100px;resize:vertical;} :focus-visible {outline:2px solid var(--accent-indigo);outline-offset:3px;}
label {display:block;color:var(--text-secondary);font-size:13px;} label input,label textarea {margin-top:8px;} .grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;} .stack {display:grid;gap:16px;} .wide {grid-column:1/-1;} .row {display:flex;gap:10px;align-items:center;flex-wrap:wrap;} .row input {flex:1;min-width:100px;} .card h2 {margin-bottom:12px;} .card p,.card li {line-height:1.65;} .card ul {padding-left:22px;} .chip {height:auto;padding:4px 8px;background:var(--bg-elevated);font-size:12px;color:var(--text-secondary);} .position {display:block;color:inherit;text-decoration:none;} .position:hover {border-color:var(--accent-indigo);} .position h2 {color:var(--text-primary);font-size:18px;} .spaced {margin-top:16px;} .preserve {white-space:pre-wrap;} dt {color:var(--text-muted);margin-top:12px;} dd {margin:5px 0;white-space:pre-wrap;overflow-wrap:anywhere;} .toast {position:fixed;bottom:24px;right:24px;max-width:90vw;background:var(--bg-elevated);border:1px solid var(--status-success);padding:14px 20px;border-radius:8px;z-index:10;} .toast.error {border-color:var(--status-fail);} [hidden] {display:none!important;} dialog {color:var(--text-primary);background:var(--bg-panel);border:1px solid var(--border-standard);border-radius:12px;max-width:450px;padding:24px;} dialog::backdrop {background:var(--bg-page);opacity:.8;} .custom-row {display:grid;grid-template-columns:1fr 2fr auto;gap:8px;margin-bottom:8px;} .card {overflow-wrap:anywhere;} @media(max-width:600px) {.grid {grid-template-columns:1fr;} .custom-row {grid-template-columns:1fr;} }
"""
JS = """
<div id="toast" role="status" class="toast" hidden></div>
<script>
let toastTimer;
function toast(message,error=false){const t=document.getElementById('toast');t.textContent=message;t.className='toast'+(error?' error':'');t.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,5000);}
async function api(url,method,data){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});let result;try{result=await r.json();}catch{throw Error('Unable to save. Please try again.');}if(!r.ok)throw Error(result.error||'Unable to save.');return result;}
</script>
"""

def page(title, current, template, **context):
    return page_shell(title, current, JS + render_template(template, **context), CSS)
