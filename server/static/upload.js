const input = document.querySelector('#document');
const zone = document.querySelector('#drop-zone');
const status = document.querySelector('#file-status');
function updateFile() {
  const file = input.files[0];
  status.textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : '';
  input.setCustomValidity(file && file.size > 10 * 1024 * 1024 ? '10MB 이하의 파일을 선택해 주세요.' : '');
}
input.addEventListener('change', updateFile);
for (const name of ['dragenter', 'dragover']) zone.addEventListener(name, event => {
  event.preventDefault(); zone.classList.add('dragging');
});
zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
zone.addEventListener('drop', event => {
  event.preventDefault(); zone.classList.remove('dragging');
  if (event.dataTransfer.files.length !== 1) {
    status.textContent = '문서 한 개씩 올려주세요.'; return;
  }
  input.files = event.dataTransfer.files; updateFile();
});
