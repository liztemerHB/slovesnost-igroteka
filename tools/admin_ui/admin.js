/**
 * admin.js — Рабочий стол «Мастерская репетитора» (Словесность).
 *
 * - Авторизация с заголовком X-Requested-With: TutorAdmin и индикацией режима хранения.
 * - Двухвкладочная левая панель приёма: Drag & Drop HTML-тренажёров + Доски Miro/Холст.
 * - Клиентское сжатие пользовательских обложек через <canvas> до <= 1280px (< 400 КБ).
 * - Табличный реестр картотеки с 4 явными состояниями (loading, error, empty, full).
 * - Печатная карточка QR-кода по адресу public_catalog_url (локально или GitHub Pages).
 */

(function() {
  'use strict';

  const CLOUD_MAX_HTML_BYTES = 4 * 1024 * 1024; // 4 МБ (запас под лимит шлюза Vercel 4.5 МБ)

  const state = {
    authenticated: false,
    storageMode: 'local',
    publicCatalogUrl: '/',
    registryStatus: 'loading', // 'loading' | 'error' | 'full'
    registryError: '',
    items: [],
    existingTopics: [],
    currentTab: 'active',
    searchQuery: '',
    selectedGameFile: null,
    gameFileContent: '',
    selectedGameGrade: null,
    selectedGameCover: 'library',
    selectedBoardGrade: null,
    editItemGrade: null,
    editItemCover: 'library'
  };

  const DEFAULT_COVERS = [
    { key: 'library', label: 'Кабинет', src: '/covers/library.png' },
    { key: 'autumn', label: 'Диктант', src: '/covers/autumn.png' },
    { key: 'quest', label: 'Квест', src: '/covers/quest.png' },
    { key: 'exam', label: 'Экзамен', src: '/covers/exam.png' },
    { key: 'board', label: 'Доска', src: '/covers/board.png' },
    { key: 'alchemy', label: 'Фразеология', src: '/covers/alchemy.png' }
  ];

  const htmlEl = document.documentElement;
  const adminThemeBtn = document.getElementById('admin-theme-btn');
  const storageModeBadge = document.getElementById('storage-mode-badge');
  const storageModeText = document.getElementById('storage-mode-text');
  const publicCatalogLink = document.getElementById('public-catalog-link');

  const loginScreen = document.getElementById('login-screen');
  const loginForm = document.getElementById('login-form');
  const loginErrorBox = document.getElementById('login-error-box');
  const passwordInput = document.getElementById('admin-password-input');
  const logoutBtn = document.getElementById('logout-btn');
  const adminHub = document.getElementById('admin-hub');

  const intakeTabBtns = document.querySelectorAll('.intake-tab-btn');
  const intakePaneGame = document.getElementById('intake-pane-game');
  const intakePaneBoard = document.getElementById('intake-pane-board');

  const gameFileInput = document.getElementById('game-file-input');
  const gameDropZone = document.getElementById('game-drop-zone');
  const dropZoneFilename = document.getElementById('drop-zone-filename');
  const uploadPreviewForm = document.getElementById('upload-preview-form');
  const gameTitleInput = document.getElementById('game-title-input');
  const gameGradePicker = document.getElementById('game-grade-picker');
  const gameTopicInput = document.getElementById('game-topic-input');
  const gameSubtitleInput = document.getElementById('game-subtitle-input');
  const gameCoverPicker = document.getElementById('game-cover-picker');
  const customCoverInput = document.getElementById('custom-cover-input');
  const uploadCoverBtn = document.getElementById('upload-cover-btn');
  const customCoverStatus = document.getElementById('custom-cover-status');
  const gameHiddenCheck = document.getElementById('game-hidden-check');
  const existingTopicsDatalist = document.getElementById('existing-topics-list');

  const boardAddForm = document.getElementById('board-add-form');
  const boardUrlInput = document.getElementById('board-url-input');
  const boardTitleInput = document.getElementById('board-title-input');
  const boardGradePicker = document.getElementById('board-grade-picker');
  const boardTopicInput = document.getElementById('board-topic-input');
  const boardSubtitleInput = document.getElementById('board-subtitle-input');
  const boardHiddenCheck = document.getElementById('board-hidden-check');

  const registryList = document.getElementById('registry-list');
  const registryCountText = document.getElementById('registry-count-text');
  const registrySearchInput = document.getElementById('registry-search-input');
  const regTabs = document.querySelectorAll('.reg-tab-btn');

  const successModal = document.getElementById('success-modal');
  const successModalClose = document.getElementById('success-modal-close');
  const successTitle = document.getElementById('success-title');
  const successQrWrap = document.getElementById('success-qr-wrap');
  const successGameUrlInput = document.getElementById('success-game-url-input');
  const successCopyGameBtn = document.getElementById('success-copy-game-btn');
  const successLessonRow = document.getElementById('success-lesson-row');
  const successLessonUrlInput = document.getElementById('success-lesson-url-input');
  const successCopyLessonBtn = document.getElementById('success-copy-lesson-btn');
  const successOpenGameLink = document.getElementById('success-open-game-link');
  const successDoneBtn = document.getElementById('success-done-btn');

  const editModal = document.getElementById('edit-modal');
  const editModalClose = document.getElementById('edit-modal-close');
  const editItemForm = document.getElementById('edit-item-form');
  const editItemId = document.getElementById('edit-item-id');
  const editTitleInput = document.getElementById('edit-title-input');
  const editGradePicker = document.getElementById('edit-grade-picker');
  const editTopicInput = document.getElementById('edit-topic-input');
  const editSubtitleInput = document.getElementById('edit-subtitle-input');
  const editUrlField = document.getElementById('edit-url-field');
  const editUrlInput = document.getElementById('edit-url-input');
  const editCoverPicker = document.getElementById('edit-cover-picker');
  const editHiddenCheck = document.getElementById('edit-hidden-check');
  const editCancelBtn = document.getElementById('edit-cancel-btn');

  const toastNotice = document.getElementById('toast-notice');
  const toastText = document.getElementById('toast-text');
  let toastTimer = null;

  // --- Сетевой слой с CSRF-заголовком ---
  async function apiFetch(endpoint, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign({
      'Content-Type': 'application/json',
      'X-Requested-With': 'TutorAdmin'
    }, opts.headers || {});

    try {
      const resp = await fetch(endpoint, opts);
      const data = await resp.json().catch(function() { return {}; });
      return { ok: resp.ok, status: resp.status, data: data };
    } catch (err) {
      return { ok: false, status: 0, error: err.message, data: {} };
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(message, duration) {
    if (!toastNotice || !toastText) return;
    toastText.textContent = message;
    toastNotice.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function() {
      toastNotice.classList.remove('is-visible');
    }, duration || 2800);
  }

  function copyText(text, onDone) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onDone).catch(function() {
        fallbackCopy(text, onDone);
      });
    } else {
      fallbackCopy(text, onDone);
    }
  }

  function fallbackCopy(text, onDone) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      if (onDone) onDone();
    } catch (e) {}
    document.body.removeChild(ta);
  }

  // --- 1. Режим освещения (синхронно с витриной) ---
  function initTheme() {
    let saved = 'light';
    try {
      saved = localStorage.getItem('slovesnost_theme') || 'light';
    } catch (e) {}
    applyTheme(saved);

    if (adminThemeBtn) {
      adminThemeBtn.addEventListener('click', function() {
        const next = htmlEl.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        try {
          localStorage.setItem('slovesnost_theme', next);
        } catch (e) {}
      });
    }
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      htmlEl.setAttribute('data-theme', 'dark');
    } else {
      htmlEl.removeAttribute('data-theme');
    }
  }

  // --- 2. Сессия, статус хранилища и публичный URL витрины ---
  function applyServerMetadata(payload) {
    if (!payload) return;
    if (payload.storage_mode) {
      state.storageMode = payload.storage_mode;
      if (storageModeBadge && storageModeText) {
        const isCloud = payload.storage_mode === 'github';
        storageModeBadge.classList.toggle('is-cloud', isCloud);
        storageModeText.textContent = isCloud ? 'GitHub Облако' : 'Локальный диск';
      }
    }
    if (payload.public_catalog_url) {
      state.publicCatalogUrl = payload.public_catalog_url;
      if (publicCatalogLink) {
        publicCatalogLink.href = payload.public_catalog_url;
      }
    }
  }

  async function checkSession() {
    const res = await apiFetch('/api/admin/session', { method: 'GET' });
    if (res.data) {
      applyServerMetadata(res.data);
      if (res.data.password_configured === false && loginErrorBox) {
        loginErrorBox.textContent = 'В настройках облака не задана переменная окружения TUTOR_ADMIN_PASSWORD. Добавьте её в панели Vercel.';
        loginErrorBox.classList.add('is-visible');
      }
    }
    if (res.ok && res.data && res.data.authenticated) {
      setAuthenticated(true);
      await loadRegistryItems();
    } else {
      setAuthenticated(false);
    }
  }

  function setAuthenticated(isAuth) {
    state.authenticated = isAuth;
    if (isAuth) {
      loginScreen.style.display = 'none';
      adminHub.classList.add('is-active');
      if (logoutBtn) logoutBtn.style.display = 'inline-flex';
    } else {
      loginScreen.style.display = 'flex';
      adminHub.classList.remove('is-active');
      if (logoutBtn) logoutBtn.style.display = 'none';
    }
  }

  function initAuth() {
    if (loginForm) {
      loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const pwd = passwordInput.value.trim();
        if (!pwd) return;

        if (loginErrorBox) loginErrorBox.classList.remove('is-visible');

        const res = await apiFetch('/api/admin/login', {
          method: 'POST',
          body: JSON.stringify({ password: pwd })
        });

        if (res.ok && res.data && res.data.ok) {
          passwordInput.value = '';
          showToast('Рабочий стол открыт');
          setAuthenticated(true);
          await loadRegistryItems();
        } else {
          const errMsg = (res.data && res.data.message) ? res.data.message : 'Неверный пароль';
          if (loginErrorBox) {
            loginErrorBox.textContent = errMsg;
            loginErrorBox.classList.add('is-visible');
          }
          passwordInput.focus();
          passwordInput.select();
        }
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', async function() {
        await apiFetch('/api/admin/logout', { method: 'POST' });
        showToast('Сессия завершена');
        setAuthenticated(false);
      });
    }
  }

  // --- 3. Вкладки левой колонки приёма ---
  function initIntakeTabs() {
    intakeTabBtns.forEach(function(btn) {
      btn.addEventListener('click', function() {
        const target = btn.getAttribute('data-intake');
        intakeTabBtns.forEach(function(b) {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (intakePaneGame) intakePaneGame.classList.toggle('is-active', target === 'game');
        if (intakePaneBoard) intakePaneBoard.classList.toggle('is-active', target === 'board');
      });
    });
  }

  // --- 4. Выбор класса и обложки ---
  function renderGradePicker(containerEl, currentVal, onSelect) {
    if (!containerEl) return;
    containerEl.innerHTML = '';

    const grades = [null, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
    grades.forEach(function(g) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'grade-pick-btn' + (g === currentVal ? ' is-selected' : '');
      btn.textContent = g === null ? 'Вне кл.' : (g + ' кл.');
      btn.addEventListener('click', function() {
        containerEl.querySelectorAll('.grade-pick-btn').forEach(function(b) { b.classList.remove('is-selected'); });
        btn.classList.add('is-selected');
        onSelect(g);
      });
      containerEl.appendChild(btn);
    });
  }

  function renderCoverPicker(containerEl, currentKey, onSelect) {
    if (!containerEl) return;
    containerEl.innerHTML = '';

    DEFAULT_COVERS.forEach(function(c) {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'cover-thumb-item' + (c.key === currentKey ? ' is-selected' : '');
      item.title = c.label;
      item.innerHTML = (
        '<img class="cover-thumb-img" src="' + escapeHtml(c.src) + '" alt="' + escapeHtml(c.label) + '" onerror="this.style.opacity=\'0.2\'">' +
        '<span class="cover-thumb-label">' + escapeHtml(c.label) + '</span>'
      );
      item.addEventListener('click', function() {
        containerEl.querySelectorAll('.cover-thumb-item').forEach(function(el) { el.classList.remove('is-selected'); });
        item.classList.add('is-selected');
        onSelect(c.key);
      });
      containerEl.appendChild(item);
    });
  }

  // --- 5. Загрузка HTML-файлов и клиентское сжатие кастомных обложек ---
  function initGameDropZone() {
    if (!gameDropZone || !gameFileInput) return;

    gameDropZone.addEventListener('click', function() { gameFileInput.click(); });
    gameDropZone.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        gameFileInput.click();
      }
    });

    gameDropZone.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.stopPropagation();
      gameDropZone.classList.add('dragover');
    });

    ['dragleave', 'dragend'].forEach(function(ev) {
      gameDropZone.addEventListener(ev, function() { gameDropZone.classList.remove('dragover'); });
    });

    gameDropZone.addEventListener('drop', function(e) {
      e.preventDefault();
      e.stopPropagation();
      gameDropZone.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleGameFiles(e.dataTransfer.files);
      }
    });

    gameFileInput.addEventListener('change', function() {
      if (gameFileInput.files && gameFileInput.files.length > 0) {
        handleGameFiles(gameFileInput.files);
      }
    });
  }

  function handleGameFiles(fileList) {
    const file = Array.from(fileList).find(function(f) {
      return f.name.toLowerCase().endsWith('.html') || f.type === 'text/html';
    });
    if (!file) {
      showToast('Выберите файл с расширением .html', 3200);
      return;
    }

    if (state.storageMode === 'github' && file.size > CLOUD_MAX_HTML_BYTES) {
      showToast('В облачном режиме файл .html должен быть не крупнее 4 МБ', 4200);
      return;
    }

    state.selectedGameFile = file;
    if (dropZoneFilename) {
      dropZoneFilename.textContent = file.name;
    }

    const reader = new FileReader();
    reader.onload = function(e) {
      state.gameFileContent = e.target.result;
      parseAndShowGamePreview(file.name, state.gameFileContent);
    };
    reader.readAsText(file, 'utf-8');
  }

  async function parseAndShowGamePreview(filename, htmlText) {
    let title = filename.replace(/\.html$/i, '');
    const titleMatch = htmlText.match(/<title>([^<]+)<\/title>/i);
    if (titleMatch && titleMatch[1].trim()) {
      title = titleMatch[1].trim();
    }

    let grade = null;
    const gradeMatch = title.match(/(\d{1,2})\s*класс/i);
    if (gradeMatch) grade = parseInt(gradeMatch[1], 10);

    const hasAudio = /audio|sound|speechSynthesis|mp3|ogg|wav/i.test(htmlText);
    let subtitle = hasAudio ? 'Интерактивное задание со звуком' : 'Интерактивный тренажёр';
    let suggestedCover = hasAudio ? 'autumn' : 'library';

    const srvPreview = await apiFetch('/api/admin/preview-game', {
      method: 'POST',
      body: JSON.stringify({ filename: filename, content_html: htmlText })
    });
    if (srvPreview.ok && srvPreview.data && srvPreview.data.meta) {
      const m = srvPreview.data.meta;
      if (m.title) title = m.title;
      if (m.grade !== undefined) grade = m.grade;
      if (m.subtitle) subtitle = m.subtitle;
      if (m.suggested_cover) suggestedCover = m.suggested_cover;
    }

    gameTitleInput.value = title;
    gameSubtitleInput.value = subtitle;
    state.selectedGameGrade = grade;
    state.selectedGameCover = suggestedCover;

    renderGradePicker(gameGradePicker, state.selectedGameGrade, function(g) {
      state.selectedGameGrade = g;
    });
    renderCoverPicker(gameCoverPicker, state.selectedGameCover, function(c) {
      state.selectedGameCover = c;
    });

    uploadPreviewForm.classList.add('is-active');
    showToast('Файл прочитан — проверьте поля и опубликуйте');
  }

  function compressImageToBase64(file) {
    return new Promise(function(resolve, reject) {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = function(ev) {
        const dataUrl = String(ev.target.result || '');
        const img = new Image();
        img.onerror = function() {
          // Фолбэк для нестандартных файлов
          const idx = dataUrl.indexOf(',');
          resolve({ filename: file.name, base64: idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl });
        };
        img.onload = function() {
          const maxW = 1280;
          const maxH = 720;
          let w = img.naturalWidth || img.width;
          let h = img.naturalHeight || img.height;
          if (w > maxW || h > maxH) {
            const ratio = Math.min(maxW / w, maxH / h);
            w = Math.round(w * ratio);
            h = Math.round(h * ratio);
          }
          const canvas = document.createElement('canvas');
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.fillStyle = '#f7f3ea';
          ctx.fillRect(0, 0, w, h);
          ctx.drawImage(img, 0, 0, w, h);
          const outUrl = canvas.toDataURL('image/jpeg', 0.86);
          const comma = outUrl.indexOf(',');
          const cleanName = file.name.replace(/\.[^.]+$/, '') + '.jpg';
          resolve({ filename: cleanName, base64: comma >= 0 ? outUrl.slice(comma + 1) : outUrl });
        };
        img.src = dataUrl;
      };
      reader.readAsDataURL(file);
    });
  }

  function initCustomCoverUpload() {
    if (!uploadCoverBtn || !customCoverInput) return;

    uploadCoverBtn.addEventListener('click', function() { customCoverInput.click(); });

    customCoverInput.addEventListener('change', async function() {
      const file = customCoverInput.files && customCoverInput.files[0];
      if (!file) return;

      customCoverStatus.textContent = 'Обработка...';
      try {
        const prepared = await compressImageToBase64(file);
        const res = await apiFetch('/api/admin/upload-cover', {
          method: 'POST',
          body: JSON.stringify({
            filename: prepared.filename,
            data_base64: prepared.base64
          })
        });

        if (res.ok && res.data && res.data.ok) {
          const newCoverKey = res.data.cover;
          const newCoverSrc = '/' + String(res.data.cover_src || ('covers/' + newCoverKey)).replace(/^\/+/, '');
          if (!DEFAULT_COVERS.some(function(c) { return c.key === newCoverKey; })) {
            DEFAULT_COVERS.push({ key: newCoverKey, label: 'Своя', src: newCoverSrc });
          }
          state.selectedGameCover = newCoverKey;
          renderCoverPicker(gameCoverPicker, state.selectedGameCover, function(c) {
            state.selectedGameCover = c;
          });
          customCoverStatus.textContent = 'Выбрана своя иллюстрация';
          showToast('Обложка сохранена');
        } else {
          customCoverStatus.textContent = 'Ошибка формата';
          showToast((res.data && res.data.message) || 'Поддерживаются PNG, JPEG и WEBP', 3500);
        }
      } catch (err) {
        customCoverStatus.textContent = 'Сбой чтения файла';
      }
    });
  }

  function initGamePublish() {
    if (!uploadPreviewForm) return;

    uploadPreviewForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      if (!state.selectedGameFile || !state.gameFileContent) {
        showToast('Сначала выберите файл .html');
        return;
      }

      const payload = {
        filename: state.selectedGameFile.name,
        content_html: state.gameFileContent,
        title: gameTitleInput.value.trim(),
        grade: state.selectedGameGrade,
        topic: gameTopicInput.value.trim(),
        subtitle: gameSubtitleInput.value.trim(),
        cover: state.selectedGameCover,
        hidden: gameHiddenCheck.checked
      };

      const publishBtn = document.getElementById('game-publish-btn');
      if (publishBtn) publishBtn.disabled = true;

      const res = await apiFetch('/api/admin/upload-game', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (publishBtn) publishBtn.disabled = false;

      if (res.ok && res.data && res.data.ok) {
        showToast('Тренажёр добавлен в картотеку');
        uploadPreviewForm.classList.remove('is-active');
        uploadPreviewForm.reset();
        state.selectedGameFile = null;
        state.gameFileContent = '';
        if (dropZoneFilename) dropZoneFilename.textContent = 'Перетащите .html сюда';

        openSuccessModal(res.data.item);
        await loadRegistryItems();
      } else {
        showToast((res.data && res.data.message) || 'Ошибка публикации', 4000);
      }
    });
  }

  // --- 6. Форма доски Miro / Холст ---
  function initBoardForm() {
    renderGradePicker(boardGradePicker, state.selectedBoardGrade, function(g) {
      state.selectedBoardGrade = g;
    });

    if (!boardAddForm) return;

    boardAddForm.addEventListener('submit', async function(e) {
      e.preventDefault();
      const url = boardUrlInput.value.trim();
      if (!/^https?:\/\//i.test(url)) {
        showToast('Ссылка должна начинаться с https:// или http://', 3500);
        return;
      }

      const payload = {
        url: url,
        title: boardTitleInput.value.trim(),
        grade: state.selectedBoardGrade,
        topic: boardTopicInput.value.trim(),
        subtitle: boardSubtitleInput.value.trim(),
        cover: 'board',
        hidden: boardHiddenCheck.checked
      };

      const submitBtn = document.getElementById('board-submit-btn');
      if (submitBtn) submitBtn.disabled = true;

      const res = await apiFetch('/api/admin/add-board', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (submitBtn) submitBtn.disabled = false;

      if (res.ok && res.data && res.data.ok) {
        showToast('Доска прикреплена к картотеке');
        boardAddForm.reset();
        state.selectedBoardGrade = null;
        renderGradePicker(boardGradePicker, null, function(g) { state.selectedBoardGrade = g; });

        openSuccessModal(res.data.item);
        await loadRegistryItems();
      } else {
        showToast((res.data && res.data.message) || 'Ошибка добавления доски', 4000);
      }
    });
  }

  // --- 7. Реестр материалов с 4 честными состояниями (loading, error, empty, full) ---
  async function loadRegistryItems() {
    state.registryStatus = 'loading';
    renderRegistry();

    const res = await apiFetch('/api/admin/items', { method: 'GET' });
    if (res.ok && res.data && res.data.ok) {
      applyServerMetadata(res.data);
      state.items = res.data.items || [];
      state.existingTopics = res.data.topics || [];
      if (Array.isArray(res.data.covers)) {
        res.data.covers.forEach(function(ck, idx) {
          if (!DEFAULT_COVERS.some(function(c) { return c.key === ck; })) {
            const hasExt = /\.(png|jpe?g|webp)$/i.test(ck);
            DEFAULT_COVERS.push({
              key: ck,
              label: 'Своя ' + (idx + 1),
              src: '/covers/' + (hasExt ? ck : ck + '.png')
            });
          }
        });
      }
      state.registryStatus = 'full';
      updateTopicsDatalist();
      updateTabCounts();
      renderRegistry();
    } else {
      state.registryStatus = 'error';
      state.registryError = (res.data && res.data.message) || 'Не удалось загрузить список картотеки';
      renderRegistry();
    }
  }

  function updateTopicsDatalist() {
    if (!existingTopicsDatalist) return;
    existingTopicsDatalist.innerHTML = '';
    state.existingTopics.forEach(function(t) {
      const opt = document.createElement('option');
      opt.value = t;
      existingTopicsDatalist.appendChild(opt);
    });
  }

  function updateTabCounts() {
    const counts = {
      active: state.items.filter(function(i) { return !i.hidden && !i.archived; }).length,
      hidden: state.items.filter(function(i) { return i.hidden && !i.archived; }).length,
      archived: state.items.filter(function(i) { return Boolean(i.archived); }).length,
      all: state.items.length
    };
    const labels = {
      active: 'На витрине',
      hidden: 'По ссылке',
      archived: 'Архив',
      all: 'Все'
    };
    regTabs.forEach(function(btn) {
      const key = btn.getAttribute('data-tab');
      if (labels[key] !== undefined) {
        btn.textContent = labels[key] + ' (' + counts[key] + ')';
      }
    });
  }

  function renderRegistry() {
    if (!registryList) return;

    // Состояние 1: Загрузка
    if (state.registryStatus === 'loading') {
      if (registryCountText) registryCountText.textContent = 'Обновление...';
      registryList.innerHTML = (
        '<div class="registry-state-box">' +
          '<h3 class="registry-state-title">Загружаем картотеку...</h3>' +
          '<p>Считываем список тренажёров, досок и тем уроков.</p>' +
        '</div>'
      );
      return;
    }

    // Состояние 2: Ошибка сети/чтения
    if (state.registryStatus === 'error') {
      if (registryCountText) registryCountText.textContent = 'Сбой чтения';
      registryList.innerHTML = (
        '<div class="registry-state-box">' +
          '<h3 class="registry-state-title">Не удалось получить данные</h3>' +
          '<p>' + escapeHtml(state.registryError) + '</p>' +
          '<button type="button" class="btn btn-sm" data-action="retry-load">Повторить запрос</button>' +
        '</div>'
      );
      return;
    }

    const filtered = getFilteredRegistryItems();

    if (registryCountText) {
      registryCountText.textContent = 'Показано: ' + filtered.length + ' из ' + state.items.length;
    }

    // Состояние 3: Пустая вкладка / поиск
    if (filtered.length === 0) {
      const emptyHint = state.searchQuery
        ? 'Попробуйте сократить поисковый запрос.'
        : 'Перетащите HTML-файл слева или переключите вкладку фильтра.';
      registryList.innerHTML = (
        '<div class="registry-state-box">' +
          '<h3 class="registry-state-title">В этом разделе пока пусто</h3>' +
          '<p>' + escapeHtml(emptyHint) + '</p>' +
        '</div>'
      );
      return;
    }

    // Состояние 4: Наполненный реестр
    registryList.innerHTML = filtered.map(function(item, idx) {
      const isBoard = item.kind === 'board';
      const gradeText = item.grade ? (item.grade + ' класс') : 'Вне класса';
      const rawCoverSrc = item.cover_src || ('covers/' + (item.cover || 'library') + '.png');
      const coverSrc = '/' + String(rawCoverSrc).replace(/^\/+/, '');
      const numStr = String(idx + 1).padStart(2, '0');

      let badges = '<span class="badge-pill">' + escapeHtml(gradeText) + '</span>';
      badges += ' <span class="badge-pill' + (isBoard ? ' is-board' : '') + '">' + (isBoard ? 'Доска урока' : 'Тренажёр') + '</span>';
      if (item.hidden) badges += ' <span class="badge-pill is-hidden">По ссылке</span>';
      if (item.archived) badges += ' <span class="badge-pill is-archived">Архив</span>';

      return (
        '<div class="registry-item-row' + (item.archived ? ' is-archived' : '') + '" data-id="' + escapeHtml(item.id) + '">' +
          '<span class="reg-order-num">' + numStr + '</span>' +
          '<div class="reg-item-thumb">' +
            '<img src="' + escapeHtml(coverSrc) + '" alt="' + escapeHtml(item.title) + '" onerror="this.style.opacity=\'0.2\'">' +
          '</div>' +
          '<div class="reg-item-info">' +
            '<span class="reg-item-title">' + escapeHtml(item.title) + '</span>' +
            '<div class="reg-item-meta">' +
              badges +
              (item.topic ? ('<span>Тема: <strong>' + escapeHtml(item.topic) + '</strong></span>') : '') +
            '</div>' +
          '</div>' +
          '<div class="reg-item-actions">' +
            '<button type="button" class="icon-btn" data-action="move-up" data-id="' + escapeHtml(item.id) + '" title="Выше" aria-label="Поднять выше" ' + (idx === 0 ? 'disabled' : '') + '>↑</button>' +
            '<button type="button" class="icon-btn" data-action="move-down" data-id="' + escapeHtml(item.id) + '" title="Ниже" aria-label="Опустить ниже" ' + (idx === filtered.length - 1 ? 'disabled' : '') + '>↓</button>' +
            '<button type="button" class="btn btn-sm" data-action="show-qr" data-id="' + escapeHtml(item.id) + '">QR и ссылка</button>' +
            '<button type="button" class="btn btn-sm" data-action="edit" data-id="' + escapeHtml(item.id) + '">Изменить</button>' +
            '<button type="button" class="btn btn-sm" data-action="toggle-hidden" data-id="' + escapeHtml(item.id) + '">' + (item.hidden ? 'На витрину' : 'Скрыть') + '</button>' +
            '<button type="button" class="btn btn-sm ' + (item.archived ? 'btn-primary' : 'btn-danger-ghost') + '" data-action="toggle-archive" data-id="' + escapeHtml(item.id) + '">' + (item.archived ? 'Вернуть' : 'В архив') + '</button>' +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  function initRegistryEvents() {
    regTabs.forEach(function(btn) {
      btn.addEventListener('click', function() {
        regTabs.forEach(function(b) { b.classList.remove('is-active'); });
        btn.classList.add('is-active');
        state.currentTab = btn.getAttribute('data-tab');
        renderRegistry();
      });
    });

    if (registrySearchInput) {
      registrySearchInput.addEventListener('input', function() {
        state.searchQuery = registrySearchInput.value.trim();
        renderRegistry();
      });
    }

    if (registryList) {
      registryList.addEventListener('click', async function(e) {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;

        const action = btn.getAttribute('data-action');
        if (action === 'retry-load') {
          await loadRegistryItems();
          return;
        }

        const id = btn.getAttribute('data-id');
        const item = state.items.find(function(i) { return i.id === id; });
        if (!item) return;

        if (action === 'move-up' || action === 'move-down') {
          await handleReorder(id, action);
        } else if (action === 'show-qr') {
          openSuccessModal(item);
        } else if (action === 'toggle-hidden') {
          await updateItem(id, { hidden: !item.hidden });
        } else if (action === 'edit') {
          openEditModal(item);
        } else if (action === 'toggle-archive') {
          await toggleArchive(id, !item.archived);
        }
      });
    }
  }

  function getFilteredRegistryItems() {
    let filtered = state.items.slice();
    if (state.currentTab === 'active') {
      filtered = filtered.filter(function(i) { return !i.hidden && !i.archived; });
    } else if (state.currentTab === 'hidden') {
      filtered = filtered.filter(function(i) { return i.hidden && !i.archived; });
    } else if (state.currentTab === 'archived') {
      filtered = filtered.filter(function(i) { return i.archived === true; });
    }
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      filtered = filtered.filter(function(i) {
        return (i.title && i.title.toLowerCase().indexOf(q) !== -1) ||
               (i.topic && i.topic.toLowerCase().indexOf(q) !== -1) ||
               (i.grade && String(i.grade).indexOf(q) !== -1);
      });
    }
    return filtered;
  }

  async function handleReorder(id, direction) {
    const filtered = getFilteredRegistryItems();
    const fIdx = filtered.findIndex(function(i) { return i.id === id; });
    if (fIdx === -1) return;

    const fTargetIdx = direction === 'move-up' ? fIdx - 1 : fIdx + 1;
    if (fTargetIdx < 0 || fTargetIdx >= filtered.length) return;

    const neighborId = filtered[fTargetIdx].id;
    const idx = state.items.findIndex(function(i) { return i.id === id; });
    const targetIdx = state.items.findIndex(function(i) { return i.id === neighborId; });
    if (idx === -1 || targetIdx === -1) return;

    const temp = state.items[idx];
    state.items[idx] = state.items[targetIdx];
    state.items[targetIdx] = temp;
    renderRegistry();

    const ids = state.items.map(function(i) { return i.id; });
    const res = await apiFetch('/api/admin/reorder', {
      method: 'POST',
      body: JSON.stringify({ ids: ids })
    });
    if (!res.ok) {
      showToast('Не удалось сохранить порядок');
      await loadRegistryItems();
    }
  }

  async function updateItem(id, fields) {
    const res = await apiFetch('/api/admin/items/' + encodeURIComponent(id), {
      method: 'PUT',
      body: JSON.stringify(fields)
    });
    if (res.ok && res.data && res.data.ok) {
      showToast('Изменения сохранены');
      await loadRegistryItems();
    } else {
      showToast((res.data && res.data.message) || 'Ошибка сохранения', 3500);
    }
  }

  async function toggleArchive(id, shouldArchive) {
    const res = await apiFetch('/api/admin/archive/' + encodeURIComponent(id), {
      method: 'POST',
      body: JSON.stringify({ archived: shouldArchive })
    });
    if (res.ok && res.data && res.data.ok) {
      showToast(shouldArchive ? 'Перемещено в архив' : 'Возвращено из архива');
      await loadRegistryItems();
    } else {
      showToast('Не удалось изменить статус архива');
    }
  }

  // --- 8. Модальное окно редактирования ---
  function openEditModal(item) {
    editItemId.value = item.id;
    editTitleInput.value = item.title || '';
    editTopicInput.value = item.topic || '';
    editSubtitleInput.value = item.subtitle || '';
    editHiddenCheck.checked = Boolean(item.hidden);

    state.editItemGrade = item.grade;
    state.editItemCover = item.cover || 'library';

    if (item.kind === 'board') {
      editUrlField.style.display = 'flex';
      editUrlInput.value = item.url || '';
    } else {
      editUrlField.style.display = 'none';
      editUrlInput.value = '';
    }

    renderGradePicker(editGradePicker, state.editItemGrade, function(g) {
      state.editItemGrade = g;
    });
    renderCoverPicker(editCoverPicker, state.editItemCover, function(c) {
      state.editItemCover = c;
    });

    editModal.classList.add('is-open');
  }

  function closeEditModal() {
    if (editModal) editModal.classList.remove('is-open');
  }

  function initEditModal() {
    if (editModalClose) editModalClose.addEventListener('click', closeEditModal);
    if (editCancelBtn) editCancelBtn.addEventListener('click', closeEditModal);
    if (editModal) {
      editModal.addEventListener('click', function(e) {
        if (e.target === editModal) closeEditModal();
      });
    }

    if (editItemForm) {
      editItemForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const id = editItemId.value;
        const payload = {
          title: editTitleInput.value.trim(),
          grade: state.editItemGrade,
          topic: editTopicInput.value.trim(),
          subtitle: editSubtitleInput.value.trim(),
          cover: state.editItemCover,
          hidden: editHiddenCheck.checked
        };
        if (editUrlField.style.display !== 'none') {
          payload.url = editUrlInput.value.trim();
        }
        await updateItem(id, payload);
        closeEditModal();
      });
    }
  }

  // --- 9. Модальное окно QR-выдачи (с учётом public_catalog_url) ---
  function buildPublicUrl(relPath) {
    const base = state.publicCatalogUrl && /^https?:\/\//i.test(state.publicCatalogUrl)
      ? state.publicCatalogUrl
      : (window.location.origin + '/');
    return new URL(relPath.replace(/^\/+/, ''), base.endsWith('/') ? base : (base + '/')).href;
  }

  function openSuccessModal(item) {
    if (!item) return;

    successTitle.textContent = item.title || 'Карточка материала';

    let itemUrl = '';
    if (item.kind === 'board') {
      itemUrl = item.url;
    } else {
      itemUrl = buildPublicUrl('g/' + item.slug + '/index.html');
    }

    successGameUrlInput.value = itemUrl;
    successOpenGameLink.href = itemUrl;

    if (item.topic) {
      const topicSlug = item.topic_slug || item.topic.toLowerCase().replace(/\s+/g, '-');
      const lessonUrl = buildPublicUrl('#lesson/' + topicSlug);
      successLessonUrlInput.value = lessonUrl;
      successLessonRow.style.display = 'flex';
    } else {
      successLessonRow.style.display = 'none';
    }

    successQrWrap.innerHTML = '';
    if (window.TutorQR && typeof window.TutorQR.renderSVG === 'function') {
      successQrWrap.innerHTML = window.TutorQR.renderSVG(itemUrl, {
        size: 228,
        margin: 3,
        colorDark: '#141926',
        colorLight: '#ffffff'
      });
    }

    successModal.classList.add('is-open');
  }

  function closeSuccessModal() {
    if (successModal) successModal.classList.remove('is-open');
  }

  function initSuccessModal() {
    if (successModalClose) successModalClose.addEventListener('click', closeSuccessModal);
    if (successDoneBtn) successDoneBtn.addEventListener('click', closeSuccessModal);
    if (successModal) {
      successModal.addEventListener('click', function(e) {
        if (e.target === successModal) closeSuccessModal();
      });
    }

    if (successCopyGameBtn) {
      successCopyGameBtn.addEventListener('click', function() {
        copyText(successGameUrlInput.value, function() {
          showToast('Прямая ссылка скопирована');
        });
      });
    }

    if (successCopyLessonBtn) {
      successCopyLessonBtn.addEventListener('click', function() {
        copyText(successLessonUrlInput.value, function() {
          showToast('Ссылка на весь урок скопирована');
        });
      });
    }

    window.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        closeSuccessModal();
        closeEditModal();
      }
    });
  }

  // Запуск Мастерской
  initTheme();
  initAuth();
  initIntakeTabs();
  initGameDropZone();
  initCustomCoverUpload();
  initGamePublish();
  initBoardForm();
  initRegistryEvents();
  initEditModal();
  initSuccessModal();
  checkSession();
})();
