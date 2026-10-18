// Independent assets share the project's regular editors, Mod tray and export path.
(() => {
  'use strict';
  const el = (...args) => AtelierJobDialogs.el(...args);
  const prefixes = {texture: 'T_', mesh: 'SK_', material: 'MI_'};
  let overlay, panel, form, kind, name, mode, files, fileRow, fileNames, sourceRow, sourceLabel,
    source, folder, destination, status, submit, browser, browserItems, browserPath, useFolder,
    up, closeButton, help, browseMode, browseLocation = '', browseRequest = 0, project, busy = false;
  function gamePath(value) { return value.trim().replaceAll('\\', '/').replace(/^\/Game\/Marvel(?:\/|$)/, '').replace(/\/$/, ''); }
  function assetName() {
    const value = name.value.trim();
    const valid = kind.value === 'mesh' ? /^(SK_|SM_)/i : new RegExp('^' + prefixes[kind.value], 'i');
    return value && (valid.test(value) ? value : prefixes[kind.value] + value);
  }
  function hide() { overlay.classList.remove('active'); document.getElementById('add-asset-open').focus(); }
  function message(text, error = false) { status.textContent = text; status.classList.toggle('is-error', error); }
  function refresh() {
    const upload = mode.value === 'file';
    const cooked = [...files.files].some(file => /\.uasset$/i.test(file.name));
    fileRow.hidden = !upload;
    sourceRow.hidden = upload && (kind.value !== 'texture' || cooked);
    sourceLabel.textContent = upload ? 'Game texture template' : 'Game asset to copy';
    name.placeholder = prefixes[kind.value] + {texture: 'MyTexture', mesh: 'MyMesh', material: 'MyMaterial'}[kind.value];
    help.textContent = {
      texture: 'Images use the template’s texture format. Pick a matching diffuse, normal or mask texture.',
      mesh: 'For FBX, GLB or Blender files, copy a game mesh first, then use Replace model.',
      material: 'Material files must be cooked material instances (MI_).',
    }[kind.value];
    source.placeholder = kind.value === 'texture' ? 'Characters/…/Textures/T_Body_D' :
      kind.value === 'mesh' ? 'Characters/…/Meshes/SK_Body' : 'Characters/…/Materials/MI_Body';
    files.accept = kind.value === 'texture' ? '.png,.tga,.jpg,.jpeg,.webp,.bmp,.dds,.uasset,.uexp,.ubulk,.uptnl' : '.uasset,.uexp,.ubulk,.uptnl';
    fileNames.textContent = [...files.files].map(file => file.name).join(', ') ||
      (kind.value === 'texture' ? 'Choose an image, or a cooked .uasset with its companion files.' :
        'Choose a cooked .uasset with its .uexp, .ubulk and .uptnl files when present.');
    const target = [gamePath(folder.value), assetName() || prefixes[kind.value] + 'YourName'].filter(Boolean).join('/');
    destination.textContent = '/Game/Marvel/' + target;
  }
  function field(labelText, id, control) {
    const wrap = el('div', undefined, 'add-asset-field');
    const label = el('label', labelText); label.htmlFor = id; control.id = id;
    wrap.append(label, control); return wrap;
  }
  function button(text, action, cls = 'btn') {
    const node = el('button', text, cls); node.type = 'button'; node.addEventListener('click', action); return node;
  }
  async function browseAt(path) {
    const request = ++browseRequest;
    browserItems.replaceChildren(el('p', 'Loading folders…', 'add-asset-help'));
    browser.hidden = false; useFolder.disabled = true;
    try {
      const query = new URLSearchParams({path: gamePath(path)});
      if (browseMode === 'source') query.set('file_type', kind.value);
      const result = await api('/api/assets/browse?' + query, {project});
      if (request !== browseRequest || !overlay.classList.contains('active')) return;
      if (!result.ok) throw Error(result.error || 'Could not browse game folders.');
      browseLocation = result.path;
      browserPath.textContent = '/Game/Marvel/' + browseLocation;
      up.disabled = !browseLocation; useFolder.disabled = false; useFolder.hidden = browseMode !== 'folder';
      browserItems.replaceChildren();
      for (const item of result.items) {
        const row = button((item.type === 'folder' ? 'Folder: ' : '') + item.name, () => {
          if (item.type === 'folder') { browseAt(item.rel_path); return; }
          source.value = item.game_rel; browser.hidden = true; source.focus(); refresh();
        });
        row.dataset.path = item.rel_path || item.game_rel; browserItems.append(row);
      }
      if (!result.items.length) browserItems.append(el('p', browseMode === 'folder' ?
        'No subfolders. Use this folder, or type a new folder above.' : 'No matching assets in this folder.', 'add-asset-help'));
    } catch (error) {
      if (request === browseRequest) browserItems.replaceChildren(el('p', error.message, 'add-asset-help'));
    }
  }
  function showBrowser(target) {
    browseMode = target;
    const path = gamePath(target === 'folder' ? folder.value : source.value);
    browseAt(target === 'folder' ? path : path.split('/').slice(0, -1).join('/'));
  }
  function init() {
    overlay = el('div', undefined, 'overlay'); overlay.id = 'add-asset-overlay';
    panel = el('section', undefined, 'modal add-asset-modal'); panel.tabIndex = -1;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); panel.setAttribute('aria-labelledby', 'add-asset-title');
    const heading = el('h2', 'Add asset'); heading.id = 'add-asset-title';
    panel.append(heading, el('p', 'Add a texture, mesh or material with your own name and a folder in the game files. It will appear in your Mod tray.', 'add-asset-help'));
    form = el('form', undefined, 'add-asset-form');
    kind = el('select');
    for (const [value, label] of [['texture', 'Texture'], ['mesh', 'Mesh'], ['material', 'Material']]) {
      const option = el('option', label); option.value = value; kind.append(option);
    }
    name = el('input'); name.type = 'text'; name.required = true; name.maxLength = 80; name.pattern = '[A-Za-z0-9_]+';
    name.placeholder = 'T_MyTexture'; name.spellcheck = false;
    const columns = el('div', undefined, 'add-asset-columns');
    columns.append(field('Asset type', 'add-asset-type', kind), field('Asset name', 'add-asset-name', name));
    mode = el('select');
    for (const [value, label] of [['file', 'File from computer'], ['game', 'Copy a game asset']]) {
      const option = el('option', label); option.value = value; mode.append(option);
    }
    files = el('input'); files.type = 'file'; files.multiple = true; files.hidden = true; files.id = 'add-asset-files';
    const choose = button('Choose files…', () => files.click());
    fileNames = el('span', '', 'add-asset-files'); fileNames.setAttribute('aria-live', 'polite');
    fileRow = el('div', undefined, 'add-asset-field'); fileRow.append(choose, files, fileNames);
    source = el('input'); source.type = 'text'; source.spellcheck = false;
    sourceRow = field('Game texture template', 'add-asset-source', source); sourceLabel = sourceRow.querySelector('label');
    const sourceInline = el('div', undefined, 'add-asset-inline'); sourceInline.append(source, button('Browse…', () => showBrowser('source'))); sourceRow.append(sourceInline);
    help = el('small');
    help.className = 'add-asset-help';
    folder = el('input'); folder.type = 'text'; folder.spellcheck = false; folder.placeholder = 'Characters/…/Textures, or your own folder';
    const folderRow = field('Destination folder', 'add-asset-folder', folder);
    const folderInline = el('div', undefined, 'add-asset-inline'); folderInline.append(folder, button('Browse…', () => showBrowser('folder'))); folderRow.append(folderInline);
    browser = el('section', undefined, 'add-asset-browser'); browser.hidden = true; browser.setAttribute('aria-label', 'Choose from game files');
    const browserHead = el('div', undefined, 'add-asset-browser-head');
    up = button('Up', () => browseAt(browseLocation.split('/').slice(0, -1).join('/')));
    browserPath = el('code', '', 'add-asset-browser-path');
    browserHead.append(up, browserPath, button('Close browser', () => { browseRequest++; browser.hidden = true; }));
    browserItems = el('div', undefined, 'add-asset-browser-items');
    useFolder = button('Use this folder', () => { folder.value = browseLocation; browser.hidden = true; folder.focus(); refresh(); });
    useFolder.id = 'add-asset-use-folder'; browser.append(browserHead, browserItems, useFolder);
    const output = el('div', undefined, 'add-asset-destination'); destination = el('code'); destination.id = 'add-asset-path';
    output.append(el('span', 'New asset path'), destination);
    status = el('p', '', 'add-asset-status'); status.id = 'add-asset-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const actions = el('div', undefined, 'add-asset-actions');
    closeButton = button('Cancel', hide); closeButton.dataset.close = 'true';
    submit = el('button', 'Add asset', 'btn primary'); submit.type = 'submit'; submit.id = 'add-asset-submit';
    actions.append(closeButton, submit);
    form.append(columns, field('Source', 'add-asset-mode', mode), fileRow, sourceRow, help, folderRow, browser, output, status, actions);
    panel.append(form); overlay.append(panel); document.body.append(overlay);
    form.addEventListener('submit', add);
    kind.addEventListener('change', () => { files.value = ''; source.value = ''; browser.hidden = true; browseRequest++; refresh(); });
    mode.addEventListener('change', () => { browser.hidden = true; browseRequest++; refresh(); });
    for (const input of [name, folder, source]) input.addEventListener('input', refresh);
    files.addEventListener('change', () => {
      if (!name.value && files.files.length) name.value = files.files[0].name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_]+/g, '_');
      refresh();
    });
    AtelierJobDialogs.trap(overlay, panel, hide);
    window.addEventListener('atelier-job', event => {
      if (busy && event.detail.kind === 'asset-add' && event.detail.project === project) message(event.detail.stage);
    });
  }
  async function add(event) {
    event.preventDefault();
    if (busy) return;
    if (project !== atelierProject()) { message('Project changed. Close this dialog and click Add asset again.', true); return; }
    const uploading = mode.value === 'file';
    if (uploading && !files.files.length) { message('Choose the file to add first.', true); return; }
    if (!sourceRow.hidden && !source.value.trim()) { message('Choose a game asset' + (uploading ? ' to use as the texture template.' : ' to copy.'), true); source.focus(); return; }
    const body = new FormData();
    body.append('file_type', kind.value); body.append('name', name.value.trim()); body.append('folder', folder.value.trim());
    body.append('source', sourceRow.hidden ? '' : source.value.trim());
    if (uploading) for (const file of files.files) body.append('files', file, file.name);
    busy = true; browser.hidden = true; browseRequest++;
    const controls = [...form.querySelectorAll('input,select,button')].filter(node => !node.dataset.close);
    const disabled = controls.map(node => node.disabled); controls.forEach(node => node.disabled = true);
    submit.textContent = 'Adding asset…'; closeButton.textContent = 'Hide'; message('Preparing your asset…'); panel.focus();
    try {
      const result = await AtelierJobs.run('/api/assets/add', {method: 'POST', body, project});
      if (!result.ok) throw Error(result.error || 'Could not add the asset.');
      hide(); window.dispatchEvent(new CustomEvent('atelier-asset-added', {detail: {...result, project}}));
    } catch (error) { message(error.message, true); }
    finally {
      busy = false; controls.forEach((node, i) => node.disabled = disabled[i]); submit.textContent = 'Add asset';
      closeButton.textContent = 'Cancel';
      if (overlay.classList.contains('active')) submit.focus();
    }
  }
  window.AtelierAddAsset = Object.freeze({
    open(path = '') {
      if (!overlay) init();
      if (!busy) {
        project = atelierProject(); form.reset(); folder.value = path; browser.hidden = true; browseRequest++;
        message('The asset will be added to your Mod tray.'); refresh();
      }
      overlay.classList.add('active'); panel.focus();
    },
  });
})();
