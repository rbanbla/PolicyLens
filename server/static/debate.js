const root = document.querySelector('#debate');
const form = document.querySelector('#debate-form');
const retryButton = document.querySelector('#debate-retry');
const statusText = document.querySelector('#debate-status');
const progress = document.querySelector('#debate-progress');
const reviewNote = document.querySelector('#debate-review-note');
const output = document.querySelector('#debate-output');
const stages = {discover:'독립 쟁점 탐색',merge:'쟁점 교차 확인',opening:'독립 입장',reply:'교차 반론',draft:'수정안 초안',review:'역할별 검토',final:'수정 가이드라인'};
let busy = false;
function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el;}
function brief(text,limit=110){
 const value=(text||'').replace(/\s+/g,' ').trim();
 return value.length>limit?value.slice(0,limit).trimEnd()+'…':value;
}
function linkedNode(tag,value,clauses){
 const el=node(tag,'');const text=String(value||'');const pattern=/\d+(?:\.\d+){1,3}/g;
 let offset=0;
 for(const match of text.matchAll(pattern)){
  const id=match[0],start=match.index;
  if((start>0&&/[\d.]/.test(text[start-1]))||/[\d.]/.test(text[start+id.length]||''))continue;
  el.append(document.createTextNode(text.slice(offset,start)));
  const entries=clauses?.[id];
  if(entries?.length){
   const wrap=node('span','');wrap.className='clause-inline';
   const button=node('button',id);button.type='button';button.className='clause-ref';button.setAttribute('aria-label',`${id} 조항 설명`);
   const tip=node('span','');tip.className='clause-tooltip';tip.setAttribute('role','tooltip');
   for(const entry of entries.slice(0,3))tip.append(node('strong',`${entry.title} · ${entry.page}쪽`),node('span',entry.excerpt));
   button.addEventListener('click',()=>wrap.classList.toggle('open'));
   wrap.append(button,tip);el.append(wrap);
  }else el.append(document.createTextNode(id));
  offset=start+id.length;
 }
 el.append(document.createTextNode(text.slice(offset)));
 return el;
}

const conditions = {
 A: 'A · 역할별 검토',
 B: 'B · 자료 기반 잠정 검토'
};
const cards = new Map();
const renderedCalls = new Set();
let runId;

function disclosure(label) {
 const details = node('details', '');
 details.append(node('summary', label));
 return details;
}

function createIssueCard(issue, clauses) {
 const card = node('article', '');
 card.className = 'result-card';
 const label = node('small', `쟁점 ${cards.size + 1}`);
 label.className = 'result-kicker';
 const sourceLabel = node('small', `원문 · ${issue.citation.page}쪽`);
 sourceLabel.className = 'result-kicker';
 const quote = node('blockquote', issue.citation.quote);
 quote.className = 'result-quote';
 const direction = node('div', '');
 direction.className = 'result-direction';
 direction.append(node('strong', '수정 방향'), node('p', '수정안을 준비하고 있습니다.'));
 const interpretations = disclosure('해석이 갈리는 이유');
 interpretations.append(
  linkedNode('p', issue.interpretation_one, clauses),
  linkedNode('p', issue.interpretation_two, clauses),
  linkedNode('p', issue.consequence, clauses),
  linkedNode('p', issue.scenario, clauses)
 );

 const proposals = disclosure('수정 문구와 A/B 비교');
 proposals.hidden = true;
 const comparison = node('div', '');
 comparison.className = 'demo-comparison';
 proposals.append(comparison);

 const discussion = disclosure('세 관점의 토론');
 discussion.hidden = true;
 const threads = {};
 for (const [condition, title] of Object.entries(conditions)) {
  const thread = disclosure(title);
  thread.hidden = true;
  discussion.append(thread);
  threads[condition] = thread;
 }

 card.append(label, linkedNode('h2', issue.question, clauses), sourceLabel, quote, direction,
             proposals, interpretations, discussion);
 output.append(card);
 return {direction, proposals, comparison, discussion, threads};
}

function appendEvidence(container, statement, evidence) {
 for (const id of statement.evidence_ids) {
  const item = evidence.get(id);
  if (!item) continue;
  container.append(node('h4', item.kind), node('p', item.context),
                   node('blockquote', item.text), node('small', item.locator));
  if (item.source.startsWith('https://')) {
   const link = node('a', '자료 출처 ↗');
   link.className = 'all-link';
   link.href = item.source;
   link.target = '_blank';
   link.rel = 'noopener';
   container.append(link);
  }
 }
}

function showProposal(card, call, statement, clauses, evidence) {
 const direction = brief(statement.position, 100);
 if (call.condition === 'A') {
  card.direction.lastElementChild.replaceWith(linkedNode('p', direction, clauses));
 }
 const section = node('section', '');
 section.className = 'demo-proposal';
 const wording = linkedNode('p', statement.proposal || statement.position, clauses);
 wording.className = 'demo-wording';
 section.append(node('h3', conditions[call.condition]), wording);

 const more = disclosure('제안 이유와 남은 이견');
 if (statement.proposal && direction.endsWith('…')) {
  more.append(linkedNode('p', statement.position, clauses));
 }
 more.append(linkedNode('p', statement.reason, clauses));
 if (statement.unresolved) {
  more.append(node('h4', '남은 이견'), linkedNode('p', statement.unresolved, clauses));
 }
 if (call.condition === 'B') {
  if (statement.evidence_ids.length) appendEvidence(more, statement, evidence);
  else more.append(node('p', '직접 연결된 참고 자료가 없어 판단을 유보했습니다.'));
 }
 section.append(more);
 card.comparison.append(section);
 card.proposals.hidden = false;
}

function showTurn(card, call, statement, clauses, evidence) {
 const turn = node('article', '');
 turn.className = 'turn';
 turn.id = statement.id;
 turn.append(node('small', `${call.role} · ${stages[call.stage]} · ${statement.verdict}`),
             linkedNode('p', statement.position, clauses));
 const more = disclosure('발언 근거와 연결된 검토');
 more.append(linkedNode('p', statement.reason, clauses));
 if (statement.proposal) more.append(linkedNode('blockquote', statement.proposal, clauses));
 if (statement.unresolved) more.append(linkedNode('p', statement.unresolved, clauses));
 for (const citation of statement.citations) {
  more.append(node('small', `원문 · ${citation.page}쪽`), node('blockquote', citation.quote));
 }
 for (const id of statement.target_ids) {
  const link = node('a', `연결 발언 ${id} →`);
  link.className = 'all-link';
  link.href = '#' + id;
  more.append(link, document.createTextNode(' '));
 }
 appendEvidence(more, statement, evidence);
 turn.append(more);
 const thread = card.threads[call.condition];
 thread.append(turn);
 thread.hidden = false;
 card.discussion.hidden = false;
}

function render(data) {
 if (runId !== data.id) {
  runId = data.id;
  cards.clear();
  renderedCalls.clear();
  output.replaceChildren();
 }
 progress.max = data.total;
 progress.value = data.cursor;
 for (const issue of data.issues) {
  if (!cards.has(issue.id)) cards.set(issue.id, createIssueCard(issue, data.clauses));
 }

 const evidence = new Map(Object.values(data.evidence).flat().map(item => [item.id, item]));
 for (const call of data.calls) {
  if (!(call.condition in conditions) || renderedCalls.has(call.step)) continue;
  for (const statement of call.output.statements) {
   const card = cards.get(statement.issue_id);
   if (!card) continue;
   showTurn(card, call, statement, data.clauses, evidence);
   if (call.stage === 'final') showProposal(card, call, statement, data.clauses, evidence);
  }
  renderedCalls.add(call.step);
 }
}

async function post(url, values) {
 const response = await fetch(url, {
  method: 'POST',
  credentials: 'same-origin',
  headers: {'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value},
  body: new URLSearchParams(values)
 });
 const data = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (data.calls) render(data);
  throw Error(data.error || '요청에 실패했습니다.');
 }
 return data;
}

function phaseMessage(data) {
 if (!data.issues.length) return '해석이 갈리는 조항을 찾고 있습니다…';
 if (data.next?.[0] === 'B') return '참고 자료를 바탕으로 수정안을 검토하고 있습니다…';
 return '세 관점의 검토와 수정안을 준비하고 있습니다…';
}

function complete(data) {
 statusText.textContent = data.issues.length ? '정책 검토가 완료됐습니다.' : '원문에서 해석이 갈리는 조항을 찾지 못했습니다.';
 progress.hidden = true;
 const notes = [
  data.manual_review,
  data.citation_omissions ? `원문과 일치하지 않은 보조 인용 ${data.citation_omissions}개를 제외했습니다.` : null
 ].filter(Boolean);
 reviewNote.hidden = !notes.length;
 reviewNote.textContent = notes.join(' ');
}

function failed(message) {
 statusText.textContent = message;
 progress.hidden = true;
 retryButton.hidden = false;
}

async function run(allowRetry = false) {
 if (busy) return;
 busy = true;
 retryButton.hidden = true;
 progress.hidden = false;
 statusText.textContent = '검토 결과를 불러오고 있습니다…';
 try {
  let data = await post(root.dataset.start, {document_hash: root.dataset.hash, profiles: '0'});
  render(data);
  if (data.status === 'failed' && !allowRetry) {
   failed(data.error || '검토가 중단됐습니다.');
   return;
  }
  while (data.status !== 'complete') {
   statusText.textContent = phaseMessage(data);
   data = await post(`/api/debates/${data.id}/step/`, {
    cursor: String(data.cursor),
    retry: data.status === 'failed' ? '1' : '0',
    parallel_discovery: '1'
   });
   render(data);
  }
  complete(data);
 } catch (error) {
  failed(error instanceof TypeError ? '서버 연결이 끊겼습니다. 저장된 단계부터 다시 시도할 수 있습니다.' : error.message);
 } finally {
  busy = false;
 }
}

retryButton.addEventListener('click', () => run(true));
run();
