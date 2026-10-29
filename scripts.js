"use strict";

    // Where the data files are. "ouput" matches the project's folder name.
    const DATA_DIR = "data/ouput/";
    // Image links in the JSON files are relative to the parent of the images folder, which is data/
    const IMAGE_BASE = "data/";
    const STORAGE_KEY = "cozy-game-kiwi:language";
    const CATEGORY_ORDER = ["normal", "dark_cuisine", "messy"];

    // Supported languages: they drive both the interface and the search. To add one, add an entry here
    // (code = the one used in translations.json) and, optionally, its interface texts in UI below.
    const LANGUAGES = [
      { code: "en", label: "English" },
      { code: "vi", label: "Tiếng Việt" },
    ];

    // Interface texts. A language without an entry here falls back to English: add one to translate the interface.
    const UI = {
      en: {
        ingredients: "Ingredients",
        recipes: "Recipes",
        menus: "Menu collections",
        categories: { normal: "Normal", dark_cuisine: "Dark cuisine", messy: "Messy" },
        searchPlaceholder: "Recipe or ingredient name",
        languageLabel: "Language",
        menuLabel: "Menu collection",
        back: "Back to results",
        ingredientsTitle: "Ingredients",
        noMenus: "No menu collections available.",
        menuEmpty: "This collection has no recipes.",
        noResults: "No recipes match “{query}”. Check the spelling, or switch the language to search names in another language.",
        loading: "Loading recipes…",
        loadError: "Couldn't load the data. Open this page through a web server (for example, run python3 -m http.server in the project folder) and check that {path} exists.",
        missingFiles: "Couldn't load {files}. Names fall back to English and some counts may be missing.",
        ingredientGroup: "Ingredient group",
      },
      vi: {
        ingredients: "Nguyên liệu",
        recipes: "Món ăn",
        menus: "Bộ sưu tập menu",
        categories: { normal: "Thường", dark_cuisine: "Hắc ám", messy: "Lộn xộn" },
        searchPlaceholder: "Tên món hoặc tên nguyên liệu",
        languageLabel: "Ngôn ngữ",
        menuLabel: "Bộ sưu tập menu",
        back: "Quay lại kết quả",
        ingredientsTitle: "Nguyên liệu",
        noMenus: "Chưa có bộ sưu tập menu nào.",
        menuEmpty: "Bộ sưu tập này chưa có món ăn.",
        noResults: "Không có món nào khớp “{query}”. Hãy kiểm tra chính tả, hoặc đổi ngôn ngữ để tìm theo tên ở ngôn ngữ khác.",
        loading: "Đang tải món ăn…",
        loadError: "Không tải được dữ liệu. Hãy mở trang qua một web server (ví dụ chạy python3 -m http.server trong thư mục dự án) và kiểm tra file {path}.",
        missingFiles: "Không tải được {files}. Tên sẽ hiển thị bằng tiếng Anh và một số số liệu có thể bị thiếu.",
        ingredientGroup: "Nhóm nguyên liệu",
      },
    };

    const state = { lang: initialLanguage(), menuId: "", query: "", selected: null };
    const app = {
      recipes: [],
      ingredients: [],
      menus: [],
      translations: null,
      missing: [],
      ingredientByName: new Map(),
      recipeIndexByName: new Map(),
      recipeIndexByLowerName: new Map(),
      indexes: new Map(),
      allIndices: [],
      results: [],
      tokens: [],
      collator: new Intl.Collator("en"),
      ready: false,
    };

    const el = Object.fromEntries(
      ["language", "search", "menu", "results", "menu-recipes", "menu-panel", "search-hint", "mix", "legend",
        "stat-ingredients", "stat-recipes", "stat-menus"].map((id) => [id, document.getElementById(id)]),
    );

    // ---- Small helpers -------------------------------------------------------------------------------------------

    function h(tag, props = {}, ...children) {
      const node = document.createElement(tag);
      for (const [key, value] of Object.entries(props)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === "text") node.textContent = value;
        else node.setAttribute(key, value === true ? "" : value);
      }
      node.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
      return node;
    }

    function initialLanguage() {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === "en" || saved === "vi") return saved;
      } catch { /* storage can be unavailable */ }
      for (const tag of navigator.languages || [navigator.language]) {
        const code = String(tag).toLowerCase().split("-")[0];
        if (code === "vi") return "vi";
      }
      return "en";
    }

    const uiLanguage = () => (UI[state.lang] ? state.lang : "en");
    const languageLabel = (code) => LANGUAGES.find((language) => language.code === code)?.label ?? code;

    function text(key, vars = {}) {
      const template = UI[uiLanguage()][key] ?? UI.en[key] ?? key;
      return template.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`));
    }

    function categoryLabel(category) {
      return UI[uiLanguage()].categories[category] ?? UI.en.categories[category] ?? category;
    }

    const formatNumber = (n) => new Intl.NumberFormat(state.lang).format(n);

    // Search is case-insensitive and ignores accents, so "trung" finds "Trứng"
    function fold(value) {
      return value.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d");
    }

    // Like fold(), but also returns, for every folded character, where it came from in the original text
    function foldWithMap(value) {
      let folded = "";
      const map = [];
      let position = 0;
      for (const char of value) {
        const piece = fold(char);
        for (let i = 0; i < piece.length; i += 1) map.push(position);
        folded += piece;
        position += char.length;
      }
      return { folded, map };
    }

    function tokensOf(query) {
      return fold(query).split(/\s+/).filter(Boolean);
    }

    // The original text split into plain strings and <mark> elements around the matched tokens
    function highlighted(value, tokens) {
      if (!tokens.length) return [value];
      const { folded, map } = foldWithMap(value);
      const ranges = [];
      for (const token of tokens) {
        let at = folded.indexOf(token);
        while (at !== -1) {
          const last = map[at + token.length - 1];
          ranges.push([map[at], last + String.fromCodePoint(value.codePointAt(last)).length]);
          at = folded.indexOf(token, at + token.length);
        }
      }
      if (!ranges.length) return [value];
      ranges.sort((a, b) => a[0] - b[0]);
      const merged = [ranges[0]];
      for (const [start, end] of ranges.slice(1)) {
        const previous = merged[merged.length - 1];
        if (start <= previous[1]) previous[1] = Math.max(previous[1], end);
        else merged.push([start, end]);
      }
      const nodes = [];
      let cursor = 0;
      for (const [start, end] of merged) {
        if (start > cursor) nodes.push(value.slice(cursor, start));
        nodes.push(h("mark", { text: value.slice(start, end) }));
        cursor = end;
      }
      if (cursor < value.length) nodes.push(value.slice(cursor));
      return nodes;
    }

    // ---- Names and descriptions in the selected language ---------------------------------------------------------

    function nameOf(name, lang = state.lang) {
      return app.translations?.[name]?.name?.[lang] || name;
    }

    function descriptionOf(recipe) {
      return app.translations?.[recipe.name]?.description?.[state.lang] || recipe.description || "";
    }

    function menuText(menu, field) {
      return menu.translations?.[field]?.[state.lang] || menu[field] || "";
    }

    function imageUrl(path) {
      return path ? IMAGE_BASE + path : null;
    }

    // ---- Loading -------------------------------------------------------------------------------------------------

    async function fetchJson(files) {
      let lastError;
      for (const file of [].concat(files)) {
        try {
          const response = await fetch(DATA_DIR + file);
          if (!response.ok) throw new Error(`${DATA_DIR}${file}: HTTP ${response.status}`);
          return await response.json();
        } catch (error) {
          lastError = error;
        }
      }
      throw lastError;
    }

    async function loadData() {
      const optional = async (name, files, fallback) => {
        try {
          return await fetchJson(files);
        } catch {
          app.missing.push(name);
          return fallback;
        }
      };
      app.recipes = await fetchJson("recipes.json");
      [app.ingredients, app.menus, app.translations] = await Promise.all([
        optional("ingredients.json", "ingredients.json", []),
        optional("menu-collections.json", ["menu-collections.json", "menu_collections.json"], []),
        optional("translations.json", "translations.json", null),
      ]);

      app.menus.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
      app.ingredientByName = new Map(app.ingredients.map((ingredient) => [ingredient.name, ingredient]));
      app.recipes.forEach((recipe, index) => {
        app.recipeIndexByName.set(recipe.name, index);
        app.recipeIndexByLowerName.set(recipe.name.toLowerCase(), index);
      });
      app.allIndices = app.recipes.map((_, index) => index);
    }

    // ---- Search --------------------------------------------------------------------------------------------------

    // Per language: for every recipe, the folded name and the folded names of its ingredients (built on first use)
    function indexFor(lang) {
      if (!app.indexes.has(lang)) {
        app.indexes.set(lang, app.recipes.map((recipe) => ({
          label: nameOf(recipe.name, lang),
          name: fold(nameOf(recipe.name, lang)),
          ingredients: fold(recipe.ingredients.map((ingredient) => nameOf(ingredient, lang)).join(" ")),
        })));
      }
      return app.indexes.get(lang);
    }

    function currentMenu() {
      return app.menus.find((menu) => menu.id === state.menuId) ?? null;
    }

    // Recipe indexes of a menu collection, in the order of the collection
    function menuIndices(menu) {
      if (!menu) return [];
      return menu.recipes
        .map((name) => app.recipeIndexByName.get(name) ?? app.recipeIndexByLowerName.get(name.toLowerCase()))
        .filter((index) => index !== undefined);
    }

    function runSearch() {
      const scope = app.allIndices;
      if (!app.tokens.length) return scope;

      const index = indexFor(state.lang);
      const whole = app.tokens.join(" ");
      const scored = [];
      for (const i of scope) {
        const { name, ingredients } = index[i];
        const haystack = `${name} ${ingredients}`;
        if (!app.tokens.every((token) => haystack.includes(token))) continue;
        let rank = 4; // only the ingredients match
        if (name === whole) rank = 0;
        else if (name.startsWith(whole)) rank = 1;
        else if (name.includes(whole)) rank = 2;
        else if (app.tokens.every((token) => name.includes(token))) rank = 3;
        scored.push([rank, i]);
      }
      scored.sort((a, b) => a[0] - b[0] || app.collator.compare(index[a[1]].label, index[b[1]].label));
      return scored.map(([, i]) => i);
    }

    // ---- Rendering -----------------------------------------------------------------------------------------------

    function placeholder(label) {
      return h("span", { "aria-hidden": "true", text: Array.from(label)[0]?.toUpperCase() ?? "?" });
    }

    function picture(path, label, className) {
      const url = imageUrl(path);
      if (!url) return null;
      const image = h("img", { src: url, alt: "", loading: "lazy", decoding: "async", class: className });
      return image;
    }

    function ingredientChip(name) {
      const ingredient = app.ingredientByName.get(name);
      const label = nameOf(name);
      const image = ingredient ? picture(ingredient.image, label) : null;
      if (image) image.addEventListener("error", () => image.remove());
      return h("li", {
        class: ingredient ? "chip" : "chip group",
        title: ingredient ? null : text("ingredientGroup"),
      }, image, h("span", { lang: state.lang, text: label }));
    }

    function thumbOf(recipe, label) {
      const thumb = h("div", { class: "thumb" });
      const image = picture(recipe.image, label);
      if (image) {
        image.addEventListener("error", () => thumb.replaceChildren(placeholder(label)));
        thumb.append(image);
      } else {
        thumb.append(placeholder(label));
      }
      return thumb;
    }

    // A clickable row. Used in both panes; `tokens` highlights the search words, `withIngredients` adds the ingredient line.
    function recipeRow(index, { tokens = [], withIngredients = false } = {}) {
      const recipe = app.recipes[index];
      const label = indexFor(state.lang)[index].label;
      const button = h("button", {
        type: "button",
        class: "recipe",
        "data-category": recipe.category,
        "data-index": index,
        "aria-current": state.selected === index ? "true" : null,
      },
        thumbOf(recipe, label),
        h("span", {},
          h("span", { class: "title-line" },
            h("span", { class: "name", lang: state.lang }, highlighted(label, tokens)),
            h("span", { class: "badge", text: categoryLabel(recipe.category) }),
          ),
          label !== recipe.name ? h("p", { class: "english", lang: "en", text: recipe.name }) : null,
          withIngredients
            ? h("p", { class: "inline-ingredients", lang: state.lang },
                highlighted(recipe.ingredients.map((name) => nameOf(name)).join(", "), tokens))
            : null,
        ),
      );
      return h("li", {}, button);
    }

    function recipeDetail(index) {
      const recipe = app.recipes[index];
      const label = indexFor(state.lang)[index].label;
      const description = descriptionOf(recipe);
      return h("article", { class: "detail", "data-category": recipe.category },
        h("button", { type: "button", class: "back", "data-back": "", text: "← " + text("back") }),
        h("div", { class: "detail-head" },
          thumbOf(recipe, label),
          h("div", {},
            h("h3", { lang: state.lang, text: label }),
            label !== recipe.name ? h("p", { class: "english", lang: "en", text: recipe.name }) : null,
            h("span", { class: "badge", text: categoryLabel(recipe.category) }),
          ),
        ),
        description ? h("p", { class: "desc", lang: state.lang, text: description }) : null,
        recipe.ingredients.length
          ? h("section", {},
              h("h4", { text: text("ingredientsTitle") }),
              h("ul", { class: "chips" }, recipe.ingredients.map(ingredientChip)))
          : null,
      );
    }

    // Left frame: the list of matches, or the details of the selected recipe
    function renderResults() {
      if (state.selected !== null) {
        el.results.replaceChildren(recipeDetail(state.selected));
        el.results.scrollTop = 0;
        return;
      }
      el.results.replaceChildren(
        app.results.length
          ? h("ul", { class: "list" }, app.results.map((index) => recipeRow(index, { tokens: app.tokens, withIngredients: true })))
          : h("p", { class: "empty", text: text("noResults", { query: state.query.trim() }) }),
      );
    }

    // Right pane: description of the collection and its recipes
    function renderMenu() {
      const menu = currentMenu();
      el["menu-panel"].hidden = !menu;
      if (!menu) {
        el["menu-recipes"].replaceChildren(h("p", { class: "empty", text: text("noMenus") }));
        return;
      }

      const image = picture(menu.image ?? menu.images?.splash ?? menu.images?.badge, menuText(menu, "name"));
      if (image) image.addEventListener("error", () => image.remove());
      el["menu-panel"].classList.toggle("has-image", Boolean(image));
      el["menu-panel"].replaceChildren(
        ...[image,
        h("h3", { lang: state.lang, text: menuText(menu, "name") }),
        menuText(menu, "description") ? h("p", { lang: state.lang, text: menuText(menu, "description") }) : null,
        ].filter(Boolean),
      );

      const indices = menuIndices(menu);
      el["menu-recipes"].replaceChildren(
        indices.length
          ? h("ul", { class: "list" }, indices.map((index) => recipeRow(index)))
          : h("p", { class: "empty", text: text("menuEmpty") }),
      );
    }

    function renderMenuSelect() {
      el.menu.replaceChildren(
        ...app.menus.map((menu) => h("option", {
          value: menu.id,
          lang: state.lang,
          text: `${menuText(menu, "name")} (${menu.recipes.length})`,
        })),
      );
      el.menu.value = state.menuId;
    }

    // Mark the selected recipe in both lists without re-rendering them
    function markSelected() {
      for (const row of document.querySelectorAll(".recipe")) {
        if (Number(row.dataset.index) === state.selected) row.setAttribute("aria-current", "true");
        else row.removeAttribute("aria-current");
      }
    }

    function selectRecipe(index) {
      state.selected = index;
      renderResults();
      markSelected();
      // When the panes are stacked (narrow screens) the details can be off screen: bring them into view
      if (window.matchMedia("(max-width: 900px)").matches) {
        const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        el.results.scrollIntoView({ block: "nearest", behavior: calm ? "auto" : "smooth" });
      }
    }

    function renderStats() {
      const categories = new Map();
      for (const recipe of app.recipes) categories.set(recipe.category, (categories.get(recipe.category) ?? 0) + 1);
      const order = [...CATEGORY_ORDER.filter((c) => categories.has(c)), ...[...categories.keys()].filter((c) => !CATEGORY_ORDER.includes(c))];

      el["stat-ingredients"].textContent = app.missing.includes("ingredients.json") ? "–" : formatNumber(app.ingredients.length);
      el["stat-recipes"].textContent = formatNumber(app.recipes.length);
      el["stat-menus"].textContent = app.missing.includes("menu-collections.json") ? "–" : formatNumber(app.menus.length);

      el.mix.setAttribute("aria-label", order.map((c) => `${categoryLabel(c)} ${categories.get(c)}`).join(", "));
      el.mix.replaceChildren(...order.map((c) => h("span", { "data-category": c, style: `flex: ${categories.get(c)} 1 0` })));
      el.legend.replaceChildren(...order.map((c) => h("li", { "data-category": c },
        h("i", { "aria-hidden": "true" }), categoryLabel(c), h("b", { text: formatNumber(categories.get(c)) }),
      )));
    }

    function applyStaticText() {
      document.documentElement.lang = uiLanguage();
      for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = text(node.dataset.i18n);
      el.search.placeholder = text("searchPlaceholder");
    }

    // Re-run the search (left pane). A new search always goes back to the list of matches.
    function update() {
      state.selected = null;
      app.tokens = tokensOf(state.query);
      app.results = runSearch();
      renderResults();
    }

    // One language for the interface and the search
    function changeLanguage(code) {
      state.lang = code;
      app.collator = new Intl.Collator(code);
      el.language.value = code;
      try { localStorage.setItem(STORAGE_KEY, code); } catch { /* storage can be unavailable */ }
      applyStaticText();
      if (!app.ready) return;
      renderStats();
      renderMenuSelect();
      app.tokens = tokensOf(state.query);
      app.results = runSearch();
      renderResults();
      renderMenu();
    }

    // ---- Start ---------------------------------------------------------------------------------------------------

    async function start() {
      el.language.replaceChildren(...LANGUAGES.map((language) =>
        h("option", { value: language.code, lang: language.code, text: language.label })));
      el.language.value = state.lang;
      app.collator = new Intl.Collator(state.lang);
      applyStaticText();

      el.language.addEventListener("change", () => changeLanguage(el.language.value));
      el.search.addEventListener("input", () => { state.query = el.search.value; update(); });
      el.menu.addEventListener("change", () => { state.menuId = el.menu.value; renderMenu(); });
      // One handler per pane (the rows are re-created on every render)
      for (const pane of [el.results, el["menu-recipes"]]) {
        pane.addEventListener("click", (event) => {
          if (event.target.closest("[data-back]")) {
            state.selected = null;
            renderResults();
            markSelected();
            return;
          }
          const row = event.target.closest(".recipe");
          if (row) selectRecipe(Number(row.dataset.index));
        });
      }

      try {
        await loadData();
      } catch (error) {
        el.results.replaceChildren(h("p", {
          class: "empty",
          role: "alert",
          text: text("loadError", { path: `${DATA_DIR}recipes.json` }),
        }));
        console.error(error);
        return;
      }

      app.ready = true;
      state.menuId = app.menus[0]?.id ?? "";
      renderStats();
      renderMenuSelect();
      update();
      renderMenu();
      requestAnimationFrame(() => requestAnimationFrame(() => el.mix.classList.add("is-in")));
    }

    start();