/**
 * shell.js — Книжная закладка возврата для учебных тренажёров «Словесность».
 *
 * Вставляет в изолированный Shadow DOM аккуратную хлопковую закладку «← В картотеку»
 * (с возвратом в активный урок #lesson/<topic_slug> или к карточке #<slug>).
 * Поддерживает safe-area, сворачивание в компактный ярлычок и API TutorShell.sendResult.
 */
(function() {
  'use strict';

  if (window.TutorShell) {
    return;
  }

  function getGameSlug() {
    const scriptEl = document.querySelector('script[data-tutor-shell]') || document.currentScript;
    if (scriptEl) {
      const slug = scriptEl.getAttribute('data-slug');
      if (slug) return slug.trim();
    }
    return '';
  }

  const slug = getGameSlug();
  const COLLAPSED_STORAGE_KEY = 'tutorshell:collapsed';

  function getCatalogReturnUrl() {
    try {
      const returnHash = sessionStorage.getItem('tutorshell:return_hash');
      if (returnHash && typeof returnHash === 'string' && returnHash.indexOf('#lesson/') === 0) {
        return '../../index.html' + returnHash;
      }
    } catch (e) {}
    return '../../index.html' + (slug ? '#' + encodeURIComponent(slug) : '');
  }

  /**
   * Фиксация результата прохождения упражнения.
   * @param {number} score - набранные баллы
   * @param {number} max - максимум баллов
   * @param {any} [details] - детали ответов
   * @returns {boolean}
   */
  function sendResult(score, max, details) {
    if (
      typeof score !== 'number' ||
      typeof max !== 'number' ||
      !Number.isFinite(score) ||
      !Number.isFinite(max) ||
      score < 0 ||
      max <= 0 ||
      score > max
    ) {
      console.warn('[TutorShell] Некорректные параметры sendResult:', { score: score, max: max, details: details });
      return false;
    }

    const payload = {
      slug: slug,
      score: score,
      max: max,
      details: details !== undefined ? details : null,
      timestamp: new Date().toISOString()
    };

    try {
      const storageKey = 'tutorshell:last:' + (slug || 'unknown');
      sessionStorage.setItem(storageKey, JSON.stringify(payload));
    } catch (err) {
      console.warn('[TutorShell] Не удалось записать в sessionStorage:', err);
    }

    return true;
  }

  window.TutorShell = {
    slug: slug,
    sendResult: sendResult,
    getCatalogReturnUrl: getCatalogReturnUrl
  };

  function initShellUI() {
    if (document.getElementById('tutor-shell-host')) {
      return;
    }

    const host = document.createElement('div');
    host.id = 'tutor-shell-host';
    host.style.position = 'fixed';
    host.style.top = '0';
    host.style.left = '0';
    host.style.width = '0';
    host.style.height = '0';
    host.style.zIndex = '2147483000';
    host.style.pointerEvents = 'none';

    const shadow = host.attachShadow({ mode: 'open' });

    let isCollapsed = false;
    try {
      isCollapsed = sessionStorage.getItem(COLLAPSED_STORAGE_KEY) === '1';
    } catch (e) {}

    const style = document.createElement('style');
    style.textContent = [
      ':host { all: initial; }',
      '.tutor-shell-wrap {',
      '  position: fixed;',
      '  bottom: calc(14px + env(safe-area-inset-bottom, 0px));',
      '  left: calc(14px + env(safe-area-inset-left, 0px));',
      '  display: inline-flex;',
      '  align-items: center;',
      '  background: #fcfaf5;',
      '  color: #141926;',
      '  border: 1px solid #bfb49f;',
      '  border-left: 3px solid #bf3926;',
      '  border-radius: 6px;',
      '  box-shadow: 0 3px 12px rgba(20, 25, 38, 0.14);',
      '  pointer-events: auto;',
      '  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;',
      '  font-size: 14px;',
      '  line-height: 1;',
      '  user-select: none;',
      '  -webkit-user-select: none;',
      '  transition: background-color 140ms cubic-bezier(0.22, 1, 0.36, 1), box-shadow 140ms cubic-bezier(0.22, 1, 0.36, 1);',
      '}',
      '.tutor-shell-wrap:hover {',
      '  background: #f7f3ea;',
      '  box-shadow: 0 5px 16px rgba(20, 25, 38, 0.2);',
      '}',
      '.catalog-link {',
      '  display: inline-flex;',
      '  align-items: center;',
      '  gap: 7px;',
      '  min-height: 44px;',
      '  padding: 0 12px;',
      '  color: #141926;',
      '  text-decoration: none;',
      '  font-weight: 600;',
      '  box-sizing: border-box;',
      '}',
      '.catalog-link:focus-visible, .toggle-btn:focus-visible {',
      '  outline: 2px solid #2346a0;',
      '  outline-offset: 2px;',
      '}',
      '.arrow {',
      '  color: #bf3926;',
      '  font-size: 16px;',
      '  transition: transform 140ms cubic-bezier(0.22, 1, 0.36, 1);',
      '}',
      '.catalog-link:hover .arrow {',
      '  transform: translateX(-2px);',
      '}',
      '.toggle-btn {',
      '  display: inline-flex;',
      '  align-items: center;',
      '  justify-content: center;',
      '  min-width: 38px;',
      '  min-height: 44px;',
      '  background: transparent;',
      '  border: none;',
      '  border-left: 1px solid #dfd7c7;',
      '  color: #555c70;',
      '  font-size: 15px;',
      '  cursor: pointer;',
      '  padding: 0;',
      '  box-sizing: border-box;',
      '  transition: background-color 140ms cubic-bezier(0.22, 1, 0.36, 1), color 140ms cubic-bezier(0.22, 1, 0.36, 1);',
      '}',
      '.toggle-btn:hover {',
      '  background: #efe9dc;',
      '  color: #141926;',
      '}',
      '.tutor-shell-wrap.is-collapsed .catalog-link {',
      '  display: none;',
      '}',
      '.tutor-shell-wrap.is-collapsed .toggle-btn {',
      '  border-left: none;',
      '  min-width: 44px;',
      '  color: #141926;',
      '  font-weight: 600;',
      '}',
      '@media (prefers-reduced-motion: reduce) {',
      '  .tutor-shell-wrap, .arrow, .toggle-btn { transition: none; }',
      '}'
    ].join('\n');

    const wrap = document.createElement('div');
    wrap.className = 'tutor-shell-wrap' + (isCollapsed ? ' is-collapsed' : '');

    const link = document.createElement('a');
    link.className = 'catalog-link';
    link.href = getCatalogReturnUrl();
    link.title = 'Вернуться в картотеку уроков';
    link.innerHTML = '<span class="arrow" aria-hidden="true">←</span><span>В картотеку</span>';

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'toggle-btn';

    function syncToggleState(collapsed) {
      if (collapsed) {
        wrap.classList.add('is-collapsed');
        toggle.textContent = '←';
        toggle.title = 'Развернуть закладку возврата';
      } else {
        wrap.classList.remove('is-collapsed');
        toggle.textContent = '−';
        toggle.title = 'Свернуть закладку';
      }
      toggle.setAttribute('aria-label', toggle.title);
    }

    syncToggleState(isCollapsed);

    toggle.addEventListener('click', function(e) {
      e.stopPropagation();
      const nextCollapsed = !wrap.classList.contains('is-collapsed');
      syncToggleState(nextCollapsed);
      try {
        sessionStorage.setItem(COLLAPSED_STORAGE_KEY, nextCollapsed ? '1' : '0');
      } catch (err) {}
    });

    wrap.appendChild(link);
    wrap.appendChild(toggle);
    shadow.appendChild(style);
    shadow.appendChild(wrap);

    const targetBody = document.body || document.documentElement;
    targetBody.appendChild(host);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initShellUI);
  } else {
    initShellUI();
  }
})();
