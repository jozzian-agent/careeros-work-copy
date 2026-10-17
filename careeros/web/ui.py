"""Shared controls using the accepted shell tokens."""
from flask import render_template
from careeros.web.theme import MOBILE_BREAKPOINT, page_shell

CSS = """
.kanban {display:flex;gap:16px;overflow-x:auto;max-width:100%;padding-bottom:16px;align-items:flex-start;} .kanban-column {flex:0 0 280px;min-width:0;} .kanban-column>h2 {font-size:16px;} .jobs-table {width:100%;border-collapse:collapse;font-size:13px;} .jobs-table th,.jobs-table td {text-align:left;padding:10px;border-bottom:1px solid var(--border-standard);overflow-wrap:anywhere;} .jobs-table th button {padding:4px;border:0;} [data-view][aria-pressed="true"] {background:var(--accent-indigo);}
.kanban-column {min-height:180px;border:1px solid transparent;border-radius:12px;padding:4px;transition:background .15s,border-color .15s;} .kanban-column.drag-over {border-color:var(--accent-indigo);background:var(--bg-elevated);}
.job-card {padding:12px;display:grid;gap:8px;min-height:180px;align-content:start;transition:background .15s,transform .15s;} .job-card:hover {background:var(--card-bg-elevated);transform:translateY(-1px);} .job-heading {display:flex;align-items:flex-start;gap:8px;min-width:0;} .job-card .job-title {font-size:15px;font-weight:600;line-height:1.35;margin:0;flex:1;min-width:0;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;} .job-title a {color:var(--text-primary);text-decoration:none;} .job-card .job-company {font-size:13px;color:var(--text-secondary);margin:0;line-height:1.4;} .job-company a {color:inherit;} .job-card .job-meta {font-size:12px;color:var(--text-muted);margin:0;line-height:1.4;} .job-chips {display:flex;flex-wrap:wrap;gap:6px;} .job-card .job-status {font-size:12px;padding:3px 24px 3px 6px;max-width:min(130px,100%);color:var(--text-secondary);} .job-card[aria-busy="true"] {opacity:.7;}
.mobile-sort {display:none;}
@media(max-width:__MOBILE_BREAKPOINT__px) {.mobile-sort {display:block;margin-bottom:12px;} .jobs-table,.jobs-table tbody,.jobs-table tr,.jobs-table td {display:block;} .jobs-table thead {display:none;} .jobs-table th {padding:2px;} .jobs-table tr.job-row {border:1px solid var(--border-standard);border-radius:8px;margin-bottom:12px;padding:10px;} .jobs-table td {border:0;padding:5px;} .jobs-table td::before {content:attr(data-label) ': ';color:var(--text-muted);} .kanban {flex-direction:column;} .kanban-column {flex:1 1 auto;width:100%;} button,.button,input,select {min-height:44px;} }

button,.button,input,textarea,select {font:inherit;color:var(--text-primary);background:var(--bg-elevated);border:1px solid var(--border-standard);border-radius:6px;padding:9px 12px;}
select {appearance:none;padding-right:30px;background-image:linear-gradient(45deg,transparent 50%,var(--text-muted) 50%),linear-gradient(135deg,var(--text-muted) 50%,transparent 50%);background-position:calc(100% - 15px) 50%,calc(100% - 10px) 50%;background-size:5px 5px;background-repeat:no-repeat;} button:disabled {opacity:.6;cursor:wait;} button,.button {cursor:pointer;text-decoration:none;display:inline-block;font-size:13px;} button:hover,.button:hover {border-color:var(--accent-indigo);} .primary {background:var(--accent-indigo);} .danger {color:var(--status-fail);}
input,textarea {width:100%;} textarea {min-height:100px;resize:vertical;} :focus-visible {outline:2px solid var(--accent-indigo);outline-offset:3px;}
label {display:block;color:var(--text-secondary);font-size:13px;} label input,label textarea {margin-top:8px;} .grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;} .stack {display:grid;gap:16px;} .wide {grid-column:1/-1;} .row {display:flex;gap:10px;align-items:center;flex-wrap:wrap;} .row input {flex:1;min-width:100px;} .card h2 {margin-bottom:12px;} .card p,.card li {line-height:1.65;} .card ul {padding-left:22px;} .chip {height:auto;padding:4px 8px;background:var(--bg-elevated);font-size:12px;color:var(--text-secondary);} .position {display:block;color:inherit;text-decoration:none;} .position:hover {border-color:var(--accent-indigo);} .position h2 {color:var(--text-primary);font-size:18px;} .spaced {margin-top:16px;} .preserve {white-space:pre-wrap;} dt {color:var(--text-muted);margin-top:12px;} dd {margin:5px 0;white-space:pre-wrap;overflow-wrap:anywhere;} .toast {position:fixed;bottom:24px;right:24px;max-width:90vw;background:var(--bg-elevated);border:1px solid var(--status-success);padding:14px 20px;border-radius:8px;z-index:10;} .toast.error {border-color:var(--status-fail);} [hidden] {display:none!important;} dialog {color:var(--text-primary);background:var(--bg-panel);border:1px solid var(--border-standard);border-radius:12px;max-width:450px;padding:24px;} dialog::backdrop {background:var(--bg-page);opacity:.8;} .custom-row {display:grid;grid-template-columns:1fr 2fr auto;gap:8px;margin-bottom:8px;} .card {overflow-wrap:anywhere;} .ai-summary {border-color:var(--accent-indigo);background:var(--card-bg-elevated);} .ai-badge {display:inline-block;margin-bottom:8px;background:var(--accent-indigo);color:var(--text-primary);} details summary {cursor:pointer;color:var(--text-secondary);} @media(max-width:__MOBILE_BREAKPOINT__px) {.grid {grid-template-columns:1fr;} .custom-row {grid-template-columns:1fr;} }
""".replace("__MOBILE_BREAKPOINT__", str(MOBILE_BREAKPOINT))
JS = """
<div id="toast" role="status" class="toast" hidden></div>
<script>
let toastTimer;
function toast(message,error=false){const t=document.getElementById('toast');t.textContent=message;t.className='toast'+(error?' error':'');t.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.hidden=true,5000);}
// A 401 is a lost session, not a failed write: the page goes to the login
// page once instead of toasting 'login required' and leaving the caller to
// ask again. The returned promise never settles on purpose, so no caller's
// success or error path runs on a page that is already navigating away.
// Unconditional, unlike the React client's apiFetch, which has to spare
// the login page's own 401: every page that calls this one sits behind the
// gate, and the fallback login page posts its form without JavaScript.
async function api(url,method,data){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});if(r.status===401){location.assign('/login');return new Promise(()=>{});}let result;try{result=await r.json();}catch{throw Error('Unable to save. Please try again.');}if(!r.ok)throw Error(result.error||'Unable to save.');return result;}
</script>
"""

def page(title, current, template, **context):
    # Every page built here sits behind the login gate, so every one of
    # them carries the logout affordance. So does Page not found, which
    # calls page_shell directly; the login page is the one page without
    # it, being the one page reachable without a session.
    return page_shell(title, current, JS + render_template(template, **context), CSS, logout=True)
