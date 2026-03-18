/* Coralogix Sizing Tool — Frontend JS */

// Store pasted images as base64 data URLs
let pastedImages = [];

document.addEventListener('DOMContentLoaded', () => {
    setupDropZone();
    setupProviderToggle();
    setupFormSubmit();
    setupPasteHandler();
});

function setupDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileList = document.getElementById('file-list');

    if (!dropZone || !fileInput) return;

    // Click to browse
    dropZone.addEventListener('click', (e) => {
        // Don't trigger if clicking on paste preview
        if (e.target.closest('#paste-preview')) return;
        fileInput.click();
    });

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
            // Clear pasted images when files are dropped
            pastedImages = [];
            updatePastePreview();
        }
    });

    fileInput.addEventListener('change', () => {
        updateFileList();
        // Clear pasted images when files are selected
        pastedImages = [];
        updatePastePreview();
    });

    function updateFileList() {
        if (!fileList) return;
        fileList.innerHTML = '';
        const files = fileInput.files;
        for (let i = 0; i < files.length; i++) {
            const div = document.createElement('div');
            div.className = 'file-item';
            const sizeMB = (files[i].size / 1024 / 1024).toFixed(1);
            div.innerHTML = `
                <span class="text-gray-400">\u{1F4CE}</span>
                <span>${files[i].name}</span>
                <span class="text-gray-400">(${sizeMB} MB)</span>
            `;
            fileList.appendChild(div);
        }
    }
}

function setupPasteHandler() {
    // Listen for paste on the whole document
    document.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const blob = item.getAsFile();
                if (!blob) continue;

                const reader = new FileReader();
                reader.onload = (ev) => {
                    pastedImages.push(ev.target.result);
                    updatePastePreview();

                    // Clear file input since we're using paste
                    const fileInput = document.getElementById('file-input');
                    if (fileInput) fileInput.value = '';
                    const fileList = document.getElementById('file-list');
                    if (fileList) fileList.innerHTML = '';
                };
                reader.readAsDataURL(blob);
            }
        }
    });
}

function updatePastePreview() {
    const preview = document.getElementById('paste-preview');
    const thumbs = document.getElementById('paste-thumbs');
    const count = document.getElementById('paste-count');

    if (!preview) return;

    if (pastedImages.length === 0) {
        preview.classList.add('hidden');
        return;
    }

    preview.classList.remove('hidden');
    count.textContent = pastedImages.length;

    thumbs.innerHTML = '';
    pastedImages.forEach((dataUrl, idx) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'relative group';
        wrapper.innerHTML = `
            <img src="${dataUrl}" class="h-20 rounded border border-gray-200 object-cover">
            <button type="button" onclick="removePasted(${idx})"
                    class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-5 h-5 text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition">
                &times;
            </button>
        `;
        thumbs.appendChild(wrapper);
    });
}

function removePasted(idx) {
    pastedImages.splice(idx, 1);
    updatePastePreview();
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
    const form = document.getElementById('upload-form');
    const btn = document.getElementById('submit-btn');

    if (!form || !btn) return;

    form.addEventListener('submit', async (e) => {
        // If we have pasted images, use the paste API instead of form submit
        if (pastedImages.length > 0) {
            e.preventDefault();
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner mr-2"></span> Analyzing screenshot...';

            const provider = document.querySelector('input[name="provider"]:checked')?.value || 'datadog';

            try {
                const resp = await fetch('/paste', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider, images: pastedImages }),
                });

                if (!resp.ok) {
                    const err = await resp.json();
                    throw new Error(err.error || 'Upload failed');
                }

                const data = await resp.json();
                // Redirect to result page — build a form and POST to /calculate-review
                showPasteResult(data);
            } catch (err) {
                btn.disabled = false;
                btn.innerHTML = 'Extract & Analyze';
                alert('Error: ' + err.message);
            }
            return;
        }

        // Normal file upload — just show spinner
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner mr-2"></span> Analyzing screenshot...';
    });
}

function showPasteResult(data) {
    // Build a hidden form and submit to render the result page server-side
    // We'll redirect to the result page via a POST to /paste-result
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/paste-result';

    const fields = {
        run_id: data.run_id,
        provider: data.provider,
        extraction: JSON.stringify(data.extraction),
    };

    for (const [key, val] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = val;
        form.appendChild(input);
    }

    document.body.appendChild(form);
    form.submit();
}
