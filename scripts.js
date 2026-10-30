"use strict";

// =================================================================================================================
// Configuration
// =================================================================================================================

// "ouput" matches the project's folder name
const DATA_DIRECTORY = "data/ouput/";
// Image paths in the JSON files are relative to the parent of the images folder, which is data/
const IMAGE_BASE_PATH = "data/";
const LANGUAGE_STORAGE_KEY = "cozy-game-kiwi:language";
// Used when neither a saved choice nor the browser language matches a supported language
const DEFAULT_LANGUAGE = "vi";
// Used for interface texts that are missing in the selected language
const FALLBACK_INTERFACE_LANGUAGE = "en";
const CATEGORY_ORDER = ["normal", "dark_cuisine", "messy"];
const STACKED_LAYOUT_MEDIA_QUERY = "(max-width: 900px)";
const REDUCED_MOTION_MEDIA_QUERY = "(prefers-reduced-motion: reduce)";

// Languages and interface texts live in translations.i18n (JSON). They are loaded at start-up by loadTranslations():
//   { "<code>": { "label": "Name shown in the language menu", "ui": { ...interface texts... } }, ... }
// The order of the file is the order of the language menu. To add a language, add one block to that file
// (code = the one used in data/ouput/translations.json). Texts missing in a language fall back to English.
const TRANSLATIONS_FILE = "translations.i18n";

// How well a recipe matches the search words (a lower rank is listed first)
const MatchRank = {
    EXACT_NAME: 0,
    NAME_STARTS_WITH_QUERY: 1,
    NAME_CONTAINS_QUERY: 2,
    NAME_CONTAINS_EVERY_WORD: 3,
    INGREDIENTS_ONLY: 4,
};

// =================================================================================================================
// State and page elements
// =================================================================================================================

let supportedLanguages = []; // [{ code, label }] in the order of the language menu
let interfaceTexts = {}; // { "<language code>": { ...interface texts... } }

// Everything that changes while the person uses the page
const state = {
    language: DEFAULT_LANGUAGE,
    collectionId: "",
    category: "",
    ingredientGroupName: "",
    activeTab: "collections",
    searchQuery: "",
    searchTokens: [],
    searchResultIndices: [],
    selectedRecipeIndex: null,
    collator: new Intl.Collator("en"),
    isReady: false,
};

// Everything loaded from the data files, plus lookups built from it
const data = {
    recipes: [],
    ingredients: [],
    collections: [],
    translations: null,
    missingFiles: [],
    ingredientsByName: new Map(),
    ingredientGroups: [],
    recipeIndexByName: new Map(),
    recipeIndexByLowerCaseName: new Map(),
    recipeIndicesByCategory: new Map(),
    categoryOrder: [],
    allRecipeIndices: [],
    searchIndexByLanguage: new Map(),
};

const getElementById = (id) => document.getElementById(id);

const elements = {
    languageSelect: getElementById("language"),
    searchInput: getElementById("search"),
    searchResults: getElementById("search-results"),

    collectionSelect: getElementById("collection"),
    collectionPanel: getElementById("collection-panel"),
    collectionRecipes: getElementById("collection-recipes"),

    categorySelect: getElementById("category"),
    categoryPanel: getElementById("category-panel"),
    categoryRecipes: getElementById("category-recipes"),

    groupSelect: getElementById("group"),
    groupPanel: getElementById("group-panel"),
    groupMembers: getElementById("group-members"),

    ingredientCount: getElementById("stat-ingredients"),
    ingredientGroupCount: getElementById("stat-ingredient-groups"),
    collectionCount: getElementById("stat-collections"),
    recipeCount: getElementById("stat-recipes"),
    categoryMix: getElementById("category-mix"),
    categoryLegend: getElementById("category-legend"),
};

// The tabs of the right pane. Only the visible tab is drawn: a category can hold hundreds of rows.
const tabs = {
    collections: {
        button: getElementById("tab-collections"),
        panel: getElementById("panel-collections"),
        render: renderCollectionTab,
    },
    categories: {
        button: getElementById("tab-categories"),
        panel: getElementById("panel-categories"),
        render: renderCategoryTab,
    },
    groups: {
        button: getElementById("tab-groups"),
        panel: getElementById("panel-groups"),
        render: renderIngredientGroupTab,
    },
};
const tabNames = Object.keys(tabs);

// =================================================================================================================
// Small helpers
// =================================================================================================================

function createElement(tagName, attributes = {}, ...children) {
    const node = document.createElement(tagName);
    for (const [name, value] of Object.entries(attributes)) {
        if (value === undefined || value === null || value === false) continue;
        if (name === "text") node.textContent = value;
        else node.setAttribute(name, value === true ? "" : value);
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
    return node;
}

const formatNumber = (number) => new Intl.NumberFormat(state.language).format(number);

const isIngredientGroup = (ingredient) => ingredient.is_tag === true;

// ---- Language and interface texts ----------------------------------------------------------------------------

const isSupportedLanguage = (code) => supportedLanguages.some((language) => language.code === code);

function readSavedLanguage() {
    try {
        return localStorage.getItem(LANGUAGE_STORAGE_KEY);
    } catch {
        return null; // storage can be unavailable
    }
}

function saveLanguage(code) {
    try {
        localStorage.setItem(LANGUAGE_STORAGE_KEY, code);
    } catch {
        // storage can be unavailable
    }
}

// The saved language, else the first browser language we support, else the default one
function detectInitialLanguage() {
    const savedLanguage = readSavedLanguage();
    if (savedLanguage && isSupportedLanguage(savedLanguage)) return savedLanguage;

    for (const languageTag of navigator.languages || [navigator.language]) {
        const code = String(languageTag).toLowerCase().split("-")[0];
        if (isSupportedLanguage(code)) return code;
    }
    return isSupportedLanguage(DEFAULT_LANGUAGE) ? DEFAULT_LANGUAGE : (supportedLanguages[0]?.code ?? "en");
}

const getInterfaceLanguage = () => (interfaceTexts[state.language] ? state.language : FALLBACK_INTERFACE_LANGUAGE);

function translate(key, variables = {}) {
    const template =
        interfaceTexts[getInterfaceLanguage()]?.[key] ?? interfaceTexts[FALLBACK_INTERFACE_LANGUAGE]?.[key] ?? key;
    return template.replace(/\{(\w+)\}/g, (_, variableName) => String(variables[variableName] ?? `{${variableName}}`));
}

function translateCategory(category) {
    return (
        interfaceTexts[getInterfaceLanguage()]?.categories?.[category] ??
        interfaceTexts[FALLBACK_INTERFACE_LANGUAGE]?.categories?.[category] ??
        category
    );
}

// ---- Names and descriptions in the selected language ---------------------------------------------------------

function getLocalizedName(name, language = state.language) {
    return data.translations?.[name]?.name?.[language] || name;
}

// Works for recipes and ingredients: both have a name and an optional description
function getLocalizedDescription(entry) {
    return data.translations?.[entry.name]?.description?.[state.language] || entry.description || "";
}

function getCollectionText(collection, field) {
    return collection.translations?.[field]?.[state.language] || collection[field] || "";
}

// ---- Search text normalization -------------------------------------------------------------------------------

// Search is case-insensitive and ignores accents, so "trung" finds "Trứng"
function normalizeText(value) {
    return value
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/đ/g, "d");
}

// Like normalizeText(), but also returns, for every normalized character, where it came from in the original text
function normalizeTextWithPositions(value) {
    let normalizedText = "";
    const originalPositions = [];
    let originalPosition = 0;
    for (const character of value) {
        const normalizedCharacter = normalizeText(character);
        for (let offset = 0; offset < normalizedCharacter.length; offset += 1) {
            originalPositions.push(originalPosition);
        }
        normalizedText += normalizedCharacter;
        originalPosition += character.length;
    }
    return { normalizedText, originalPositions };
}

function splitIntoSearchTokens(query) {
    return normalizeText(query).split(/\s+/).filter(Boolean);
}

// Ranges [start, end) of the original text where one of the tokens matches
function findMatchRanges(originalText, tokens) {
    const { normalizedText, originalPositions } = normalizeTextWithPositions(originalText);
    const ranges = [];
    for (const token of tokens) {
        let matchStart = normalizedText.indexOf(token);
        while (matchStart !== -1) {
            const lastCharacterStart = originalPositions[matchStart + token.length - 1];
            const lastCharacterLength = String.fromCodePoint(originalText.codePointAt(lastCharacterStart)).length;
            ranges.push({ start: originalPositions[matchStart], end: lastCharacterStart + lastCharacterLength });
            matchStart = normalizedText.indexOf(token, matchStart + token.length);
        }
    }
    return ranges;
}

function mergeOverlappingRanges(ranges) {
    const sortedRanges = [...ranges].sort((first, second) => first.start - second.start);
    const mergedRanges = [{ ...sortedRanges[0] }];
    for (const range of sortedRanges.slice(1)) {
        const previousRange = mergedRanges[mergedRanges.length - 1];
        if (range.start <= previousRange.end) previousRange.end = Math.max(previousRange.end, range.end);
        else mergedRanges.push({ ...range });
    }
    return mergedRanges;
}

// The original text split into plain strings and <mark> elements around the matched tokens
function highlightMatches(originalText, tokens) {
    const ranges = tokens.length ? findMatchRanges(originalText, tokens) : [];
    if (!ranges.length) return [originalText];

    const nodes = [];
    let cursor = 0;
    for (const { start, end } of mergeOverlappingRanges(ranges)) {
        if (start > cursor) nodes.push(originalText.slice(cursor, start));
        nodes.push(createElement("mark", { text: originalText.slice(start, end) }));
        cursor = end;
    }
    if (cursor < originalText.length) nodes.push(originalText.slice(cursor));
    return nodes;
}

// =================================================================================================================
// Loading
// =================================================================================================================

async function loadTranslations() {
    const response = await fetch(TRANSLATIONS_FILE);
    if (!response.ok) throw new Error(`${TRANSLATIONS_FILE}: HTTP ${response.status}`);
    const translationsByLanguage = await response.json();

    supportedLanguages = Object.entries(translationsByLanguage).map(([code, entry]) => ({
        code,
        label: entry.label ?? code,
    }));
    interfaceTexts = Object.fromEntries(
        Object.entries(translationsByLanguage).map(([code, entry]) => [code, entry.ui ?? {}]),
    );
}

async function fetchDataFile(fileName) {
    const response = await fetch(DATA_DIRECTORY + fileName);
    if (!response.ok) throw new Error(`${DATA_DIRECTORY}${fileName}: HTTP ${response.status}`);
    return response.json();
}

async function fetchOptionalDataFile(fileName, valueWhenMissing) {
    try {
        return await fetchDataFile(fileName);
    } catch {
        data.missingFiles.push(fileName);
        return valueWhenMissing;
    }
}

// Lookups that are built once, right after loading
function buildLookups() {
    data.ingredientsByName = new Map(data.ingredients.map((ingredient) => [ingredient.name, ingredient]));
    data.ingredientGroups = data.ingredients.filter(isIngredientGroup);

    data.recipes.forEach((recipe, recipeIndex) => {
        data.recipeIndexByName.set(recipe.name, recipeIndex);
        data.recipeIndexByLowerCaseName.set(recipe.name.toLowerCase(), recipeIndex);
        if (!data.recipeIndicesByCategory.has(recipe.category)) data.recipeIndicesByCategory.set(recipe.category, []);
        data.recipeIndicesByCategory.get(recipe.category).push(recipeIndex);
    });
    data.allRecipeIndices = data.recipes.map((_, recipeIndex) => recipeIndex);

    const knownCategories = CATEGORY_ORDER.filter((category) => data.recipeIndicesByCategory.has(category));
    const otherCategories = [...data.recipeIndicesByCategory.keys()].filter(
        (category) => !CATEGORY_ORDER.includes(category),
    );
    data.categoryOrder = [...knownCategories, ...otherCategories];
}

async function loadData() {
    data.recipes = await fetchDataFile("recipes.json");
    [data.ingredients, data.collections, data.translations] = await Promise.all([
        fetchOptionalDataFile("ingredients.json", []),
        fetchOptionalDataFile("collections.json", []),
        fetchOptionalDataFile("translations.json", null),
    ]);
    data.collections.sort((first, second) => (first.sort_order ?? 0) - (second.sort_order ?? 0));
    buildLookups();
}

// =================================================================================================================
// Search
// =================================================================================================================

// Per language: for every recipe, its label and the normalized name and ingredient names (built on first use)
function getSearchIndex(language) {
    if (!data.searchIndexByLanguage.has(language)) {
        data.searchIndexByLanguage.set(
            language,
            data.recipes.map((recipe) => {
                const label = getLocalizedName(recipe.name, language);
                const ingredientNames = recipe.ingredients.map((name) => getLocalizedName(name, language));
                return {
                    label,
                    normalizedName: normalizeText(label),
                    normalizedIngredients: normalizeText(ingredientNames.join(" ")),
                };
            }),
        );
    }
    return data.searchIndexByLanguage.get(language);
}

const getRecipeLabel = (recipeIndex) => getSearchIndex(state.language)[recipeIndex].label;

function rankNameMatch(normalizedName, fullQuery) {
    if (normalizedName === fullQuery) return MatchRank.EXACT_NAME;
    if (normalizedName.startsWith(fullQuery)) return MatchRank.NAME_STARTS_WITH_QUERY;
    if (normalizedName.includes(fullQuery)) return MatchRank.NAME_CONTAINS_QUERY;
    if (state.searchTokens.every((token) => normalizedName.includes(token))) {
        return MatchRank.NAME_CONTAINS_EVERY_WORD;
    }
    return MatchRank.INGREDIENTS_ONLY;
}

function sortRecipeIndicesByName(recipeIndices) {
    return [...recipeIndices].sort((first, second) =>
        state.collator.compare(getRecipeLabel(first), getRecipeLabel(second)),
    );
}

// Recipe indexes that contain every search word in their name or ingredients, best matches first
function searchRecipes() {
    if (!state.searchTokens.length) return data.allRecipeIndices;

    const searchIndex = getSearchIndex(state.language);
    const fullQuery = state.searchTokens.join(" ");
    const matches = [];
    for (const recipeIndex of data.allRecipeIndices) {
        const { normalizedName, normalizedIngredients } = searchIndex[recipeIndex];
        const searchableText = `${normalizedName} ${normalizedIngredients}`;
        if (!state.searchTokens.every((token) => searchableText.includes(token))) continue;
        matches.push({ recipeIndex, rank: rankNameMatch(normalizedName, fullQuery) });
    }

    matches.sort(
        (first, second) =>
            first.rank - second.rank ||
            state.collator.compare(getRecipeLabel(first.recipeIndex), getRecipeLabel(second.recipeIndex)),
    );
    return matches.map((match) => match.recipeIndex);
}

// =================================================================================================================
// Rendering: building blocks
// =================================================================================================================

function createPlaceholder(label) {
    return createElement("span", {
        "aria-hidden": "true",
        text: Array.from(label)[0]?.toUpperCase() ?? "?",
    });
}

function createImage(imagePath, { removeOnError = false } = {}) {
    if (!imagePath) return null;
    const image = createElement("img", {
        src: IMAGE_BASE_PATH + imagePath,
        alt: "",
        loading: "lazy",
        decoding: "async",
    });
    if (removeOnError) image.addEventListener("error", () => image.remove());
    return image;
}

// A square picture that falls back to the first letter of the label when there is no picture or it fails to load
function createThumbnail(imagePath, label) {
    const thumbnail = createElement("div", { class: "thumb" });
    const image = createImage(imagePath);
    if (image) image.addEventListener("error", () => thumbnail.replaceChildren(createPlaceholder(label)));
    thumbnail.append(image ?? createPlaceholder(label));
    return thumbnail;
}

const createEmptyMessage = (message) => createElement("p", { class: "empty", text: message });

function createList(items) {
    return createElement("ul", { class: "list" }, items);
}

// Fills a <select>; each option is { value, label }
function fillSelect(selectElement, options, selectedValue) {
    selectElement.replaceChildren(
        ...options.map(({ value, label }) => createElement("option", { value, lang: state.language, text: label })),
    );
    selectElement.value = selectedValue;
}

// The header box above a recipe list: a title, plus a picture and a description when there are any.
// (replaceChildren() would turn a missing picture into the text "null", so only real elements are passed.)
function showInfoPanel(panel, { imagePath = null, title, description = "", descriptionLanguage = null }) {
    const image = createImage(imagePath, { removeOnError: true });
    const titleElement = createElement("h3", { lang: state.language, text: title });
    const descriptionElement = description
        ? createElement("p", { lang: descriptionLanguage, text: description })
        : null;

    panel.hidden = false;
    panel.classList.toggle("has-image", image !== null);
    panel.replaceChildren(...[image, titleElement, descriptionElement].filter(Boolean));
}

// =================================================================================================================
// Rendering: recipes (left pane and recipe lists)
// =================================================================================================================

// One ingredient of a recipe. A tag (Meat, Veggie, ...) means "any ingredient that has this tag": it is listed in
// ingredients.json with "is_tag": true and its own icon, so it is drawn like an ingredient, with a dashed border.
function createIngredientChip(ingredientName, tokens = []) {
    const ingredient = data.ingredientsByName.get(ingredientName);
    const isGroup = ingredient ? isIngredientGroup(ingredient) : false;
    return createElement(
        "li",
        {
            class: isGroup ? "chip is-group" : "chip",
            title: isGroup ? translate("ingredientGroup") : null,
        },
        ingredient ? createImage(ingredient.image, { removeOnError: true }) : null,
        createElement("span", { lang: state.language }, highlightMatches(getLocalizedName(ingredientName), tokens)),
    );
}

function createIngredientChips(recipe, tokens) {
    return createElement(
        "ul",
        { class: "chips" },
        recipe.ingredients.map((name) => createIngredientChip(name, tokens)),
    );
}

// A clickable row. Used in all lists; `tokens` highlights the search words,
// `showIngredients` adds the ingredient chips.
function createRecipeRow(recipeIndex, { tokens = [], showIngredients = false } = {}) {
    const recipe = data.recipes[recipeIndex];
    const label = getRecipeLabel(recipeIndex);
    const button = createElement(
        "button",
        {
            type: "button",
            class: "recipe",
            "data-category": recipe.category,
            "data-recipe-index": recipeIndex,
            "aria-current": state.selectedRecipeIndex === recipeIndex ? "true" : null,
        },
        createThumbnail(recipe.image, label),
        createElement(
            "span",
            {},
            createElement(
                "span",
                { class: "title-line" },
                createElement("span", { class: "name", lang: state.language }, highlightMatches(label, tokens)),
                createElement("span", { class: "badge", text: translateCategory(recipe.category) }),
            ),
            showIngredients ? createIngredientChips(recipe, tokens) : null,
        ),
    );
    return createElement("li", {}, button);
}

const createRecipeList = (recipeIndices) =>
    createList(recipeIndices.map((recipeIndex) => createRecipeRow(recipeIndex, { showIngredients: true })));

function createRecipeDetail(recipeIndex) {
    const recipe = data.recipes[recipeIndex];
    const label = getRecipeLabel(recipeIndex);
    const description = getLocalizedDescription(recipe);
    return createElement(
        "article",
        { class: "detail", "data-category": recipe.category },
        createElement("button", {
            type: "button",
            class: "back",
            "data-back": "",
            text: "← " + translate("back"),
        }),
        createElement(
            "div",
            { class: "detail-head" },
            createThumbnail(recipe.image, label),
            createElement(
                "div",
                {},
                createElement("h3", { lang: state.language, text: label }),
                createElement("span", { class: "badge", text: translateCategory(recipe.category) }),
            ),
        ),
        description ? createElement("p", { class: "description", lang: state.language, text: description }) : null,
        recipe.ingredients.length
            ? createElement(
                  "section",
                  {},
                  createElement("h4", { text: translate("ingredientsTitle") }),
                  createIngredientChips(recipe, []),
              )
            : null,
    );
}

// Left frame: the list of matches, or the details of the selected recipe
function renderSearchResults() {
    const frame = elements.searchResults;
    if (state.selectedRecipeIndex !== null) {
        frame.replaceChildren(createRecipeDetail(state.selectedRecipeIndex));
        frame.scrollTop = 0;
        return;
    }

    if (!state.searchResultIndices.length) {
        frame.replaceChildren(createEmptyMessage(translate("noResults", { query: state.searchQuery.trim() })));
        return;
    }
    frame.replaceChildren(
        createList(
            state.searchResultIndices.map((recipeIndex) =>
                createRecipeRow(recipeIndex, { tokens: state.searchTokens, showIngredients: true }),
            ),
        ),
    );
}

// Mark the selected recipe in every list without re-rendering them
function markSelectedRecipe() {
    for (const row of document.querySelectorAll(".recipe")) {
        if (Number(row.dataset.recipeIndex) === state.selectedRecipeIndex) row.setAttribute("aria-current", "true");
        else row.removeAttribute("aria-current");
    }
}

function selectRecipe(recipeIndex) {
    state.selectedRecipeIndex = recipeIndex;
    renderSearchResults();
    markSelectedRecipe();

    // When the panes are stacked (narrow screens) the details can be off screen: bring them into view
    if (window.matchMedia(STACKED_LAYOUT_MEDIA_QUERY).matches) {
        const prefersReducedMotion = window.matchMedia(REDUCED_MOTION_MEDIA_QUERY).matches;
        elements.searchResults.scrollIntoView({
            block: "nearest",
            behavior: prefersReducedMotion ? "auto" : "smooth",
        });
    }
}

function backToSearchResults() {
    state.selectedRecipeIndex = null;
    renderSearchResults();
    markSelectedRecipe();
}

// Run the search again and redraw the left frame (a language change keeps the recipe being viewed)
function refreshSearchResults() {
    state.searchTokens = splitIntoSearchTokens(state.searchQuery);
    state.searchResultIndices = searchRecipes();
    renderSearchResults();
}

// A new search always goes back to the list of matches
function startNewSearch() {
    state.selectedRecipeIndex = null;
    refreshSearchResults();
}

// =================================================================================================================
// Rendering: right pane (collections, categories, ingredient groups)
// =================================================================================================================

// ---- Collections ---------------------------------------------------------------------------------------------

const findSelectedCollection = () =>
    data.collections.find((collection) => collection.id === state.collectionId) ?? null;

// Recipe indexes of a collection, in the order of the collection
function getCollectionRecipeIndices(collection) {
    return collection.recipes
        .map(
            (recipeName) =>
                data.recipeIndexByName.get(recipeName) ?? data.recipeIndexByLowerCaseName.get(recipeName.toLowerCase()),
        )
        .filter((recipeIndex) => recipeIndex !== undefined);
}

function renderCollectionSelect() {
    fillSelect(
        elements.collectionSelect,
        data.collections.map((collection) => ({
            value: collection.id,
            label: `${getCollectionText(collection, "name")} (${collection.recipes.length})`,
        })),
        state.collectionId,
    );
}

function renderCollectionTab() {
    const collection = findSelectedCollection();
    elements.collectionPanel.hidden = !collection;
    if (!collection) {
        elements.collectionRecipes.replaceChildren(createEmptyMessage(translate("noMenus")));
        return;
    }

    showInfoPanel(elements.collectionPanel, {
        imagePath: collection.image ?? collection.images?.splash ?? collection.images?.badge,
        title: getCollectionText(collection, "name"),
        description: getCollectionText(collection, "description"),
        descriptionLanguage: state.language,
    });

    const recipeIndices = getCollectionRecipeIndices(collection);
    elements.collectionRecipes.replaceChildren(
        recipeIndices.length ? createRecipeList(recipeIndices) : createEmptyMessage(translate("menuEmpty")),
    );
}

// ---- Categories ----------------------------------------------------------------------------------------------

const countRecipesInCategory = (category) => data.recipeIndicesByCategory.get(category).length;

function renderCategorySelect() {
    fillSelect(
        elements.categorySelect,
        data.categoryOrder.map((category) => ({
            value: category,
            label: `${translateCategory(category)} (${formatNumber(countRecipesInCategory(category))})`,
        })),
        state.category,
    );
}

// The recipes of one category, sorted by name in the current language
function renderCategoryTab() {
    const recipeIndices = data.recipeIndicesByCategory.get(state.category);
    elements.categoryPanel.hidden = !recipeIndices;
    if (!recipeIndices) {
        elements.categoryRecipes.replaceChildren(createEmptyMessage(translate("noCategories")));
        return;
    }

    showInfoPanel(elements.categoryPanel, {
        title: translateCategory(state.category),
        description: translate("categoryRecipes", { n: formatNumber(recipeIndices.length) }),
    });
    elements.categoryRecipes.replaceChildren(createRecipeList(sortRecipeIndicesByName(recipeIndices)));
}

// ---- Ingredient groups ---------------------------------------------------------------------------------------

// The ingredients listed in the "members" field of a group (names that are not in ingredients.json are skipped)
function getGroupMembers(group) {
    return (group.members ?? [])
        .map((memberName) => data.ingredientsByName.get(memberName))
        .filter((ingredient) => ingredient !== undefined);
}

const sortIngredientsByName = (ingredients) =>
    [...ingredients].sort((first, second) =>
        state.collator.compare(getLocalizedName(first.name), getLocalizedName(second.name)),
    );

function renderIngredientGroupSelect() {
    const sortedGroups = sortIngredientsByName(data.ingredientGroups);
    if (!sortedGroups.some((group) => group.name === state.ingredientGroupName)) {
        state.ingredientGroupName = sortedGroups[0]?.name ?? "";
    }
    fillSelect(
        elements.groupSelect,
        sortedGroups.map((group) => ({
            value: group.name,
            label: `${getLocalizedName(group.name)} (${formatNumber(getGroupMembers(group).length)})`,
        })),
        state.ingredientGroupName,
    );
}

function createGroupMemberRow(ingredient) {
    const label = getLocalizedName(ingredient.name);
    const description = getLocalizedDescription(ingredient);
    return createElement(
        "li",
        { class: "member" },
        createThumbnail(ingredient.image, label),
        createElement(
            "span",
            {},
            createElement("span", { class: "name", lang: state.language, text: label }),
            description ? createElement("p", { class: "member-description", text: description }) : null,
        ),
    );
}

// The ingredients that belong to one group (from the "members" field of the group in ingredients.json)
function renderIngredientGroupTab() {
    const group = data.ingredientGroups.find((candidate) => candidate.name === state.ingredientGroupName);
    elements.groupPanel.hidden = !group;
    if (!group) {
        elements.groupMembers.replaceChildren(createEmptyMessage(translate("noGroups")));
        return;
    }

    const members = getGroupMembers(group);
    showInfoPanel(elements.groupPanel, {
        imagePath: group.image,
        title: getLocalizedName(group.name),
        description: translate("groupMembers", { n: formatNumber(members.length) }),
    });
    elements.groupMembers.replaceChildren(
        members.length
            ? createList(sortIngredientsByName(members).map(createGroupMemberRow))
            : createEmptyMessage(translate("groupEmpty")),
    );
}

// ---- Tabs ----------------------------------------------------------------------------------------------------

const renderActiveTab = () => tabs[state.activeTab].render();

function activateTab(activeTabName, { shouldFocus = false } = {}) {
    state.activeTab = activeTabName;
    for (const [tabName, tab] of Object.entries(tabs)) {
        const isActive = tabName === activeTabName;
        tab.button.setAttribute("aria-selected", String(isActive));
        tab.button.tabIndex = isActive ? 0 : -1;
        tab.panel.hidden = !isActive;
        if (shouldFocus && isActive) tab.button.focus();
    }
    if (state.isReady) renderActiveTab();
}

// Left and right arrows move to the previous and next tab (wrapping around)
function activateNeighborTab(direction) {
    const nextIndex = (tabNames.indexOf(state.activeTab) + direction + tabNames.length) % tabNames.length;
    activateTab(tabNames[nextIndex], { shouldFocus: true });
}

// =================================================================================================================
// Rendering: totals and static texts
// =================================================================================================================

function renderStatistics() {
    const hasIngredientsFile = !data.missingFiles.includes("ingredients.json");
    const hasCollectionsFile = !data.missingFiles.includes("collections.json");
    const formatCount = (count, isAvailable = true) => (isAvailable ? formatNumber(count) : "–");

    // Groups are listed with the ingredients but they are not ingredients themselves, so they are not counted
    const plainIngredientCount = data.ingredients.filter((ingredient) => !isIngredientGroup(ingredient)).length;
    elements.ingredientCount.textContent = formatCount(plainIngredientCount, hasIngredientsFile);
    elements.ingredientGroupCount.textContent = formatCount(data.ingredientGroups.length, hasIngredientsFile);
    elements.collectionCount.textContent = formatCount(data.collections.length, hasCollectionsFile);
    elements.recipeCount.textContent = formatCount(data.recipes.length);

    elements.categoryMix.setAttribute(
        "aria-label",
        data.categoryOrder
            .map((category) => `${translateCategory(category)} ${countRecipesInCategory(category)}`)
            .join(", "),
    );
    elements.categoryMix.replaceChildren(
        ...data.categoryOrder.map((category) =>
            createElement("span", {
                "data-category": category,
                style: `flex: ${countRecipesInCategory(category)} 1 0`,
            }),
        ),
    );
    elements.categoryLegend.replaceChildren(
        ...data.categoryOrder.map((category) =>
            createElement(
                "li",
                { "data-category": category },
                createElement("i", { "aria-hidden": "true" }),
                translateCategory(category),
                createElement("b", { text: formatNumber(countRecipesInCategory(category)) }),
            ),
        ),
    );
}

function applyStaticTexts() {
    document.documentElement.lang = getInterfaceLanguage();
    for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = translate(node.dataset.i18n);
    elements.searchInput.placeholder = translate("searchPlaceholder");
}

function renderAllSelects() {
    renderCollectionSelect();
    renderCategorySelect();
    renderIngredientGroupSelect();
}

// One language for the interface and the search
function changeLanguage(languageCode) {
    state.language = languageCode;
    state.collator = new Intl.Collator(languageCode);
    elements.languageSelect.value = languageCode;
    saveLanguage(languageCode);
    applyStaticTexts();
    if (!state.isReady) return;

    renderStatistics();
    renderAllSelects();
    refreshSearchResults();
    renderActiveTab();
}

// =================================================================================================================
// Start
// =================================================================================================================

function showFatalError(message) {
    elements.searchResults.replaceChildren(createElement("p", { class: "empty", role: "alert", text: message }));
}

function populateLanguageSelect() {
    elements.languageSelect.replaceChildren(
        ...supportedLanguages.map((language) =>
            createElement("option", { value: language.code, lang: language.code, text: language.label }),
        ),
    );
    elements.languageSelect.value = state.language;
}

function registerEventListeners() {
    elements.languageSelect.addEventListener("change", () => changeLanguage(elements.languageSelect.value));

    elements.searchInput.addEventListener("input", () => {
        state.searchQuery = elements.searchInput.value;
        startNewSearch();
    });

    elements.collectionSelect.addEventListener("change", () => {
        state.collectionId = elements.collectionSelect.value;
        renderCollectionTab();
    });
    elements.categorySelect.addEventListener("change", () => {
        state.category = elements.categorySelect.value;
        renderCategoryTab();
    });
    elements.groupSelect.addEventListener("change", () => {
        state.ingredientGroupName = elements.groupSelect.value;
        renderIngredientGroupTab();
    });

    for (const [tabName, tab] of Object.entries(tabs)) {
        tab.button.addEventListener("click", () => activateTab(tabName));
        tab.button.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            activateNeighborTab(event.key === "ArrowRight" ? 1 : -1);
        });
    }

    // One handler per list (the rows are re-created on every render)
    for (const recipeList of [elements.searchResults, elements.collectionRecipes, elements.categoryRecipes]) {
        recipeList.addEventListener("click", (event) => {
            if (event.target.closest("[data-back]")) {
                backToSearchResults();
                return;
            }
            const row = event.target.closest(".recipe");
            if (row) selectRecipe(Number(row.dataset.recipeIndex));
        });
    }
}

async function start() {
    try {
        await loadTranslations();
    } catch (error) {
        console.error(error);
        showFatalError(
            `Couldn't load ${TRANSLATIONS_FILE}. Open this page through a web server ` +
                "(for example, run python3 -m http.server in the project folder) and check that the file exists.",
        );
        return;
    }

    state.language = detectInitialLanguage();
    state.collator = new Intl.Collator(state.language);
    populateLanguageSelect();
    applyStaticTexts();
    registerEventListeners();

    try {
        await loadData();
    } catch (error) {
        console.error(error);
        showFatalError(translate("loadError", { path: `${DATA_DIRECTORY}recipes.json` }));
        return;
    }

    state.isReady = true;
    state.collectionId = data.collections[0]?.id ?? "";
    state.category = data.categoryOrder[0] ?? "";
    renderStatistics();
    renderAllSelects();
    startNewSearch();
    renderActiveTab();

    // Two frames later, so the browser has drawn the empty bar before it starts to fill
    requestAnimationFrame(() => requestAnimationFrame(() => elements.categoryMix.classList.add("is-in")));
}

start();
