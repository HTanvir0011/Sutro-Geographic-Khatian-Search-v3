(()=>{'use strict';
const el=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let csrf='',setup=false,page=1,total=0,current=null,uploadId=null,places=[],listRequest=0,areaRequest=0,messageTimer;
let adminActive=false,complaintPage=1,complaintRequest=0,complaintDetailRequest=0,currentComplaint=null;
const complaintStates={new:'নতুন',read:'দেখা হয়েছে',reviewing:'পর্যালোচনায়',resolved:'সমাধান হয়েছে',closed:'বন্ধ'};
function message(text,error=false){const box=el('message');box.textContent=text;box.className=error?'error':'';box.hidden=false;if(el('recordDialog').open){el('dialogNotice').textContent=text;el('dialogNotice').hidden=false}if(el('complaintDialog').open){el('complaintNotice').textContent=text;el('complaintNotice').hidden=false}clearTimeout(messageTimer);messageTimer=setTimeout(()=>box.hidden=true,6500)}
async function api(url,options={}){
 const headers={...options.headers};
 if(options.method&&options.method!=='GET')headers['X-CSRF-Token']=csrf;
 if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
 const response=await fetch(url,{...options,headers});
 let data;try{data=await response.json()}catch{throw Error('সার্ভার থেকে সঠিক উত্তর পাওয়া যায়নি।')}
 if(!response.ok){if(response.status===401&&!url.endsWith('/login')){adminActive=false;el('recordDialog').close();el('complaintDialog').close();el('workspace').hidden=true;el('loginView').hidden=false;el('logout').hidden=true}throw Error(data.error||'অনুরোধ সম্পন্ন হয়নি।')}
 return data;
}
async function busy(form,work){const buttons=[...form.querySelectorAll('button')].map(button=>({button,disabled:button.disabled}));buttons.forEach(({button})=>button.disabled=true);try{await work()}catch(error){message(error.message,true)}finally{buttons.forEach(({button,disabled})=>button.disabled=disabled)}}
function tab(name){for(const item of ['records','upload','deed','evidence','settings','complaints'])el(item+'Panel').hidden=item!==name;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));if(name==='records')loadRecords();if(name==='settings'&&el('userManagement')&&!el('userManagement').hidden)loadAdminUsers();if(name==='complaints')loadComplaints();if(name==='evidence')loadEvidenceHistory()}
async function loadSession(){
 const data=await api('/api/admin/session');csrf=data.csrf;setup=data.setup_required;
 adminActive=data.authenticated;
 el('loginView').hidden=data.authenticated;el('workspace').hidden=!data.authenticated;el('logout').hidden=!data.authenticated;
 el('loginTitle').textContent=setup?'প্রথমবারের পাসওয়ার্ড সেট করুন':'অ্যাডমিন লগইন';
 el('loginHint').textContent=setup?(data.setup_allowed?'১২ অক্ষর বা তার বেশি একটি পাসওয়ার্ড দিন।':'প্রথম সেটআপের জন্য এই কম্পিউটারে http://127.0.0.1:5000/admin খুলুন।'):'পাসওয়ার্ড দিয়ে আপনার নথি পরিচালনা করুন।';
 el('loginButton').disabled=setup&&!data.setup_allowed;
 el('loginButton').textContent=setup?'পাসওয়ার্ড সেট করে শুরু করুন →':'লগইন করুন →';
 const usernameLabel=el('usernameLabel');if(usernameLabel)usernameLabel.hidden=setup;
 el('confirmLabel').hidden=!setup;el('confirmPassword').required=setup;
 el('password').minLength=setup?12:1;el('password').autocomplete=setup?'new-password':'current-password';
 const userManagement=el('userManagement');if(userManagement)userManagement.hidden=!data.authenticated||data.admin?.role!=='superadmin';
 if(data.authenticated){tab(['records','upload','deed','evidence','settings','complaints'].includes(location.hash.slice(1))?location.hash.slice(1):'records');loadPlaces();refreshComplaintBadge();if(data.admin?.role==='superadmin')loadAdminUsers()}
}
async function loadAdminUsers(){if(!el('adminUserList'))return;try{const data=await api('/api/admin/users');el('adminUserList').innerHTML=data.users.map(user=>`<div class="admin-user-row"><strong>${esc(user.username)}</strong><span>${esc(user.role)} · ${user.active?'Active':'Disabled'}</span>${user.role==='admin'?`<button type="button" data-admin-id="${user.id}" data-admin-active="${user.active?'0':'1'}">${user.active?'Disable':'Enable'}</button>`:''}</div>`).join('')}catch(error){message(error.message,true)}}
async function loadRecords(){
 const requestId=++listRequest;
 const params=new URLSearchParams({kind:el('recordKind').value,state:el('recordState').value,q:el('recordQuery').value,page});
 el('recordRows').innerHTML='<tr><td colspan="4">লোড হচ্ছে…</td></tr>';
 try{const data=await api('/api/admin/records?'+params);if(requestId!==listRequest)return;total=data.total;
  if(page>Math.max(1,Math.ceil(total/25))){page=Math.max(1,Math.ceil(total/25));return loadRecords()}
  el('metrics').innerHTML=[[el('recordKind').value==='khatian'?'সব খতিয়ান':'সব দলিল',data.counts.total],['Draft',data.counts.drafts],['Warning',data.counts.warnings],['মুছে ফেলা',data.counts.deleted]].map(([label,value])=>`<div class="metric"><b>${esc(value)}</b><span>${label}</span></div>`).join('');
  el('recordRows').innerHTML=data.records.map(r=>`<tr><td><strong>${esc(r.title)}</strong><small>${esc(r.id)} · ${esc(r.survey)}</small></td><td>${esc(r.location)}</td><td><span class="badge ${r.deleted?'deleted':''}">${esc(r.deleted?'Deleted':r.status)}</span>${r.warning?'<br><span class="badge warn">⚠ Warning</span>':''}</td><td><button data-record="${esc(r.id)}" data-kind="${esc(el('recordKind').value)}">বিস্তারিত →</button></td></tr>`).join('')||'<tr><td colspan="4">কোনো রেকর্ড পাওয়া যায়নি।</td></tr>';
  el('pageInfo').textContent=`পৃষ্ঠা ${page} / ${Math.max(1,Math.ceil(total/25))} · ${total} রেকর্ড`;
  el('prevPage').disabled=page<=1;el('nextPage').disabled=page*25>=total;
 }catch(error){if(requestId!==listRequest)return;el('recordRows').textContent='';message(error.message,true)}
}
async function openRecord(kind,id){
 try{current=await api('/api/admin/records/'+kind+'/'+encodeURIComponent(id));
  const labels={deed_no:'Deed image number',filename:'Filename',khatian_no:'খতিয়ান',owner_name:'মালিক',dag_no:'দাগ',land_area_decimal:'জমি (শতাংশ)',district:'জেলা',upazila:'উপজেলা',mouza:'মৌজা',division:'বিভাগ',survey:'জরিপ',year:'সাল',jl_no:'JL',deed_date:'দলিলের তারিখ',total_land_dec:'মোট জমি'};
  el('detailTitle').textContent=id;
  const fields=Object.entries(current.record).filter(([k,v])=>labels[k]&&typeof v!=='object').map(([k,v])=>`<div><small>${labels[k]}</small>${esc(v||'—')}</div>`).join('');
  el('detailBody').innerHTML=(current.image_url?`<a target="_blank" rel="noopener" href="${esc(current.image_url)}"><img class="detail-image" src="${esc(current.image_url)}" alt="খতিয়ানের ছবি"></a>`:'')+`<div class="details-grid">${fields}</div>`+(kind==='deed'?`<a target="_blank" rel="noopener" href="/api/admin/deeds/${encodeURIComponent(id)}/pdf">Signed PDF ডাউনলোড ↗</a>`:'')+`<details><summary>সম্পূর্ণ রেকর্ড দেখুন</summary><pre>${esc(JSON.stringify(current.record,null,2))}</pre></details>`;
  el('warningInput').value=current.warning;el('deleteRecord').textContent=current.deleted?'Restore করুন':'Delete করুন';el('editUpload').hidden=!current.editable;el('dialogNotice').hidden=true;el('recordDialog').showModal();
 }catch(error){message(error.message,true)}
}
async function updateControl(obj){
 if(!current)return;
 await api(`/api/admin/records/${current.kind}/${encodeURIComponent(current.id)}`,{method:'PATCH',body:JSON.stringify(obj)});
 el('recordDialog').close();message('রেকর্ড আপডেট হয়েছে।');await loadRecords();
}
function fillReview(data){
 setupLineOcr();
 uploadId=data.id;tab('upload');el('reviewCard').hidden=false;el('reviewImage').src=data.image_url;el('reviewOriginal').href=data.image_url;
 el('ocrText').textContent=data.ocr_text||'কোনো লেখা পাওয়া যায়নি।';el('ocrMessage').textContent=data.ocr_message||'OCR প্রস্তাবনা নিচে দেওয়া আছে। ছবির সঙ্গে মিলিয়ে তথ্য সংশোধন করুন।';
 const form=el('reviewForm');form.reset();for(const [key,value] of Object.entries(data.record)){if(form.elements[key]&&!Array.isArray(value))form.elements[key].value=value||''}
 form.elements.owners.value=(data.record.owners||[]).map(r=>[r.name_bn,r.father_or_spouse_bn,r.share_exact].join(' | ')).join('\n');
 form.elements.dag_rows.value=(data.record.dag_rows||[]).map(r=>[r.dag_no,r.land_class_bn,r.area_dec].join(' | ')).join('\n');
 fillUpazilas();loadMouzas();el('reviewCard').scrollIntoView({behavior:'smooth',block:'start'});
}
function parseRows(text,keys){return text.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{const parts=line.split('|').map(v=>v.trim());if(parts.length>keys.length)throw Error('প্রতি লাইনে সর্বোচ্চ তিনটি তথ্য | দিয়ে আলাদা করুন।');return Object.fromEntries(keys.map((k,i)=>[k,parts[i]||'']))})}
function datalist(id,values){el(id).innerHTML=[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'bn')).map(v=>`<option value="${esc(v)}"></option>`).join('')}
async function loadPlaces(){try{places=(await api('/api/khatian/filters')).places;datalist('districtList',places.map(p=>p.district));fillUpazilas()}catch(error){message(error.message,true)}}
function fillUpazilas(){const district=el('reviewForm').elements.district.value.normalize('NFC');datalist('upazilaList',places.filter(p=>p.district.normalize('NFC')===district).map(p=>p.upazila))}
async function loadMouzas(){
 const form=el('reviewForm'),district=form.elements.district.value,upazila=form.elements.upazila.value;
 const requestId=++areaRequest;datalist('mouzaList',[]);if(!district||!upazila)return;
 try{const data=await api('/api/khatian/filters?'+new URLSearchParams({district,upazila}));if(requestId===areaRequest)datalist('mouzaList',data.places.map(p=>p.mouza))}catch(error){message(error.message,true)}
}
el('loginForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{
 if(setup&&el('password').value!==el('confirmPassword').value)throw Error('দুটি পাসওয়ার্ড মেলেনি।');
 const username=el('username');const password=el('password');if(!password)throw Error('Admin login form is incomplete. Reload the page.');const data=await api('/api/admin/'+(setup?'setup':'login'),{method:'POST',body:JSON.stringify({username:username?username.value:'superadmin',password:password.value})});csrf=data.csrf;event.target.reset();await loadSession();
})});
el('logout').addEventListener('click',()=>busy(el('workspace'),async()=>{await api('/api/admin/logout',{method:'POST'});adminActive=false;complaintRequest++;complaintDetailRequest++;el('complaintDialog').close();el('complaintDetail').textContent='';el('complaintRows').textContent='';el('complaintNote').value='';currentComplaint=null;el('recordDialog').close();uploadId=null;el('reviewCard').hidden=true;el('reviewForm').reset();await loadSession()}));
setupEvidence();
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));
el('filterForm').addEventListener('submit',event=>{event.preventDefault();page=1;loadRecords()});
for(const id of ['recordKind','recordState'])el(id).addEventListener('change',()=>{page=1;loadRecords()});
el('prevPage').addEventListener('click',()=>{page--;loadRecords()});el('nextPage').addEventListener('click',()=>{page++;loadRecords()});
el('recordRows').addEventListener('click',event=>{const button=event.target.closest('[data-record]');if(button)openRecord(button.dataset.kind,button.dataset.record)});
el('closeDialog').addEventListener('click',()=>el('recordDialog').close());
el('saveWarning').addEventListener('click',()=>busy(el('recordDialog'),()=>updateControl({warning:el('warningInput').value.trim()})));
el('deleteRecord').addEventListener('click',()=>{if(!current)return;const deleted=!current.deleted;if(deleted&&!confirm('রেকর্ডটি পাবলিক সাইট থেকে মুছে ফেলবেন? পরে Restore করা যাবে।'))return;busy(el('recordDialog'),()=>updateControl({deleted}))});
el('editUpload').addEventListener('click',()=>{el('recordDialog').close();fillReview(current)});
el('uploadForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{
 el('uploadStatus').textContent='ছবি আপলোড ও OCR চলছে…';
 try{const data=await api('/api/admin/khatian-upload',{method:'POST',body:new FormData(event.target)});fillReview(data);message('Draft তৈরি হয়েছে। তথ্য যাচাই করে Publish করুন।')}finally{el('uploadStatus').textContent=''}
})});
el('reviewForm').addEventListener('submit',event=>{event.preventDefault();const status=event.submitter?.value||'draft';if(status==='published'&&!event.target.reportValidity())return;busy(event.target,async()=>{
 const obj=Object.fromEntries(new FormData(event.target));obj.owners=parseRows(obj.owners,['name_bn','father_or_spouse_bn','share_exact']);obj.dag_rows=parseRows(obj.dag_rows,['dag_no','land_class_bn','area_dec']);
 await api('/api/admin/khatians/'+encodeURIComponent(uploadId),{method:'PATCH',body:JSON.stringify({record:obj,status})});message(status==='published'?'খতিয়ান Publish হয়েছে। এখন পাবলিক সার্চে পাওয়া যাবে।':'Draft সংরক্ষিত হয়েছে।');tab('records');
})});
el('reviewForm').elements.district.addEventListener('input',()=>{fillUpazilas();areaRequest++;datalist('mouzaList',[])});
el('reviewForm').elements.upazila.addEventListener('change',loadMouzas);
el('adminDeedForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{
 const data=await api('/api/deeds',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
 el('deedSaved').innerHTML=`<strong>✓ ${esc(data.record.deed_id)} সংরক্ষিত হয়েছে।</strong><p><a href="/api/deeds/${encodeURIComponent(data.record.deed_id)}/pdf">QR-সহ signed PDF ডাউনলোড ↗</a></p>`;event.target.reset();message('দলিল যোগ হয়েছে। সব রেকর্ড থেকে warning ও delete পরিচালনা করতে পারবেন।');
})});
el('passwordForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{const obj=Object.fromEntries(new FormData(event.target));if(obj.password!==obj.confirm)throw Error('দুটি নতুন পাসওয়ার্ড মেলেনি।');delete obj.confirm;const data=await api('/api/admin/password',{method:'POST',body:JSON.stringify(obj)});csrf=data.csrf;event.target.reset();message('পাসওয়ার্ড পরিবর্তন হয়েছে।')})});
const adminUserForm=el('adminUserForm');if(adminUserForm)adminUserForm.addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{const obj=Object.fromEntries(new FormData(event.target));await api('/api/admin/users',{method:'POST',body:JSON.stringify(obj)});event.target.reset();el('adminUserMessage').textContent='Admin account তৈরি হয়েছে।';await loadAdminUsers()})});
const adminUserList=el('adminUserList');if(adminUserList)adminUserList.addEventListener('click',event=>{const button=event.target.closest('[data-admin-id]');if(!button)return;busy(el('userManagement'),async()=>{await api('/api/admin/users/'+button.dataset.adminId,{method:'PATCH',body:JSON.stringify({active:button.dataset.adminActive==='1'})});await loadAdminUsers()})});
async function refreshComplaintBadge(){
 if(!adminActive)return;
 try{const data=await api('/api/admin/complaints/stats');el('newComplaintBadge').textContent=data.new+' নতুন';el('newComplaintBadge').hidden=!data.new}catch{/* Session handling is performed by api(). */}
}
async function loadComplaints(){
 const requestId=++complaintRequest;
 const params=new URLSearchParams({status:el('complaintStatusFilter').value,q:el('complaintSearch').value,page:complaintPage});
 el('complaintRows').innerHTML='<tr><td colspan="4">লোড হচ্ছে…</td></tr>';
 try{const data=await api('/api/admin/complaints?'+params);if(requestId!==complaintRequest)return;
  if(complaintPage>Math.max(1,Math.ceil(data.total/20))){complaintPage=Math.max(1,Math.ceil(data.total/20));return loadComplaints()}
  const counts=data.counts;
  el('complaintMetrics').innerHTML=[['সব অভিযোগ',Object.values(counts).reduce((a,b)=>a+b,0)],['নতুন',counts.new||0],['পর্যালোচনায়',counts.reviewing||0],['সমাধান হয়েছে',counts.resolved||0]].map(([label,count])=>`<div class="metric"><b>${esc(count)}</b><span>${label}</span></div>`).join('');
  el('complaintRows').innerHTML=data.complaints.map(c=>`<tr><td><strong>${esc(c.subject)}</strong><small>${esc(c.category)}<br>${esc(c.id)}<br>${esc(new Date(c.created_at).toLocaleString('bn-BD',{timeZone:'Asia/Dhaka'}))}</small></td><td>${esc(c.name)}<small>${esc([c.district,c.upazila,c.mouza].join(' · '))}</small></td><td><span class="badge ${c.status==='new'?'warn':''}">${esc(complaintStates[c.status])}</span><small>${esc(c.documents)} নথি</small></td><td><button data-complaint="${esc(c.id)}">বিস্তারিত →</button></td></tr>`).join('')||'<tr><td colspan="4">কোনো অভিযোগ পাওয়া যায়নি।</td></tr>';
  el('complaintPageInfo').textContent=`পৃষ্ঠা ${complaintPage} / ${Math.max(1,Math.ceil(data.total/20))} · ${data.total} অভিযোগ`;
  el('complaintPrev').disabled=complaintPage<=1;el('complaintNext').disabled=complaintPage*20>=data.total;
  refreshComplaintBadge();
 }catch(err){if(requestId===complaintRequest){el('complaintRows').textContent='';message(err.message,true)}}
}
async function openComplaint(id){
 const requestId=++complaintDetailRequest;
 try{const data=await api('/api/admin/complaints/'+encodeURIComponent(id));if(requestId!==complaintDetailRequest)return;
  if(data.status==='new'){await api('/api/admin/complaints/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({status:'read'})});data.status='read'}
  if(requestId!==complaintDetailRequest)return;currentComplaint=data;
  const labels={name:'অভিযোগকারী',phone:'ফোন',district:'জেলা',upazila:'উপজেলা',mouza:'মৌজা',khatian_no:'খতিয়ান',dag_no:'দাগ'};
  el('complaintDetail').innerHTML=`<span class="eyebrow">${esc(data.category)}</span><h2>${esc(data.fields.subject)}</h2><p class="hint">${esc(data.id)} · ${esc(new Date(data.created_at).toLocaleString('bn-BD',{timeZone:'Asia/Dhaka'}))}</p><div class="details-grid">${Object.entries(labels).map(([key,label])=>`<div><small>${label}</small>${esc(data.fields[key]||'—')}</div>`).join('')}</div><h3>অভিযোগের বিবরণ</h3><div class="complaint-description">${esc(data.fields.description)}</div><h3>সংযুক্ত নথি</h3><ul class="document-list">${data.documents.map(doc=>`<li><a href="${esc(doc.url)}">↓ ${esc(doc.original_name)}</a><small> · ${(doc.size/1024).toFixed(1)} KB</small></li>`).join('')||'<li>কোনো নথি সংযুক্ত করা হয়নি।</li>'}</ul>`;
  el('complaintState').value=data.status;el('complaintNote').value=data.admin_note;el('complaintNotice').hidden=true;el('complaintDialog').showModal();loadComplaints();
 }catch(err){message(err.message,true)}
}
function setupEvidence(){
 const nav=document.querySelector('.tabs'), button=document.createElement('button');button.dataset.tab='evidence';button.textContent='Evidence review';nav.insertBefore(button,nav.children[3]||null);
 const choose=(inputId,listId,url,key)=>{let timer;el(inputId).addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(async()=>{const query=el(inputId).value.trim();if(query.length<(key==='khatian_id'?2:1))return;try{const data=await api(url+'?q='+encodeURIComponent(query));el(listId).innerHTML=data.records.map(row=>`<option value="${esc(row[key])}" label="${esc(row.label)}"></option>`).join('')}catch(error){message(error.message,true)}},250)})};
 choose('evidenceKhatian','evidenceKhatianList','/api/admin/evidence/khatian-options','khatian_id');choose('evidenceDeed','evidenceDeedList','/api/admin/evidence/deed-options','deed_id');
 el('evidenceForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{const data=await api('/api/admin/evidence/reviews',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});renderEvidence(data);loadEvidenceHistory();message('Evidence comparison saved.')})});
}
function setupLineOcr(){
 if(el('lineOcrBox'))return;
 const box=document.createElement('div');box.id='lineOcrBox';box.className='line-ocr';box.innerHTML='<strong>Experimental line OCR</strong><p class="hint">Enter the image-pixel crop for one printed text line. The result is a suggestion only; review it against the image before publishing.</p><div class="line-crop"><label>X<input id="lineOcrX" type="number" min="0" value="0"></label><label>Y<input id="lineOcrY" type="number" min="0" value="0"></label><label>Width<input id="lineOcrW" type="number" min="16" value="200"></label><label>Height<input id="lineOcrH" type="number" min="8" value="40"></label></div><button id="readSelectedLine" type="button">Read selected line</button><output id="lineOcrResult"></output>';
 el('reviewImage').insertAdjacentElement('afterend',box);
 el('readSelectedLine').addEventListener('click',()=>busy(box,async()=>{const image=el('reviewImage');if(!image.naturalWidth)throw Error('Wait for the uploaded image to load.');const rect={x:+el('lineOcrX').value,y:+el('lineOcrY').value,width:+el('lineOcrW').value,height:+el('lineOcrH').value};if(rect.x<0||rect.y<0||rect.width<16||rect.height<8||rect.x+rect.width>image.naturalWidth||rect.y+rect.height>image.naturalHeight)throw Error('Use a crop inside the original image dimensions.');if(!window.SutroLineOcr)throw Error('OCR reader is not ready.');el('lineOcrResult').textContent='Reading…';try{const text=await window.SutroLineOcr.read(image,rect);el('lineOcrResult').textContent=text||'No text suggestion.'}catch(error){el('lineOcrResult').textContent='Reader unavailable: '+error.message}}));
}
function renderEvidence(data){
 const result=el('evidenceResult');const badge=data.outcome==='consistent'?'match':'review';
 result.hidden=false;result.innerHTML=`<div class="evidence-head"><strong>${esc(data.id)}</strong><span class="evidence-state ${badge}">${esc(data.outcome==='consistent'?'Fields consistent':'Needs human review')}</span></div><p class="hint">${esc(data.notice)}</p><div class="table-wrap"><table><thead><tr><th>Field</th><th>Signed deed</th><th>Khatian</th><th>Result</th></tr></thead><tbody>${data.fields.map(row=>`<tr><td>${esc(row.field)}</td><td>${esc(row.deed||'—')}</td><td>${esc(row.khatian||'—')}</td><td><span class="evidence-state ${esc(row.state)}">${esc(row.state)}</span></td></tr>`).join('')}</tbody></table></div>${data.history?.length?`<details><summary>Linked khatian history</summary><pre>${esc(JSON.stringify(data.history,null,2))}</pre></details>`:''}`;
}
async function loadEvidenceHistory(){
 if(!adminActive)return;try{const data=await api('/api/admin/evidence/reviews');el('evidenceHistory').innerHTML=data.reviews.length?`<ul class="evidence-history">${data.reviews.map(row=>`<li><strong>${esc(row.id)}</strong> · ${esc(row.deed_id)} ↔ ${esc(row.khatian_id)} <span class="evidence-state ${esc(row.outcome)}">${esc(row.outcome)}</span><small>${esc(row.created_at)}</small></li>`).join('')}</ul>`:'No comparison has been saved yet.'}catch(error){el('evidenceHistory').textContent=error.message}
}
el('complaintFilter').addEventListener('submit',event=>{event.preventDefault();complaintPage=1;loadComplaints()});
el('complaintStatusFilter').addEventListener('change',()=>{complaintPage=1;loadComplaints()});
el('refreshComplaints').addEventListener('click',loadComplaints);
el('complaintPrev').addEventListener('click',()=>{complaintPage--;loadComplaints()});
el('complaintNext').addEventListener('click',()=>{complaintPage++;loadComplaints()});
el('complaintRows').addEventListener('click',event=>{const button=event.target.closest('[data-complaint]');if(button)openComplaint(button.dataset.complaint)});
el('closeComplaint').addEventListener('click',()=>{complaintDetailRequest++;el('complaintDialog').close()});
el('saveComplaint').addEventListener('click',()=>busy(el('complaintDialog'),async()=>{
 if(!currentComplaint)return;
 await api('/api/admin/complaints/'+encodeURIComponent(currentComplaint.id),{method:'PATCH',body:JSON.stringify({status:el('complaintState').value,admin_note:el('complaintNote').value})});
 el('complaintDialog').close();message('অভিযোগের আপডেট সংরক্ষিত হয়েছে।');loadComplaints();
}));
setInterval(()=>{if(adminActive&&!document.hidden){refreshComplaintBadge();if(!el('complaintsPanel').hidden&&!el('complaintDialog').open)loadComplaints()}},60000);
loadSession().catch(error=>message(error.message,true));
})();
