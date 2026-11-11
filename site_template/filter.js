/**
 * filter.js — Чистые функции фильтрации, группировки уроков и маршрутизации каталога.
 * Не содержит манипуляций с DOM.
 * 
 * Экспорт:
 *   window.CatalogFilter = {
 *     normalize,
 *     slugify,
 *     slugifyTopic,
 *     filterItems,
 *     collectGrades,
 *     groupByTopics,
 *     parseRouteHash
 *   };
 */
(function(root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.CatalogFilter = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';

  // Таблица транслитерации ГОСТ 7.79-2000 (система Б) — 100% совпадение с Python publish.py
  var TRANSLIT_MAP = {
    'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',  'е': 'e',  'ё': 'yo',
    'ж': 'zh', 'з': 'z',  'и': 'i',  'й': 'y',  'к': 'k',  'л': 'l',  'м': 'm',
    'н': 'n',  'о': 'o',  'п': 'p',  'р': 'r',  'с': 's',  'т': 't',  'у': 'u',
    'ф': 'f',  'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ъ': '',   'ы': 'y',  'ь': '',   'э': 'e',  'ю': 'yu', 'я': 'ya'
  };

  /**
   * Нормализует строку для поиска и сопоставления:
   * - приведение к нижнему регистру
   * - замена ё/Ё на е
   * - схлопывание повторных пробелов и trim
   * @param {any} val
   * @returns {string}
   */
  function normalize(val) {
    if (val === null || val === undefined) {
      return '';
    }
    return String(val)
      .toLowerCase()
      .replace(/[ёЁ]/g, 'е')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /**
   * Генерация слага из текста по упрощенной системе ГОСТ 7.79-2000 (сист. Б).
   * Совпадает с функцией slugify в tools/publish.py.
   * @param {string} text
   * @returns {string}
   */
  function slugify(text) {
    if (text === null || text === undefined) {
      return '';
    }
    var str = String(text).toLowerCase();
    var chars = [];
    for (var i = 0; i < str.length; i++) {
      var ch = str.charAt(i);
      if (Object.prototype.hasOwnProperty.call(TRANSLIT_MAP, ch)) {
        chars.push(TRANSLIT_MAP[ch]);
      } else if (/[a-z0-9]/.test(ch)) {
        chars.push(ch);
      } else {
        chars.push('-');
      }
    }
    var res = chars.join('').replace(/-+/g, '-').replace(/^-+|-+$/g, '');
    return res;
  }

  /**
   * Генерация слага для темы урока: slugify(f"{topic}-{grade}" if grade else topic).
   * @param {string} topic - название темы
   * @param {number|string|null} [grade] - класс
   * @returns {string}
   */
  function slugifyTopic(topic, grade) {
    var t = String(topic == null ? '' : topic).trim();
    if (!t) return '';
    var hasGrade = grade !== null && grade !== undefined && grade !== '' && !isNaN(Number(grade));
    var raw = hasGrade ? (t + '-' + Number(grade)) : t;
    var s = slugify(raw);
    return s || 'urok';
  }

  /**
   * Фильтрует массив элементов каталога по параметрам:
   * { query, grade, kind, topic_slug, includeHidden }
   * 
   * По умолчанию скрывает элементы с hidden === true и archived === true.
   * @param {Array} items - элементы каталога
   * @param {Object} [filters] - параметры фильтрации
   * @returns {Array} отфильтрованный массив элементов
   */
  function filterItems(items, filters) {
    if (!Array.isArray(items)) {
      return [];
    }
    filters = filters || {};
    var normQuery = normalize(filters.query);
    var includeHidden = Boolean(filters.includeHidden);

    var hasGradeFilter = filters.grade !== undefined && filters.grade !== '' && filters.grade !== 'all';
    var isGradeNull = hasGradeFilter && (filters.grade === null || filters.grade === 'null' || filters.grade === 'none');
    var targetGrade = hasGradeFilter && !isGradeNull ? Number(filters.grade) : null;

    var hasKindFilter = filters.kind !== undefined && filters.kind !== '' && filters.kind !== 'all';
    var targetKind = hasKindFilter ? String(filters.kind).toLowerCase().trim() : null;

    var targetTopicSlug = (filters.topic_slug != null && filters.topic_slug !== '')
      ? String(filters.topic_slug).trim().toLowerCase()
      : null;

    return items.filter(function(item) {
      if (!item) return false;

      // 0. Скрытие скрытых и архивированных по умолчанию
      if (!includeHidden) {
        if (item.hidden === true || item.archived === true) {
          return false;
        }
      }

      // 1. Фильтрация по теме урока (topic_slug)
      if (targetTopicSlug) {
        var itemSlug = item.topic_slug || slugifyTopic(item.topic, item.grade);
        if (itemSlug.toLowerCase() !== targetTopicSlug) {
          return false;
        }
      }

      // 2. Фильтрация по классу
      if (hasGradeFilter) {
        if (isGradeNull) {
          if (item.grade !== null && item.grade !== undefined && item.grade !== '') {
            return false;
          }
        } else {
          if (item.grade === null || item.grade === undefined || item.grade === '' || Number(item.grade) !== targetGrade) {
            return false;
          }
        }
      }

      // 3. Фильтрация по типу (game / board)
      if (hasKindFilter) {
        var itemKind = (item.kind || 'game').toLowerCase().trim();
        if (itemKind !== targetKind) {
          return false;
        }
      }

      // 4. Поиск по строке (название, тема, описание, теги)
      if (normQuery) {
        var titleNorm = normalize(item.title);
        var topicNorm = normalize(item.topic);
        var subtitleNorm = normalize(item.subtitle);
        var titleMatch = titleNorm.indexOf(normQuery) !== -1;
        var topicMatch = topicNorm.indexOf(normQuery) !== -1;
        var subtitleMatch = subtitleNorm.indexOf(normQuery) !== -1;

        var tagMatch = false;
        if (Array.isArray(item.tags)) {
          for (var i = 0; i < item.tags.length; i++) {
            if (normalize(item.tags[i]).indexOf(normQuery) !== -1) {
              tagMatch = true;
              break;
            }
          }
        } else if (item.tags) {
          tagMatch = normalize(item.tags).indexOf(normQuery) !== -1;
        }

        if (!titleMatch && !topicMatch && !subtitleMatch && !tagMatch) {
          return false;
        }
      }

      return true;
    });
  }

  /**
   * Собирает уникальные классы из списка элементов:
   * числовые классы сортируются по возрастанию, а null помещается в конец (если присутствует).
   * @param {Array} items
   * @returns {Array<number|null>}
   */
  function collectGrades(items) {
    if (!Array.isArray(items)) {
      return [];
    }
    var numbersMap = {};
    var hasNull = false;

    items.forEach(function(item) {
      if (!item || item.archived === true) return;
      if (item.grade === null || item.grade === undefined || item.grade === '' || isNaN(Number(item.grade))) {
        hasNull = true;
      } else {
        numbersMap[Number(item.grade)] = true;
      }
    });

    var sortedNumbers = Object.keys(numbersMap).map(Number).sort(function(a, b) {
      return a - b;
    });

    if (hasNull) {
      sortedNumbers.push(null);
    }

    return sortedNumbers;
  }

  /**
   * Группирует видимые элементы с непустым полем topic в уроки (коллекции тем).
   * Возвращает массив уроков:
   * [{ topic, topic_slug, grade, items, count, cover_src, min_order }]
   * Сортировка уроков: сначала по min_order (по возрастанию), затем по алфавиту названия.
   * @param {Array} items
   * @returns {Array}
   */
  function groupByTopics(items) {
    if (!Array.isArray(items)) {
      return [];
    }
    var groupsMap = {};

    items.forEach(function(item) {
      if (!item) return;
      if (item.hidden === true || item.archived === true) return;
      var rawTopic = item.topic ? String(item.topic).trim() : '';
      if (!rawTopic) return;

      var slug = item.topic_slug || slugifyTopic(rawTopic, item.grade);
      if (!slug) return;

      var orderVal = typeof item.order === 'number' && !isNaN(item.order) ? item.order : 99999;

      if (!groupsMap[slug]) {
        groupsMap[slug] = {
          topic: rawTopic,
          topic_slug: slug,
          grade: (item.grade !== null && item.grade !== undefined && item.grade !== '' && !isNaN(Number(item.grade)))
            ? Number(item.grade)
            : null,
          items: [],
          count: 0,
          cover_src: null,
          cover: null,
          min_order: orderVal
        };
      }

      var g = groupsMap[slug];
      g.items.push(item);
      g.count++;
      if (orderVal < g.min_order) {
        g.min_order = orderVal;
      }
      if (!g.cover_src && item.cover_src) {
        g.cover_src = item.cover_src;
      }
      if (!g.cover && item.cover) {
        g.cover = item.cover;
      }
      // Если у темы есть айтемы с разными классами, сохраняем null или согласованный класс
      if (g.grade !== null && item.grade !== null && item.grade !== undefined && Number(item.grade) !== g.grade) {
        g.grade = null; // смешанный урок
      }
    });

    var result = Object.keys(groupsMap).map(function(slug) {
      var g = groupsMap[slug];
      // Внутри урока сортируем материалы по order
      g.items.sort(function(a, b) {
        var oa = typeof a.order === 'number' ? a.order : 99999;
        var ob = typeof b.order === 'number' ? b.order : 99999;
        return oa - ob;
      });
      return g;
    });

    // Сортировка уроков между собой
    result.sort(function(a, b) {
      if (a.min_order !== b.min_order) {
        return a.min_order - b.min_order;
      }
      return a.topic.localeCompare(b.topic, 'ru');
    });

    return result;
  }

  /**
   * Разбирает hash из адресной строки:
   * "" или "#" -> { mode: 'all' }
   * "#lesson/<topic_slug>" -> { mode: 'lesson', topic_slug: '<topic_slug>' }
   * "#<slug>" -> { mode: 'item', slug: '<slug>' }
   * @param {string} hash
   * @returns {{ mode: string, topic_slug?: string, slug?: string }}
   */
  function parseRouteHash(hash) {
    if (!hash) {
      return { mode: 'all' };
    }
    var clean = String(hash).replace(/^#+/, '').trim();
    if (!clean) {
      return { mode: 'all' };
    }

    try {
      clean = decodeURIComponent(clean);
    } catch (e) {}

    if (clean.indexOf('lesson/') === 0) {
      var topicSlug = clean.slice('lesson/'.length).trim();
      return {
        mode: 'lesson',
        topic_slug: topicSlug
      };
    }
    if (clean.indexOf('topic=') === 0) {
      var topicParam = clean.slice('topic='.length).trim();
      return {
        mode: 'lesson',
        topic_slug: topicParam
      };
    }

    return {
      mode: 'item',
      slug: clean
    };
  }

  return {
    normalize: normalize,
    slugify: slugify,
    slugifyTopic: slugifyTopic,
    filterItems: filterItems,
    collectGrades: collectGrades,
    groupByTopics: groupByTopics,
    parseRouteHash: parseRouteHash
  };
});
