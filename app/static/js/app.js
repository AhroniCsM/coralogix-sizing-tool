/* Coralogix Sizing Tool — Frontend JS */

document.addEventListener('DOMContentLoaded', () => {
    setupDropZone();
    setupProviderToggle();
    setupFormSubmit();
});

function setupDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileList = document.getElementById('file-list');

    if (!dropZone || !fileInput) return;

    // Click to browse
    dropZone.addEventListener('click', () => fileInput.click());

    // Drag & drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateFileList();
        }
    });

    fileInput.addEventListener('change', updateFileList);

    function updateFileList() {
        if (!fileList) return;
        fileList.innerHTML = '';
        const files = fileInput.files;
        for (let i = 0; i < files.length; i++) {
            const div = document.createElement('div');
            div.className = 'file-item';
            const sizeMB = (files[i].size / 1024 / 1024).toFixed(1);
            div.innerHTML = `
                <span class="text-gray-400">📎</span>
                <span>${files[i].name}</span>
                <span class="text-gray-400">(${sizeMB} MB)</span>
            `;
            fileList.appendChild(div);
        }
    }
}

function setupProviderToggle() {
    const radios = document.querySelectorAll('input[name="provider"]');
    const ddTips = document.getElementById('dd-tips');
    const nrTips = document.getElementById('nr-tips');

    if (!radios.length || !ddTips || !nrTips) return;

    radios.forEach(radio => {
        radio.addEventListener('change', () => {
            if (radio.value === 'datadog') {
                ddTips.classList.remove('hidden');
                nrTips.classList.add('hidden');
            } else {
                ddTips.classList.add('hidden');
                nrTips.classList.remove('hidden');
            }
        });
    });
}

function setupFormSubmit() {
    const form = document.querySelector('form[action="/upload"]');
    const btn = document.getElementById('submit-btn');

    if (!form || !btn) return;

    form.addEventListener('submit', () => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner mr-2"></span> Extracting with Claude Vision...';
    });
}
