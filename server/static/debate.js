const root = document.querySelector('#debate');
const form = document.querySelector('#debate-form');
const button = document.querySelector('#debate-start');
const statusText = document.querySelector('#debate-status');
const progress = document.querySelector('#debate-progress');
const output = document.querySelector('#debate-output');
const stages = {discover:'독립 쟁점 탐색',merge:'쟁점 교차 확인',opening:'독립 입장',reply:'교차 반론',draft:'수정안 초안',review:'역할별 검토',final:'수정 가이드라인'};
const roles = {student:'학생',faculty:'교수',administration:'학사행정',moderator:'정리'};
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
async function post(url,values){
 const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:new URLSearchParams(values)});
 const data=await response.json().catch(()=>({}));
 if(!response.ok){if(data.calls)render(data);throw Error(data.error||'요청에 실패했습니다.');}return data;
}
function render(data){
 output.replaceChildren();progress.hidden=false;progress.value=data.cursor;
 if(data.issues.length){output.append(node('h2','공통으로 검토할 쟁점'));for(const issue of data.issues){
  const card=node('article','');card.className='issue';card.append(node('small',issue.id),node('h3',issue.question),node('blockquote',issue.citation.quote),node('p',issue.consequence));
  const detail=node('details','');detail.append(node('summary','두 해석과 적용 상황'),node('p',issue.interpretation_one),node('p',issue.interpretation_two),node('p','가정 상황 · '+issue.scenario));card.append(detail);output.append(card);
 }}
 for(const condition of ['A','B']){
  const calls=data.calls.filter(c=>c.condition===condition);if(!calls.length)continue;
  const section=node('section','');section.className='condition-result';section.append(node('h2',condition==='A'?'A · 역할 프롬프트':'B · 수집 자료 기반 잠정 결과'));
  const finals=calls.filter(c=>c.stage==='final');
  for(const call of finals)for(const statement of call.output.statements){const article=node('article','');article.className='issue';article.append(node('small',statement.issue_id+' · 검토 반영 제안'),node('h3',statement.position),node('blockquote',statement.proposal),node('p',statement.reason),node('h4','남은 이견'),node('p',statement.unresolved||'별도 기재 없음'));section.append(article);}
  const log=node('details','');log.open=!finals.length;log.append(node('summary','발언·반론·수정 과정 확인'));
  for(const call of calls){const block=node('article','');block.className='turn';block.append(node('h3',stages[call.stage]+' · '+call.role));for(const statement of call.output.statements){
    const s=node('div','');s.id=statement.id;s.append(node('small',statement.id+' / '+statement.issue_id+' / '+statement.verdict),node('h4',statement.position),node('p',statement.reason));
    if(statement.proposal)s.append(node('blockquote',statement.proposal));
    const sources=node('details','');sources.append(node('summary','근거와 연결 발언'));
    for(const citation of statement.citations)sources.append(node('small','원문 구간 '+citation.page),node('blockquote',citation.quote));
    for(const id of statement.target_ids){const link=node('a',id+' →');link.href='#'+id;sources.append(link,document.createTextNode(' '));}
    const evidence=Object.values(data.evidence).flat();
    for(const id of statement.evidence_ids){const found=evidence.find(item=>item.id===id);if(found){sources.append(node('h4',found.kind),node('p',found.context),node('blockquote',found.text),node('small',found.locator));if(found.source.startsWith('https://')){const link=node('a','자료 출처 ↗');link.href=found.source;link.target='_blank';link.rel='noopener';sources.append(link);}}}
    s.append(sources);block.append(s);
  }log.append(block);}section.append(log);output.append(section);
 }
 if(data.status==='complete'&&!data.issues.length)output.append(node('p','원문에서 확인 가능한 쟁점을 찾지 못해 토론을 생성하지 않았습니다.'));
}
form.addEventListener('submit',async event=>{
 event.preventDefault();button.disabled=true;document.querySelector('#use-profiles').disabled=true;
 try{let data=await post(root.dataset.start,{document_hash:root.dataset.hash,profiles:document.querySelector('#use-profiles').checked?'1':'0'});render(data);
 while(data.status!=='complete'){
  statusText.textContent=`${data.cursor} / ${data.total} · ${data.next[0]} ${stages[data.next[1]]} · ${roles[data.next[2]]} 생성 중…`;
  data=await post(`/api/debates/${data.id}/step/`,{cursor:String(data.cursor),retry:data.status==='failed'?'1':'0'});render(data);
 }
 statusText.textContent=completionMessage(data);
 }catch(error){statusText.textContent=error.message+' 다시 실행하면 마지막 성공 단계부터 이어집니다.';}
 finally{button.disabled=false;button.textContent='결과 확인 / 이어서 실행 →';document.querySelector('#use-profiles').disabled=false;}
});
function completionMessage(data){
 const base=data.issues.length?'검토가 완료됐습니다. B는 자료가 제한된 잠정 결과이며, 수정 가이드라인은 공식 정책이 아닙니다.':'원문에서 검증 가능한 쟁점을 찾지 못해 토론을 생성하지 않았습니다. 다른 정책 문서로 다시 검토할 수 있습니다.';
 return data.manual_review?base+' '+data.manual_review:base;
}
if(root.dataset.existing){
 fetch(`/api/debates/${encodeURIComponent(root.dataset.existing)}/`,{credentials:'same-origin'})
  .then(response=>response.ok?response.json():null)
  .then(data=>{if(!data)return;render(data);button.textContent='결과 확인 / 이어서 실행 →';statusText.textContent=data.status==='complete'?completionMessage(data):`${data.cursor} / ${data.total} 단계까지 저장됐습니다. 버튼을 누르면 이어서 실행합니다.`;})
  .catch(()=>{});
}
