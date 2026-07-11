# ruff: noqa: E501
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from .cookie_policies import get_cookie_policy, validate_cookie
from .dependencies import authorize_admin
from .errors import APIError
from .schemas import APIKeyCreateRequest, APIKeyUpdateRequest, CredentialUpdateRequest

router = APIRouter()


def _success(request: Request, data: object) -> dict:
    return {"ok": True, "request_id": request.state.request_id, "data": data}


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_panel() -> str:
    return ADMIN_HTML


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/api/admin/status", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def admin_status(request: Request) -> dict:
    return _success(
        request,
        {
            "platform_count": len(request.app.state.parsehub.get_platforms()),
            "api_key_count": len(request.app.state.admin_store.list_api_keys()),
            "redis": request.app.state.redis is not None,
        },
    )


@router.get("/api/admin/keys", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def list_keys(request: Request) -> dict:
    return _success(request, request.app.state.admin_store.list_api_keys())


@router.post("/api/admin/keys", tags=["admin"], dependencies=[Depends(authorize_admin)], status_code=201)
async def create_key(payload: APIKeyCreateRequest, request: Request) -> dict:
    record, raw_key = request.app.state.admin_store.create_api_key(payload.name, payload.daily_quota)
    return _success(request, {**record, "api_key": raw_key})


@router.patch("/api/admin/keys/{key_id}", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def update_key(key_id: str, payload: APIKeyUpdateRequest, request: Request) -> dict:
    try:
        record = request.app.state.admin_store.update_api_key(
            key_id,
            name=payload.name,
            enabled=payload.enabled,
            daily_quota=payload.daily_quota,
            set_quota=payload.daily_quota is not None or payload.clear_daily_quota,
        )
    except KeyError as exc:
        raise APIError(404, "API_KEY_NOT_FOUND", "API Key 不存在") from exc
    return _success(request, record)


@router.delete("/api/admin/keys/{key_id}", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def delete_key(key_id: str, request: Request) -> dict:
    if not request.app.state.admin_store.delete_api_key(key_id):
        raise APIError(404, "API_KEY_NOT_FOUND", "API Key 不存在")
    return _success(request, {"deleted": True})


@router.get("/api/admin/credentials", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def list_credentials(request: Request) -> dict:
    platforms = request.app.state.parsehub.get_platforms()
    return _success(request, request.app.state.admin_store.list_credentials(platforms))


@router.put("/api/admin/credentials/{platform}", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def set_credential(platform: str, payload: CredentialUpdateRequest, request: Request) -> dict:
    supported = {item["id"] for item in request.app.state.parsehub.get_platforms()}
    if platform not in supported:
        raise APIError(404, "PLATFORM_NOT_FOUND", "平台不存在")
    policy = get_cookie_policy(platform)
    warnings: list[str] = []
    if payload.cookie:
        if not policy.supported:
            raise APIError(422, "COOKIE_NOT_SUPPORTED", "当前解析器不会读取该平台 Cookie，可只配置代理")
        try:
            missing_required, missing_recommended = validate_cookie(platform, payload.cookie)
        except ValueError as exc:
            raise APIError(422, "COOKIE_FORMAT_INVALID", "Cookie 格式无法解析") from exc
        if missing_required:
            raise APIError(
                422,
                "COOKIE_FIELDS_MISSING",
                f"Cookie 缺少必需字段：{', '.join(missing_required)}",
                details={"missing": missing_required},
            )
        if missing_recommended:
            warnings.append(f"未检测到推荐字段：{', '.join(missing_recommended)}")
    request.app.state.admin_store.set_credential(platform, payload.cookie, payload.proxy)
    return _success(request, {"saved": True, "warnings": warnings})


@router.delete("/api/admin/credentials/{platform}", tags=["admin"], dependencies=[Depends(authorize_admin)])
async def clear_credential(platform: str, request: Request) -> dict:
    request.app.state.admin_store.clear_credential(platform)
    return _success(request, {"deleted": True})


ADMIN_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ParseHub 管理台</title><style>
:root{--bg:#0b1020;--card:#141b2d;--line:#29334c;--text:#eef3ff;--muted:#93a4c7;--blue:#6ea8fe;--red:#ff6b7a;--green:#4ade80}*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#080c18,#101a31);color:var(--text);font:14px system-ui,-apple-system,sans-serif;min-height:100vh}header{padding:26px max(24px,calc((100% - 1180px)/2));display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);background:#0b1020cc;backdrop-filter:blur(12px);position:sticky;top:0;z-index:3}h1{font-size:21px;margin:0}header span,.muted{color:var(--muted)}main{max-width:1180px;margin:auto;padding:28px 24px 70px}.login{max-width:440px;margin:12vh auto;background:var(--card);padding:28px;border:1px solid var(--line);border-radius:18px}.grid{display:grid;grid-template-columns:1fr 1.15fr;gap:22px}.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 18px 50px #0003}.wide{grid-column:1/-1}h2{font-size:16px;margin:0 0 16px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}input,textarea,select{width:100%;background:#0c1324;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 12px;outline:none}textarea{min-height:110px;resize:vertical}input:focus,textarea:focus{border-color:var(--blue)}button{border:0;border-radius:9px;padding:9px 13px;background:var(--blue);color:#081020;font-weight:650;cursor:pointer}button.ghost{background:#25304a;color:var(--text)}button.danger{background:#44202a;color:#ff9da7}.list{display:grid;gap:10px}.item{border:1px solid var(--line);border-radius:12px;padding:13px;display:flex;justify-content:space-between;align-items:center;gap:12px}.name{font-weight:650}.pill{font-size:12px;padding:3px 8px;border-radius:999px;background:#25304a;color:var(--muted)}.pill.on{background:#123823;color:#7cf1a6}.toolbar{display:grid;grid-template-columns:1fr 150px auto;gap:9px;margin-bottom:15px}.platforms{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}.platform{border:1px solid var(--line);border-radius:12px;padding:13px}.platform .top{display:flex;justify-content:space-between;margin-bottom:12px}.status{color:var(--muted);font-size:12px}.status.ok{color:var(--green)}dialog{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:15px;width:min(560px,92vw);padding:22px}dialog::backdrop{background:#000a}.toast{position:fixed;right:22px;bottom:22px;background:#1e2b45;border:1px solid var(--line);padding:12px 16px;border-radius:10px;display:none}.secret{word-break:break-all;background:#09101f;padding:13px;border-radius:10px;border:1px dashed var(--blue);margin:12px 0}@media(max-width:800px){.grid{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.wide{grid-column:auto}}
</style></head><body><header><div><h1>ParseHub 管理台</h1><span>平台凭据与 API Key</span></div><button class="ghost" onclick="logout()">退出</button></header>
<main><section id="login" class="login"><h2>管理员认证</h2><p class="muted">输入服务器环境变量 PARSEHUB_ADMIN_TOKEN。</p><input id="token" type="password" placeholder="管理员密钥"><br><br><button onclick="login()">进入管理台</button></section>
<section id="app" class="grid" hidden><div class="card"><h2>生成 API Key</h2><div class="toolbar"><input id="keyName" placeholder="名称，例如：我的 iPhone"><input id="keyQuota" type="number" min="1" placeholder="独立日额度"><button onclick="createKey()">生成</button></div><p class="muted">密钥明文只显示一次。服务端仅保存不可逆摘要。</p></div><div class="card"><h2>运行状态</h2><div id="status" class="muted">载入中…</div></div><div class="card wide"><h2>API Keys</h2><div id="keys" class="list"></div></div><div class="card wide"><h2>平台 Cookie 与代理</h2><p class="muted">Cookie 使用服务端密钥加密保存，列表不会回显明文。</p><div id="platforms" class="platforms"></div></div></section></main>
<dialog id="credentialDialog"><h2 id="credentialTitle">平台设置</h2><input id="platformId" type="hidden"><div id="cookieHint" class="muted" style="margin-bottom:12px;line-height:1.65"></div><label>解析与媒体下载代理（可选）</label><input id="proxy" placeholder="http://127.0.0.1:7890"><br><label>Cookie</label><textarea id="cookie" placeholder="Cookie Header、JSON 或 key=value; ...；留空则保留原 Cookie"></textarea><div class="row" style="margin-top:16px"><button onclick="saveCredential()">保存</button><button class="danger" onclick="clearCredential()">清除配置</button><button class="ghost" onclick="credentialDialog.close()">取消</button></div></dialog>
<dialog id="secretDialog"><h2>API Key 已生成</h2><p class="muted">请立即复制，关闭后无法再次查看。</p><div id="newSecret" class="secret"></div><div class="row"><button onclick="copySecret()">复制</button><button class="ghost" onclick="secretDialog.close()">完成</button></div></dialog><div id="toast" class="toast"></div>
<script>
let adminToken=sessionStorage.getItem('parsehub_admin')||'';const $=id=>document.getElementById(id);async function api(path,opt={}){opt.headers={...(opt.headers||{}),'X-Admin-Token':adminToken};if(opt.body)opt.headers['Content-Type']='application/json';const r=await fetch(path,opt),j=await r.json();if(!j.ok)throw Error(j.error.message);return j.data}function toast(s){$('toast').textContent=s;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',2200)}async function login(){adminToken=$('token').value;try{await api('/api/admin/status');sessionStorage.setItem('parsehub_admin',adminToken);showApp()}catch(e){toast(e.message)}}function logout(){sessionStorage.removeItem('parsehub_admin');location.reload()}async function showApp(){$('login').hidden=true;$('app').hidden=false;await Promise.all([loadStatus(),loadKeys(),loadPlatforms()])}async function loadStatus(){const s=await api('/api/admin/status');$('status').innerHTML=`支持平台：<b>${s.platform_count}</b><br>动态 Key：<b>${s.api_key_count}</b><br>Redis：<b>${s.redis?'已启用':'单机模式'}</b>`}async function loadKeys(){const rows=await api('/api/admin/keys');$('keys').innerHTML=rows.length?rows.map(k=>`<div class="item"><div><div class="name">${esc(k.name)} <span class="pill ${k.enabled?'on':''}">${k.enabled?'启用':'停用'}</span></div><div class="muted">${k.prefix}… · 日额度 ${k.daily_quota||'默认'} · 最近使用 ${fmt(k.last_used_at)}</div></div><div class="row"><button class="ghost" onclick="toggleKey('${k.id}',${!k.enabled})">${k.enabled?'停用':'启用'}</button><button class="danger" onclick="deleteKey('${k.id}')">删除</button></div></div>`).join(''):'<div class="muted">尚未生成动态 API Key</div>'}async function createKey(){const name=$('keyName').value.trim(),q=+$('keyQuota').value||null;if(!name)return toast('请输入名称');const x=await api('/api/admin/keys',{method:'POST',body:JSON.stringify({name,daily_quota:q})});$('newSecret').textContent=x.api_key;secretDialog.showModal();$('keyName').value='';$('keyQuota').value='';await Promise.all([loadKeys(),loadStatus()])}async function toggleKey(id,enabled){await api('/api/admin/keys/'+id,{method:'PATCH',body:JSON.stringify({enabled})});loadKeys()}async function deleteKey(id){if(!confirm('确定永久删除这个 API Key？'))return;await api('/api/admin/keys/'+id,{method:'DELETE'});loadKeys();loadStatus()}async function loadPlatforms(){const rows=await api('/api/admin/credentials');$('platforms').innerHTML=rows.map(p=>{const policy=p.cookie_policy,label=!policy.supported?'不支持 Cookie':p.cookie_configured?'Cookie 已配置':policy.required.length?'需要 Cookie':'Cookie 可选';return `<div class="platform"><div class="top"><div class="name">${esc(p.name)}</div><span class="status ${p.cookie_configured?'ok':''}">${label}</span></div><div class="muted">${policy.required.length?'必需：'+policy.required.join(', '):policy.supported?'无硬性必需字段':'当前解析器不读取 Cookie'}<br>代理：${esc(p.proxy||'默认出口')}</div><br><button class="ghost" onclick='openCredential(${JSON.stringify(JSON.stringify(p))})'>${policy.supported?'设置 Cookie / 代理':'设置代理'}</button></div>`}).join('')}function openCredential(raw){const p=JSON.parse(raw),policy=p.cookie_policy;$('platformId').value=p.platform;$('credentialTitle').textContent=p.name+' 设置';$('cookie').value='';$('cookie').disabled=!policy.supported;$('proxy').value=p.proxy||'';const required=policy.required.length?`<b>必需字段：</b>${policy.required.join(', ')}<br>`:'';const recommended=policy.recommended.length?`<b>推荐字段：</b>${policy.recommended.join(', ')}<br>`:'';$('cookieHint').innerHTML=required+recommended+esc(policy.note);credentialDialog.showModal()}async function saveCredential(){const platform=$('platformId').value,cookie=$('cookie').disabled?null:($('cookie').value||null),proxy=$('proxy').value||null;const result=await api('/api/admin/credentials/'+platform,{method:'PUT',body:JSON.stringify({cookie,proxy})});credentialDialog.close();toast(result.warnings.length?`已保存；${result.warnings.join('；')}`:'已保存');loadPlatforms()}async function clearCredential(){const platform=$('platformId').value;if(!confirm('清除这个平台的 Cookie 和代理？'))return;await api('/api/admin/credentials/'+platform,{method:'DELETE'});credentialDialog.close();loadPlatforms()}function copySecret(){navigator.clipboard.writeText($('newSecret').textContent);toast('已复制')}function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}function fmt(t){return t?new Date(t*1000).toLocaleString():'从未'}if(adminToken){api('/api/admin/status').then(showApp).catch(()=>sessionStorage.removeItem('parsehub_admin'))}
</script></body></html>"""
