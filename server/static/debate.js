const root = document.querySelector('#debate');
const form = document.querySelector('#debate-form');
const retryButton = document.querySelector('#debate-retry');
const statusText = document.querySelector('#debate-status');
const progress = document.querySelector('#debate-progress');
const waitText = document.querySelector('#debate-wait');
const reviewNote = document.querySelector('#debate-review-note');
const output = document.querySelector('#debate-output');
const stages = {discover:'독립 쟁점 탐색',merge:'쟁점 교차 확인',opening:'독립 입장',reply:'교차 반론',draft:'수정안 초안',review:'역할별 검토',final:'수정 가이드라인'};
let currentData = null;
let busy = false;
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
async function post(url,values){
 const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:new URLSearchParams(values)});
 const data=await response.json().catch(()=>({}));
 if(!response.ok){if(data.calls){currentData=data;render(data);}throw Error(data.error||'요청에 실패했습니다.');}return data;
}
function render(data){
 output.replaceChildren();progress.value=data.cursor;
 if(data.issues.length){output.append(node('h2','검토할 쟁점'));for(const issue of data.issues){
  const card=node('article','');card.className='issue';card.append(node('small',issue.id),node('h3',issue.question),node('blockquote',issue.citation.quote),node('p',issue.consequence));
  const detail=node('details','');detail.append(node('summary','두 해석과 적용 상황'),node('p',issue.interpretation_one),node('p',issue.interpretation_two),node('p','가정 상황 · '+issue.scenario));card.append(detail);output.append(card);
 }}
 for(const condition of ['A','B']){
  const calls=data.calls.filter(c=>c.condition===condition);if(!calls.some(c=>c.stage==='final'))continue;
  const section=node('section','');section.className='condition-result';section.append(node('h2',condition==='A'?'A · 역할별 검토':'B · 자료를 반영한 검토 (잠정)'));
  const finals=calls.filter(c=>c.stage==='final');
  for(const call of finals)for(const statement of call.output.statements){const article=node('article','');article.className='issue';article.append(node('small',statement.issue_id+' · 검토 반영 제안'),node('h3',statement.position),node('blockquote',statement.proposal),node('p',statement.reason),node('h4','남은 이견'),node('p',statement.unresolved||'별도 기재 없음'));section.append(article);}
  const log=node('details','');log.append(node('summary','발언·반론·수정 과정 확인'));
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
function phaseMessage(data){
 if(data.cursor<4)return '문서에서 해석이 갈릴 수 있는 조항을 찾고 있습니다…';
 if(data.cursor<15)return '학생·교수·학사행정 관점에서 쟁점을 검토하고 있습니다…';
 return '참고 자료를 반영해 수정 방향을 확인하고 있습니다…';
}
function complete(data){
 statusText.textContent=data.issues.length?'검토가 완료됐습니다. 아래에서 쟁점과 수정 방향을 확인해 주세요.':'원문에서 확인 가능한 쟁점을 찾지 못했습니다. 다른 문서를 검토할 수 있습니다.';
 progress.hidden=true;
 waitText.hidden=true;
 retryButton.hidden=true;
 reviewNote.hidden=!data.manual_review;
 reviewNote.textContent=data.manual_review||'';
}
function failed(message){
 statusText.textContent=message+' 저장된 단계부터 다시 시도할 수 있습니다.';
 waitText.hidden=true;
 retryButton.hidden=false;
}
async function run(allowRetry=false){
 if(busy)return;
 busy=true;
 retryButton.hidden=true;
 waitText.hidden=false;
 progress.hidden=false;
 try{
  currentData=await post(root.dataset.start,{document_hash:root.dataset.hash,profiles:'0'});
  render(currentData);
  if(currentData.status==='failed'&&!allowRetry){failed(currentData.error||'검토가 중단됐습니다.');return;}
  while(currentData.status!=='complete'){
   statusText.textContent=phaseMessage(currentData);
   currentData=await post(`/api/debates/${currentData.id}/step/`,{cursor:String(currentData.cursor),retry:currentData.status==='failed'?'1':'0'});
   progress.value=currentData.cursor;
   if([4,15,26].includes(currentData.cursor))render(currentData);
  }
  complete(currentData);
 }catch(error){failed(error instanceof TypeError?'서버 연결이 끊겼습니다.':error.message);}
 finally{busy=false;}
}
retryButton.addEventListener('click',()=>run(true));
run();
