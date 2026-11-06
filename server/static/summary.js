const panel = document.querySelector('#policy-summary');
const message = document.querySelector('#summary-status');
const items = document.querySelector('#summary-items');
const retry = document.querySelector('#summary-retry');
function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}
let busy = false;
async function summarize(isRetry = false) {
  if (busy) return;
  busy = true;
  retry.hidden = true;
  items.setAttribute('aria-busy', 'true');
  message.classList.remove('sr-only');
  message.textContent = '문서의 주요 내용을 정리하고 있습니다…';
  try {
    const response = await fetch(panel.dataset.url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value},
      body: new URLSearchParams({document_hash: panel.dataset.documentHash, retry: isRetry ? '1' : '0'})
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || '요약을 불러오지 못했습니다.');
    items.replaceChildren();
    for (const item of data.items) {
      const article = document.createElement('article');
      article.className = 'summary-item';
      article.append(element('h2', item.title), element('p', item.summary));
      const details = document.createElement('details');
      details.append(element('summary', '원문 근거 확인'));
      for (const citation of item.citations) {
        details.append(element('small', citation.label), element('blockquote', citation.quote));
      }
      article.append(details);
      items.append(article);
    }
    if (data.items.length) {
      message.classList.add('sr-only');
      message.textContent = '주요 내용 ' + data.items.length + '개를 정리했습니다.';
    } else {
      message.textContent = '원문에서 요약할 주요 내용을 찾지 못했습니다.';
    }
  } catch (error) {
    message.textContent = error instanceof TypeError ? '서버 연결이 끊겼습니다. 잠시 후 다시 시도해 주세요.' : error.message;
    retry.hidden = false;
  } finally {
    busy = false;
    items.setAttribute('aria-busy', 'false');
  }
}
retry.addEventListener('click', () => summarize(true));
summarize();
