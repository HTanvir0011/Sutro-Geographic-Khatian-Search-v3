(()=>{'use strict';
const el=id=>document.getElementById(id),form=el('complaintForm');
let csrf='',places=[],areaRequest=0;
function error(text){el('complaintError').textContent=text;el('complaintError').hidden=!text}
async function json(url,options={}){const response=await fetch(url,options);let data;try{data=await response.json()}catch{throw Error('সার্ভার থেকে সঠিক উত্তর পাওয়া যায়নি।')}if(!response.ok){const err=Error(data.error||'অভিযোগ জমা দেওয়া যায়নি।');err.status=response.status;throw err}return data}
function options(id,values){const list=el(id);list.replaceChildren();for(const value of [...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'bn'))){const option=document.createElement('option');option.value=value;list.append(option)}}
async function token(){csrf=(await json('/api/complaints/session')).csrf;el('submitComplaint').disabled=false;el('trackButton').disabled=false}
json('/api/khatian/filters').then(data=>{places=data.places||[];options('complaintDistricts',places.map(p=>p.district))}).catch(()=>{});
form.elements.district.addEventListener('change',()=>{areaRequest++;form.elements.upazila.value='';form.elements.mouza.value='';options('complaintMouzas',[]);options('complaintUpazilas',places.filter(p=>p.district.normalize('NFC')===form.elements.district.value.normalize('NFC')).map(p=>p.upazila))});
form.elements.upazila.addEventListener('change',async()=>{const requestId=++areaRequest;options('complaintMouzas',[]);form.elements.mouza.value='';const district=form.elements.district.value,upazila=form.elements.upazila.value;if(!district||!upazila)return;try{const data=await json('/api/khatian/filters?'+new URLSearchParams({district,upazila}));if(requestId===areaRequest)options('complaintMouzas',data.places.map(p=>p.mouza))}catch{/* Free-text locations remain available. */}});
el('complaintDocuments').addEventListener('change',()=>{const files=[...el('complaintDocuments').files];el('documentSummary').textContent=files.map(f=>f.name).join(' · ');error('')});
form.addEventListener('submit',async event=>{event.preventDefault();error('');const files=[...el('complaintDocuments').files];if(files.length>5||files.some(f=>f.size>5*1024*1024)||files.reduce((size,f)=>size+f.size,0)>10*1024*1024){error('সর্বোচ্চ ৫টি নথি দিন। প্রতিটি ৫ MB এবং সব মিলে ১০ MB এর মধ্যে রাখুন।');return}
 el('submitComplaint').disabled=true;el('complaintProgress').textContent='অভিযোগ ও নথি জমা হচ্ছে…';
 try{const data=await json('/api/complaints',{method:'POST',headers:{'X-CSRF-Token':csrf},body:new FormData(form)});el('complaintReceipt').textContent=data.receipt;el('complaintSuccess').hidden=false;form.hidden=true;form.reset();el('documentSummary').textContent='';el('complaintSuccess').scrollIntoView({behavior:'smooth',block:'start'})}
 catch(err){error(err.message);if(err.status===403)try{await token();error('সেশন নতুন করা হয়েছে। তথ্য রাখা আছে—আবার জমা দিন।')}catch{error('পেজ reload করে আবার চেষ্টা করুন।')}}
 finally{el('submitComplaint').disabled=false;el('complaintProgress').textContent=''}
});
el('newComplaint').addEventListener('click',()=>{el('complaintSuccess').hidden=true;form.hidden=false;el('complaintReceipt').textContent='';options('complaintUpazilas',[]);options('complaintMouzas',[]);form.scrollIntoView({behavior:'smooth'})});
el('trackForm').addEventListener('submit',async event=>{event.preventDefault();el('trackingResult').hidden=true;el('trackingError').hidden=true;el('trackButton').disabled=true;
 try{const data=await json('/api/complaints/track',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({receipt:el('trackingNumber').value.trim()})});
  const result=el('trackingResult');result.replaceChildren();
  for(const [label,value] of [['অভিযোগ নম্বর',data.receipt],['বর্তমান অবস্থা',data.status_label],['জমা দেওয়ার সময়',data.submitted_at],['সর্বশেষ আপডেট',data.updated_at]]){const paragraph=document.createElement('p');const strong=document.createElement('strong');strong.textContent=label+': ';paragraph.append(strong, label.includes('সময়')||label==='সর্বশেষ আপডেট'?new Date(value).toLocaleString('bn-BD',{timeZone:'Asia/Dhaka'}):value);result.append(paragraph)}
  result.hidden=false;
 }catch(err){el('trackingError').textContent=err.message;el('trackingError').hidden=false;if(err.status===403)try{await token();el('trackingError').textContent='সেশন নতুন করা হয়েছে। আবার অবস্থা দেখুন।'}catch{}}
 finally{el('trackButton').disabled=false}
});
el('trackSubmitted').addEventListener('click',()=>{el('trackingNumber').value=el('complaintReceipt').textContent;el('track').scrollIntoView({behavior:'smooth',block:'start'});el('trackForm').requestSubmit()});
token().catch(()=>error('অভিযোগ ফর্ম চালু করা যায়নি। পেজ reload করুন।'));
})();
