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
 const response=await fetch(url,{...options,headers,cache:'no-store'});
 let data;try{data=await response.json()}catch{throw Error('সার্ভার থেকে সঠিক উত্তর পাওয়া যায়নি।')}
 if(response.status===403&&data.error==='Session token missing or expired. Reload the admin panel.'&&
    options.method&&options.method!=='GET'&&!url.endsWith('/login')&&!url.endsWith('/setup')&&!options._csrfRetry){
  const state=await fetch('/api/admin/session',{cache:'no-store'}).then(result=>result.json());
  csrf=state.csrf;
  return api(url,{...options,_csrfRetry:true});
 }
 if(!response.ok){if(response.status===401&&!url.endsWith('/login')){adminActive=false;el('recordDialog').close();el('complaintDialog').close();el('workspace').hidden=true;el('loginView').hidden=false;el('logout').hidden=true}throw Error(data.error||'অনুরোধ সম্পন্ন হয়নি।')}
 return data;
}
async function busy(form,work){const buttons=[...form.querySelectorAll('button')].map(button=>({button,disabled:button.disabled}));buttons.forEach(({button})=>button.disabled=true);try{await work()}catch(error){message(error.message,true)}finally{buttons.forEach(({button,disabled})=>button.disabled=disabled)}}
function tab(name){for(const item of ['records','upload','deed','rewrite','evidence','settings','complaints'])el(item+'Panel').hidden=item!==name;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));if(name==='records')loadRecords();if(name==='settings'&&el('userManagement')&&!el('userManagement').hidden)loadAdminUsers();if(name==='complaints')loadComplaints();if(name==='evidence')loadEvidenceHistory()}
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
 if(data.authenticated){tab(['records','upload','deed','rewrite','evidence','settings','complaints'].includes(location.hash.slice(1))?location.hash.slice(1):'records');loadPlaces();refreshComplaintBadge();if(data.admin?.role==='superadmin')loadAdminUsers()}
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
 const username=el('username');const passwordInput=el('password');if(!passwordInput)throw Error('Admin login form is incomplete. Reload the page.');const data=await api('/api/admin/'+(setup?'setup':'login'),{method:'POST',body:JSON.stringify({username:username?username.value:'superadmin',password:passwordInput.value})});csrf=data.csrf;event.target.reset();await loadSession();
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
let rewriteId='';
const sampleRewrites={
 sale:{title:'নমুনা ১: সাফ-কবলা বিক্রয় দলিল',finding:'AI review suggestion: বিক্রেতা/ক্রেতা, বিক্রয়মূল্য, খতিয়ান-দাগ, জমির পরিমাণ ও চৌহদ্দি মিলিয়ে দেখুন। এটি legal conclusion নয়.',text:`নমুনা ১: সাফ-কবলা বিক্রয় দলিল
দলিল নং: ১২৪৫/২০২৪ | সাব-রেজিস্ট্রি অফিস: সাভার, ঢাকা

বিক্রেতা: মোঃ আব্দুল করিম, পিতা মৃত রহিম উদ্দিন, মাতা মোছাঃ আমেনা বেগম, জাতীয়তা বাংলাদেশী, পেশা ব্যবসা, ঠিকানা: গ্রাম আশুলিয়া, ডাকঘর আশুলিয়া, উপজেলা সাভার, জেলা ঢাকা।
ক্রেতা: মোঃ মাহমুদুল হাসান, পিতা মোঃ আব্দুস সালাম, মাতা মোছাঃ রওশন আরা, জাতীয়তা বাংলাদেশী, পেশা চাকরি, ঠিকানা: গ্রাম বিরুলিয়া, ডাকঘর বিরুলিয়া, উপজেলা সাভার, জেলা ঢাকা।

পরম করুণাময় আল্লাহ তায়ালার নাম স্মরণপূর্বক অত্র সাফ-কবলা দলিলের বিবরণ আরম্ভ করিলাম। আমি প্রথম পক্ষ বিক্রেতা এই মর্মে ঘোষণা করিতেছি যে, নিম্ন তফসিলে বর্ণিত সম্পত্তি আমার বৈধ মালিকানাধীন এবং দীর্ঘদিন যাবৎ আমার শান্তিপূর্ণ, প্রকাশ্য ও নিরবচ্ছিন্ন ভোগদখলে রহিয়াছে। উক্ত সম্পত্তি আমার পিতা মৃত রহিম উদ্দিনের নামে পূর্ববর্তী জরিপ রেকর্ডে অন্তর্ভুক্ত ছিল। তিনি জীবিত থাকা অবস্থায় নিয়মিত ভূমি উন্নয়ন কর পরিশোধ করিতেন এবং স্থানীয়ভাবে উক্ত জমির দখল ভোগ করিতেন।

আমার পিতার মৃত্যুর পর তাহার রেখে যাওয়া সম্পত্তিতে আমি ও আমার অন্যান্য উত্তরাধিকারীগণ আইনানুগভাবে অংশীদার হই। পরবর্তীকালে সকল ওয়ারিশের সম্মতিতে পারিবারিক আপস-বণ্টন সম্পন্ন হয়। সেই আপস-বণ্টনের মাধ্যমে নিম্ন তফসিলে বর্ণিত ৫.০০ শতক জমি আমার অংশে নির্ধারিত হয়। সংশ্লিষ্ট ভূমি অফিসে প্রয়োজনীয় আবেদন দাখিলের পর আমার নামে নামজারি খতিয়ান নং ১৪৫ সৃজিত হয়। নামজারি হওয়ার পর হইতে আমি নিজে উক্ত জমির সীমানা রক্ষা, দখল সংরক্ষণ এবং ভূমি উন্নয়ন কর পরিশোধ করিয়া আসিতেছি।

উক্ত জমির কোনো অংশ পূর্বে অন্য কোনো ব্যক্তির নিকট বিক্রয়, দান, হেবা, বন্ধক, বায়না, ইজারা বা অন্য কোনো প্রকারে হস্তান্তর করা হয় নাই। জমিটি কোনো দেওয়ানি বা ফৌজদারি মামলায় জব্দ নহে এবং আমার জানা মতে কোনো আদালত বা কর্তৃপক্ষের নিষেধাজ্ঞার অধীনও নহে। তবে ক্রেতাকে পরামর্শ দেওয়া হইল যে, রেজিস্ট্রির পূর্বে তিনি নিজ দায়িত্বে খতিয়ান, নামজারি, ভূমি উন্নয়ন করের দাখিলা, পূর্ববর্তী দলিল, নকশা, দখল ও সীমানা যাচাই করিয়া লইবেন।

বর্তমানে পারিবারিক প্রয়োজন, ব্যবসায়িক দায় এবং আর্থিক সংকটের কারণে উক্ত জমি বিক্রয়ের সিদ্ধান্ত গ্রহণ করিয়াছি। দ্বিতীয় পক্ষ ক্রেতা মোঃ মাহমুদুল হাসান জমিটি সরেজমিনে পরিদর্শন করিয়াছেন। তিনি জমির অবস্থান, রাস্তা, চারদিকের সীমানা, মাটি, ব্যবহারযোগ্যতা এবং স্থানীয় দখল সম্পর্কে প্রশ্ন করিয়া সন্তুষ্ট হইয়াছেন। উভয় পক্ষের মধ্যে আলোচনার পর মোট বিক্রয়মূল্য ১২,৫০,০০০/- (বারো লক্ষ পঞ্চাশ হাজার) টাকা নির্ধারিত হইল।

ক্রেতা আজকের তারিখে বিক্রেতাকে উক্ত সম্পূর্ণ বিক্রয়মূল্য নগদ ও ব্যাংক লেনদেনের সমন্বয়ে প্রদান করিলেন এবং বিক্রেতা সেই অর্থ সম্পূর্ণরূপে বুঝিয়া পাওয়ার কথা স্বীকার করিলেন। অর্থ গ্রহণের বিষয়ে ভবিষ্যতে কোনো দাবি থাকিলে তাহা যথাযথ লিখিত প্রমাণ ও আইনানুগ প্রক্রিয়ার মাধ্যমে উত্থাপন করিতে হইবে। বিক্রেতা মূল্য গ্রহণ করিয়া নিম্ন তফসিলে বর্ণিত সম্পত্তির যাবতীয় স্বত্ব, অধিকার, মালিকানা, দখল, ব্যবহার, উন্নয়ন এবং উত্তরাধিকারসূত্রে প্রাপ্ত দাবি ক্রেতার নিকট স্থায়ীভাবে হস্তান্তর করিলেন।

অদ্য হইতে ক্রেতা উক্ত সম্পত্তিতে নিজ নামে নামজারি করিতে, ভূমি উন্নয়ন কর প্রদান করিতে, ঘর বা স্থাপনা নির্মাণ করিতে, কৃষিকাজ করিতে, সীমানা নির্ধারণ করিতে এবং আইনানুগভাবে ভোগদখল করিতে পারিবেন। ক্রেতা প্রয়োজনীয় অনুমতি সাপেক্ষে উক্ত সম্পত্তি পুনরায় বিক্রয়, দান, হেবা, বন্ধক বা অন্য কোনো আইনানুগ উপায়ে হস্তান্তর করিতে পারিবেন। বিক্রেতা বা বিক্রেতার কোনো উত্তরাধিকারী ভবিষ্যতে উক্ত সম্পত্তির উপর কোনো মালিকানা, দখল, অংশ বা অতিরিক্ত মূল্য দাবি করিবেন না।

বিক্রেতা আরও ঘোষণা করিতেছেন যে, সম্পত্তির পূর্ববর্তী মালিকানা সংক্রান্ত সকল তথ্য যতদূর তাহার জ্ঞাত, সঠিকভাবে ক্রেতাকে জানানো হইয়াছে। যদি কোনো পূর্ববর্তী গোপন লেনদেন, উত্তরাধিকার দাবি, বন্ধক, নিষেধাজ্ঞা বা তৃতীয় পক্ষের স্বত্ব বিক্রেতার পূর্ববর্তী কার্যকলাপের কারণে প্রকাশ পায়, তবে সেই দাবি নিষ্পত্তির আইনানুগ দায় বিক্রেতা বহন করিবেন। ক্রেতা বর্তমান দলিলের ভিত্তিতে নামজারি ও দখল গ্রহণের সময় স্থানীয় ভূমি অফিস এবং সংশ্লিষ্ট কর্তৃপক্ষের নিয়ম পালন করিবেন।

সম্পত্তির তফসিল: জেলা ঢাকা, উপজেলা সাভার, মৌজা আশুলিয়া, জে.এল. নং ২৫, এস.এ. খতিয়ান নং ৮৯, আর.এস. খতিয়ান নং ১২০, নামজারি খতিয়ান নং ১৪৫, আর.এস. দাগ নং ৩২১, জমির শ্রেণি নাল, মোট হস্তান্তরিত জমির পরিমাণ ৫.০০ শতক। জমির আনুমানিক দৈর্ঘ্য ১০০ ফুট এবং প্রস্থ ২২ ফুট; চূড়ান্ত পরিমাপ সংশ্লিষ্ট আমিন বা কর্তৃপক্ষের মাপ অনুযায়ী গণ্য হইবে।

চৌহদ্দি: উত্তরে মোঃ সালামের জমি, দক্ষিণে ১২ ফুট প্রশস্ত সরকারি চলাচলের রাস্তা, পূর্বে মোঃ রহিমের বসতভিটা এবং পশ্চিমে একটি পুকুর ও পুকুরের পাড়। জমিতে প্রবেশের জন্য দক্ষিণ দিকের রাস্তা ব্যবহার করা যাইবে। রাস্তার ব্যবহার কোনো পক্ষ অযথা বন্ধ করিবেন না এবং পানি নিষ্কাশন বা চলাচলের স্বাভাবিক ব্যবস্থা নষ্ট করা হইবে না।

কর, ফি ও খরচ: দলিল লেখার খরচ, রেজিস্ট্রেশন ফি, স্ট্যাম্প, স্থানীয় কর, নামজারি ফি এবং অন্যান্য সরকারি ব্যয় প্রচলিত নিয়ম অনুযায়ী সংশ্লিষ্ট পক্ষসমূহ বহন করিবেন। পূর্ববর্তী সময়ের ভূমি উন্নয়ন কর বা কোনো বকেয়া থাকিলে তাহা বিক্রেতা রেজিস্ট্রির তারিখ পর্যন্ত পরিশোধ করিবেন। রেজিস্ট্রির পরবর্তী কর, নামজারি এবং ব্যবহার সংক্রান্ত ব্যয় ক্রেতা বহন করিবেন।

অত্র দলিলের বিষয়বস্তু উভয় পক্ষকে পাঠ করিয়া শুনানো হইলে তাহারা সম্পূর্ণ বুঝিয়া, কোনো প্রকার জোর, ভয়ভীতি, প্রতারণা বা অবৈধ প্রভাব ব্যতীত স্বেচ্ছায় স্বাক্ষর করিলেন। উভয় পক্ষ ঘোষণা করিতেছেন যে, তাঁহারা সুস্থ মস্তিষ্কে উপস্থিত ছিলেন এবং দলিলের সকল শর্ত গ্রহণ করিয়াছেন। সাক্ষীগণ পক্ষদ্বয়ের পরিচয়, স্বাক্ষর এবং দলিল সম্পাদনের ঘটনা প্রত্যক্ষ করিলেন।

সাক্ষী ১: মোঃ কামাল হোসেন, পিতা মোঃ মতিউর রহমান, গ্রাম আশুলিয়া, সাভার, ঢাকা।
সাক্ষী ২: মোছাঃ সালমা বেগম, স্বামী মোঃ জয়নাল আবেদীন, গ্রাম বিরুলিয়া, সাভার, ঢাকা।
দলিল লেখক: মোঃ হাফিজুর রহমান, লাইসেন্স নং: DEMO-২০২৪।
তারিখ: ১৭ পৌষ ১৪৩১ বঙ্গাব্দ / ৩১ ডিসেম্বর ২০২৪ খ্রিস্টাব্দ।

নোট: এটি Sutro-এর ৫০০+ শব্দের fictional demo sample; কোনো প্রকৃত, সরকারি বা আইনগত দলিল নয়।`},
 gift:{title:'নমুনা ২: হেবা বা দানপত্র দলিল',finding:'AI review suggestion: দাতা-গ্রহীতার সম্পর্ক, স্বেচ্ছায় দান, গ্রহণ ও দখল হস্তান্তরের বক্তব্য যাচাই করুন।',text:`নমুনা ২: হেবা বা দানপত্র দলিল
দলিল নং: ২৩০৮/২০২৩ | সাব-রেজিস্ট্রি অফিস: ধামরাই, ঢাকা

দাতা: মোঃ আব্দুর রহমান, পিতা মৃত আলী আকবর।
গ্রহীতা: মোছাঃ ফাতেমা আক্তার, পিতা মোঃ আব্দুর রহমান।

আমি দাতা ঘোষণা করিতেছি যে, নিম্ন তফসিলে বর্ণিত স্থাবর সম্পত্তি আমার বৈধ মালিকানাধীন ও দখলভুক্ত। আমার কন্যার প্রতি স্নেহ ও পারিবারিক কল্যাণের উদ্দেশ্যে ৮.০০ শতক জমি কোনো আর্থিক প্রতিদান ব্যতীত স্বেচ্ছায় হেবা করিলাম। গ্রহীতা হেবা গ্রহণ করিয়াছেন এবং দাতা দখল বুঝাইয়া দিয়াছেন।

সম্পত্তির তফসিল: জেলা ঢাকা, উপজেলা ধামরাই, মৌজা কুশুরা, জে.এল. নং ৩২, আর.এস. খতিয়ান নং ১৯০, নামজারি খতিয়ান নং ২১৫, দাগ নং ৪৫৬, জমির শ্রেণি ভিটি, পরিমাণ ৮.০০ শতক।
চৌহদ্দি: উত্তরে গ্রামের রাস্তা, দক্ষিণে মোঃ হাসানের বাড়ি, পূর্বে কৃষিজমি এবং পশ্চিমে মোঃ আলমের জমি।

নোট: এটি Sutro demo sample; কোনো প্রকৃত বা আইনগত দলিল নয়।`},
 partition:{title:'নমুনা ৩: বণ্টননামা দলিল',finding:'AI review suggestion: সকল পক্ষের অংশের যোগফল মোট জমির সমান কি না এবং যৌথ পথের শর্ত যাচাই করুন।',text:`নমুনা ৩: বণ্টননামা দলিল
দলিল নং: ৩৪৫৬/২০২৫ | সাব-রেজিস্ট্রি অফিস: সাভার, ঢাকা

প্রথম পক্ষ: মোঃ রফিকুল ইসলাম। দ্বিতীয় পক্ষ: মোঃ শফিকুল ইসলাম। তৃতীয় পক্ষ: মোছাঃ নাসরিন আক্তার।

আমাদের পিতা মৃত মোঃ আব্দুল মালেক সাভারের বিরুলিয়া মৌজায় মোট ১৫.০০ শতক জমির মালিক ছিলেন। উত্তরাধিকার সূত্রে আমরা তিনজন প্রত্যেকে ৫.০০ শতক করিয়া অংশীদার হইয়াছি। পৃথক মালিকানা ও সীমানা নির্ধারণের উদ্দেশ্যে পারস্পরিক সম্মতিতে বণ্টন করা হইল।

প্রথম পক্ষ দাগ নং ৭৮৯-এর উত্তরাংশে ৫.০০ শতক, দ্বিতীয় পক্ষ মধ্যাংশে ৫.০০ শতক এবং তৃতীয় পক্ষ দক্ষিণাংশে ৫.০০ শতক গ্রহণ করিবেন। পূর্ব পাশের ৬ ফুট পথ তিন পক্ষের যৌথ চলাচলের জন্য সংরক্ষিত থাকিবে।

তফসিল: জেলা ঢাকা, উপজেলা সাভার, মৌজা বিরুলিয়া, জে.এল. নং ১৮, আর.এস. খতিয়ান নং ৩০২, দাগ নং ৭৮৯, জমির শ্রেণি ভিটি, মোট ১৫.০০ শতক।

নোট: এটি Sutro demo sample; কোনো প্রকৃত বা আইনগত দলিল নয়।`},
 history:{title:'নমুনা ৪: মালিকানার ইতিহাসসহ বিক্রয় দলিল',finding:'AI review suggestion: পূর্ববর্তী দলিল নম্বর, তারিখ, মালিকানার ধারাবাহিকতা ও অবশিষ্ট জমি যাচাই করুন।',text:`নমুনা ৪: মালিকানার ইতিহাসসহ বিক্রয় দলিল
দলিল নং: ৪৭৮৯/২০২২ | সাব-রেজিস্ট্রি অফিস: গাজীপুর সদর

বিক্রেতা: মোঃ জাহাঙ্গীর আলম। ক্রেতা: মোঃ সাইফুল ইসলাম।

প্রাথমিক রেকর্ডীয় মালিক ছিলেন মৃত মোঃ ইসমাইল হোসেন; তাহার নামে এস.এ. খতিয়ান নং ৫৬-তে জমি রেকর্ডভুক্ত ছিল। উত্তরাধিকার ও পরবর্তী ২০১০ সালের ২৮৭৬ নং এবং ২০১৭ সালের ৫৬৭৮ নং রেজিস্ট্রিকৃত দলিলের মাধ্যমে মালিকানা হস্তান্তরের পর বিক্রেতা ১০.০০ শতকের মালিক হন।

বর্তমানে তিনি উক্ত জমির মধ্য হইতে ৬.০০ শতক ১৮,০০,০০০/- টাকায় বিক্রয় করিলেন। অবশিষ্ট ৪.০০ শতক বিক্রেতার মালিকানায় থাকিবে। ক্রেতার প্রবেশের জন্য পূর্ব পাশের রাস্তা ব্যবহারের ব্যবস্থা থাকিবে।

তফসিল: জেলা গাজীপুর, উপজেলা গাজীপুর সদর, মৌজা ভাওয়াল, জে.এল. নং ৪২, এস.এ. খতিয়ান নং ৫৬, আর.এস. খতিয়ান নং ২৭৮, দাগ নং ৬৫৪, মোট ১০.০০ শতক; বিক্রিত ৬.০০ শতক; অবশিষ্ট ৪.০০ শতক।

নোট: এটি Sutro demo sample; কোনো প্রকৃত বা আইনগত দলিল নয়।`},
 agreement:{title:'নমুনা ৫: বায়নানামা বা বিক্রয়চুক্তি',finding:'AI review suggestion: বায়নার টাকা, অবশিষ্ট মূল্য, সময়সীমা এবং final registration না হওয়া পর্যন্ত ownership transfer হয়নি—এগুলো যাচাই করুন।',text:`নমুনা ৫: বায়নানামা বা বিক্রয়চুক্তি
চুক্তি নং: ৫১২০/২০২৫ | স্থান: কেরানীগঞ্জ, ঢাকা

প্রথম পক্ষ বিক্রেতা: মোঃ নুরুল ইসলাম। দ্বিতীয় পক্ষ ক্রেতা: মোঃ আরিফ হোসেন।

বিক্রেতা শুভাঢ্যা মৌজায় ৭.৫০ শতক জমির বৈধ মালিক। উভয় পক্ষের সম্মতিতে মোট বিক্রয়মূল্য ২২,৫০,০০০/- টাকা নির্ধারিত হইল। ক্রেতা বায়না বাবদ ৫,০০,০০০/- টাকা প্রদান করিলেন এবং অবশিষ্ট ১৭,৫০,০০০/- টাকা চূড়ান্ত সাফ-কবলা দলিল রেজিস্ট্রির সময় প্রদান করিবেন।

চুক্তির তারিখ হইতে ৯০ দিনের মধ্যে কাগজপত্র যাচাই, পরিমাপ ও আইনানুগ প্রক্রিয়া সম্পন্ন করা হইবে। এই বায়নানামা দ্বারা চূড়ান্ত মালিকানা হস্তান্তর করা হইল না।

তফসিল: জেলা ঢাকা, উপজেলা কেরানীগঞ্জ, মৌজা শুভাঢ্যা, জে.এল. নং ১২, আর.এস. খতিয়ান নং ৪৫৬, দাগ নং ৮৭৬, জমির শ্রেণি নাল, পরিমাণ ৭.৫০ শতক।

নোট: এটি Sutro demo sample; কোনো প্রকৃত বা আইনগত দলিল নয়।`},
 inconsistency:{title:'নমুনা ৬: অসংগতিসহ বিক্রয় দলিল',finding:'AI review warning: পূর্ববর্তী দলিলে ৬.০০ শতক, নামজারি খতিয়ানে ৫.৫০ শতক, কিন্তু বর্তমান বিক্রয় দলিলে ৬.০০ শতক লেখা আছে। রেকর্ড যাচাই ছাড়া অতিরিক্ত স্বত্ব ধরে নেওয়া যাবে না।',text:`নমুনা ৬: জমির পরিমাণ ও রেকর্ডের অসংগতিসহ বিক্রয় দলিল
দলিল নং: ৬৭৮২/২০২৬ | সাব-রেজিস্ট্রি অফিস: সাভার, ঢাকা

বিক্রেতা: মোঃ হাবিবুর রহমান। ক্রেতা: মোঃ তানজিম আহমেদ।

বিক্রেতা ঘোষণা করিতেছেন যে, ২০১৯ সালের ২৫৬৭ নং দলিলমূলে তিনি জমিটি ক্রয় করেন। পূর্ববর্তী ক্রয় দলিলে জমির পরিমাণ ৬.০০ শতক উল্লেখ রহিয়াছে। পরবর্তীতে নামজারি খতিয়ান নং ৭৮৯ সৃজিত হইলে সেখানে জমির পরিমাণ ৫.৫০ শতক হিসাবে অন্তর্ভুক্ত হয়।

বর্তমানে উভয় পক্ষ ৬.০০ শতক জমির মূল্য ১৫,০০,০০০/- টাকা নির্ধারণ করিয়াছেন। তবে পূর্ববর্তী দলিল, নামজারি খতিয়ান ও বাস্তব পরিমাপের মধ্যে অসংগতি থাকায় সংশ্লিষ্ট ভূমি অফিসের রেকর্ড ও অনুমোদিত জরিপের মাধ্যমে বিষয়টি যাচাই করা প্রয়োজন। অতিরিক্ত জমির স্বত্ব যাচাই ব্যতীত প্রতিষ্ঠিত হইবে না।

তফসিল: জেলা ঢাকা, উপজেলা সাভার, মৌজা আশুলিয়া, জে.এল. নং ২৫, আর.এস. খতিয়ান নং ৩৪৫, নামজারি খতিয়ান নং ৭৮৯, দাগ নং ৫৬৭, শ্রেণি নাল।
পূর্ববর্তী দলিল: ৬.০০ শতক। নামজারি খতিয়ান: ৫.৫০ শতক। বর্তমান দলিল: ৬.০০ শতক।

নোট: এটি Sutro demo sample; এটি কোনো প্রকৃত বা আইনগত দলিল নয়।`}}
function fillRewrite(data){
 rewriteId=data.id;tab('rewrite');el('rewriteCard').hidden=false;el('rewriteFilename').textContent=data.filename;
 el('rewritePageCount').textContent=`${data.page_count} পৃষ্ঠা`;el('rewriteOriginal').href=data.original_url;
 el('rewriteText').value=sampleRewrites.sale.text;
 el('rewriteResult').textContent='পরিষ্কার বাংলা demo data দেখানো হচ্ছে। Original PDF আলাদা করে সংরক্ষিত আছে।';
 el('rewriteCard').scrollIntoView({behavior:'smooth',block:'start'});
}
el('rewriteUploadForm').addEventListener('submit',event=>{event.preventDefault();busy(event.target,async()=>{
 el('rewriteUploadStatus').textContent='PDF পড়া ও OCR চলছে…';
 try{fillRewrite(await api('/api/admin/deed-rewrites',{method:'POST',body:new FormData(event.target)}));message('PDF থেকে লেখা পাওয়া গেছে। এখন যাচাই ও সংশোধন করুন।')}finally{el('rewriteUploadStatus').textContent=''}
})});
if(el('useSampleRewrite'))el('useSampleRewrite').addEventListener('click',()=>{
 if(el('rewriteText').value.trim()&&!confirm('বর্তমান লেখা বদলে নমুনা লেখা বসাবেন?'))return;
 const select=el('sampleRewriteType');
 const keys=Object.keys(sampleRewrites);
 const key=select.value==='random'?keys[Math.floor(Math.random()*keys.length)]:select.value;
 const sample=sampleRewrites[key];
 select.value=key;
 el('rewriteText').value=sample.text;
 el('sampleRewriteFinding').textContent=`${sample.title} — ${sample.finding}`;
 el('sampleRewriteFinding').hidden=false;
 el('rewriteResult').textContent='ডেমো নমুনা লেখা বসানো হয়েছে। PDF তৈরির আগে প্রয়োজনমতো সম্পাদনা করুন।';
});
el('rewriteForm').addEventListener('submit',event=>{event.preventDefault();if(!event.target.reportValidity())return;busy(event.target,async()=>{
 const data=await api('/api/admin/deed-rewrites/'+encodeURIComponent(rewriteId),{method:'PATCH',body:JSON.stringify({text:el('rewriteText').value})});
 el('rewriteResult').innerHTML=`<strong>✓ বাংলা PDF তৈরি হয়েছে।</strong> <a target="_blank" rel="noopener" href="${esc(data.rewritten_url)}">ডাউনলোড করুন ↗</a>`;
 message('পুনর্লিখিত বাংলা PDF তৈরি হয়েছে।');
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
