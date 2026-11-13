(() => {
    "use strict";

    const EMAIL_RE = /^[a-z0-9._%+\-]+@(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,}$/;
    const PROGRESS_STORAGE_KEY = "iq_quiz_progress_v1";
    const THEME_STORAGE_KEY = "iq_theme";
    const LANG_STORAGE_KEY = "iq_lang";

    const state = {
        screen: "landing",
        lang: "ru",
        sessionStatus: "none",
        paymentStatus: "unpaid",
        hasEmail: false,
        quizActive: false,
        returnScreen: null,
        questions: [ ],
        totalQuestions: 15,
        answered: { },
        draftOption: null,
        currentIndex: 0,
        questionStartedAt: 0,
        questionElapsedMs: 0,
        quizElapsedMs: 0,
        timerStartedAt: 0,
        timerId: null,
        plans: [ ],
        selectedPlanId: "trial_sub",
        result: null,
        reviewFilter: "all",
        demoChoice: null,
        activeDomainTab: "spatial",
        confirmAction: null
    };

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function t(key, vars = null) {
        const dict = window.IQ_I18N || { };
        const langDict = dict[state.lang] || dict.ru || { };
        const fallbackDict = dict.ru || { };
        let str = langDict[key];
        if (str === undefined) str = fallbackDict[key];
        if (str === undefined) return key;
        if (vars) {
            for (const [k, v] of Object.entries(vars)) {
                str = str.replaceAll(`{${k}}`, String(v));
            }
        }
        return str;
    }

    function getResolvedLang() {
        const current = document.documentElement.dataset.lang;
        if (current === "ru" || current === "en") return current;
        try {
            const saved = localStorage.getItem(LANG_STORAGE_KEY);
            if (saved === "ru" || saved === "en") return saved;
        } catch { /* игнор */ }
        const sysLang = (navigator.language || (navigator.languages && navigator.languages[0]) || "en").toLowerCase();
        return sysLang.startsWith("ru") ? "ru" : "en";
    }

    function applyStaticTranslations() {
        document.title = t("title_app");
        document.querySelectorAll("[data-t]").forEach((el) => {
            el.textContent = t(el.dataset.t);
        });
        document.querySelectorAll("[data-t-placeholder]").forEach((el) => {
            el.setAttribute("placeholder", t(el.dataset.tPlaceholder));
        });
        document.querySelectorAll("[data-t-aria]").forEach((el) => {
            el.setAttribute("aria-label", t(el.dataset.tAria));
        });
        document.querySelectorAll("[data-t-title]").forEach((el) => {
            el.setAttribute("title", t(el.dataset.tTitle));
        });
    }

    function applyLanguage(lang, persist = true) {
        const nextLang = lang === "en" ? "en" : "ru";
        state.lang = nextLang;
        document.documentElement.lang = nextLang;
        document.documentElement.dataset.lang = nextLang;
        document.cookie = `iq_lang=${nextLang}; path=/; max-age=31536000; SameSite=Lax`;
        if (persist) {
            try { localStorage.setItem(LANG_STORAGE_KEY, nextLang); } catch { /* игнор */ }
        }
        applyStaticTranslations();
        applyTheme(getResolvedTheme(), false);
        updateLandingCta();
        renderHeroDemo();
        renderDomainExplorer();
        updateDynamicFaq();
        $("email-error").hidden = true;
        $("checkout-error").hidden = true;
        document.documentElement.classList.remove("i18n-pending");
    }
    
    function initLanguage() {
        applyLanguage(getResolvedLang(), false);
    }

    async function syncLocalizedDataFromServer() {
        const targetLang = state.lang;
        try {
            const data = await apiFetch("/api/session/state");
            if (state.lang !== targetLang) return;
            if (Array.isArray(data.plans) && data.plans.length) {
                state.plans = data.plans;
                updateDynamicFaq();
            }
            if (Array.isArray(data.questions) && data.questions.length && state.quizActive) {
                state.questions = data.questions;
                if (state.screen === "quiz") {
                    renderQuestion({ resetQuestionTimer: false });
                }
            }
            if (data.result) {
                state.result = data.result;
                if (state.screen === "result") {
                    renderResult(false);
                }
            }
            if (state.screen === "paywall") renderPlans();
            if (state.screen === "checkout") renderCheckoutSummary();
        } catch (err) {
            console.warn("[LangSync]", err.message);
        }
    }

    async function toggleLanguage() {
        const nextLang = state.lang === "ru" ? "en" : "ru";
        applyLanguage(nextLang, true);
        if (state.screen === "quiz" && state.questions.length) {
            renderQuestion({ resetQuestionTimer: false });
        } else if (state.screen === "paywall") {
            renderPlans();
        } else if (state.screen === "checkout") {
            renderCheckoutSummary();
        } else if (state.screen === "result" && state.result) {
            renderResult(false);
        }
        await syncLocalizedDataFromServer();
    }

    function showToast(message, isError = false) {
        const el = $("toast");
        el.textContent = message;
        el.className = isError ? "toast toast--error" : "toast";
        el.hidden = false;
        clearTimeout(showToast.timer);
        showToast.timer = setTimeout(() => { el.hidden = true; }, 3400);
    }

    async function apiFetch(url, method = "GET", body = null) {
        const opts = {
            method,
            credentials: "same-origin",
            headers: { "X-Lang": state.lang || getResolvedLang() }
        };
        if (body !== null) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(url, opts);
        const data = await res.json().catch(() => ({ }));
        if (!res.ok) {
            throw new Error(data.error || t("err_conn"));
        }
        return data;
    }

    function trackEvent(eventName) {
        apiFetch("/api/funnel/event", "POST", { event: eventName }).catch((err) => {
            console.warn("[Funnel]", err.message);
        });
    }

    function getResolvedTheme() {
        const current = document.documentElement.dataset.theme;
        if (current === "dark" || current === "light") return current;
        try {
            const saved = localStorage.getItem(THEME_STORAGE_KEY);
            if (saved === "dark" || saved === "light") return saved;
        } catch { /* игнор */ }
        return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function applyTheme(theme, persist = true) {
        const nextTheme = theme === "dark" ? "dark" : "light";
        document.documentElement.dataset.theme = nextTheme;
        const meta = $("meta-theme-color");
        if (meta) meta.setAttribute("content", nextTheme === "dark" ? "#090a0f" : "#f6f7f4");

        const toggleBtn = $("btn-theme-toggle");
        if (toggleBtn) {
            const label = nextTheme === "dark" ? t("theme_to_light") : t("theme_to_dark");
            toggleBtn.setAttribute("aria-label", label);
            toggleBtn.setAttribute("title", label);
            toggleBtn.setAttribute("aria-pressed", String(nextTheme === "dark"));
        }

        if (persist) {
            try { localStorage.setItem(THEME_STORAGE_KEY, nextTheme); } catch { /* игнор */ }
        }
    }

    function toggleTheme() {
        const current = getResolvedTheme();
        applyTheme(current === "dark" ? "light" : "dark", true);
    }

    function initTheme() {
        applyTheme(getResolvedTheme(), false);
        if (!window.matchMedia) return;
        const media = window.matchMedia("(prefers-color-scheme: dark)");
        const onSystemChange = (e) => {
            let hasExplicit = false;
            try {
                const saved = localStorage.getItem(THEME_STORAGE_KEY);
                hasExplicit = saved === "dark" || saved === "light";
            } catch { /* игнор */ }
            if (!hasExplicit) applyTheme(e.matches ? "dark" : "light", false);
        };
        if (typeof media.addEventListener === "function") {
            media.addEventListener("change", onSystemChange);
        }
    }

    function getAnsweredSignature(answeredMap = state.answered) {
        return Object.keys(answeredMap || { }).sort((a, b) => Number(a) - Number(b)).join(",");
    }

    function getCurrentQuizElapsedMs() {
        return state.quizElapsedMs + (state.timerStartedAt ? Math.max(0, Date.now() - state.timerStartedAt) : 0);
    }

    function getCurrentQuestionElapsedMs() {
        return state.questionElapsedMs + (state.questionStartedAt ? Math.max(0, Date.now() - state.questionStartedAt) : 0);
    }

    function saveQuizProgress(pausedOnLanding = state.screen === "landing") {
        if (!state.quizActive) return;
        const payload = {
            quizActive: true,
            pausedOnLanding,
            currentIndex: state.currentIndex,
            draftOption: state.draftOption,
            quizElapsedMs: getCurrentQuizElapsedMs(),
            questionElapsedMs: getCurrentQuestionElapsedMs(),
            answeredSig: getAnsweredSignature()
        };
        const raw = JSON.stringify(payload);
        try { localStorage.setItem(PROGRESS_STORAGE_KEY, raw); } catch { /* игнор */ }
        try { sessionStorage.setItem(PROGRESS_STORAGE_KEY, raw); } catch { /* игнор */ }
    }

    function loadQuizProgress() {
        for (const store of [localStorage, sessionStorage]) {
            try {
                const raw = store.getItem(PROGRESS_STORAGE_KEY);
                if (!raw) continue;
                const parsed = JSON.parse(raw);
                if (parsed && typeof parsed === "object" && parsed.quizActive === true) {
                    return parsed;
                }
            } catch { /* игнор */ }
        }
        return null;
    }

    function clearQuizProgress() {
        try { localStorage.removeItem(PROGRESS_STORAGE_KEY); } catch { /* игнор */ }
        try { sessionStorage.removeItem(PROGRESS_STORAGE_KEY); } catch { /* игнор */ }
        try { sessionStorage.removeItem("iq_quiz_started_at"); } catch { /* игнор */ }
    }

    function formatDuration(ms) {
        const totalSec = Math.max(0, Math.floor(ms / 1000));
        const min = String(Math.floor(totalSec / 60)).padStart(2, "0");
        const sec = String(totalSec % 60).padStart(2, "0");
        return `${min}:${sec}`;
    }

    function pauseTimer() {
        if (state.timerId) {
            clearInterval(state.timerId);
            state.timerId = null;
        }
        if (state.timerStartedAt) {
            state.quizElapsedMs += Math.max(0, Date.now() - state.timerStartedAt);
            state.timerStartedAt = 0;
        }
        if (state.questionStartedAt) {
            state.questionElapsedMs += Math.max(0, Date.now() - state.questionStartedAt);
            state.questionStartedAt = 0;
        }
        $("header-timer").hidden = true;
    }

    function startTimer() {
        if (state.timerId) {
            clearInterval(state.timerId);
            state.timerId = null;
        }
        state.timerStartedAt = Date.now();
        if (!state.questionStartedAt) {
            state.questionStartedAt = Date.now();
        }
        const timerEl = $("header-timer");
        timerEl.hidden = false;
        const tick = () => {
            timerEl.textContent = formatDuration(getCurrentQuizElapsedMs());
        };
        tick();
        state.timerId = setInterval(tick, 1000);
    }

    function updateLandingCta() {
        const heroLabelEl = $("btn-start-quiz").querySelector("span");
        const bottomBtn = $("btn-bottom-start");
        const bottomLabelEl = bottomBtn ? bottomBtn.querySelector("span") : null;
        const headerBtn = $("btn-header-start");
        let heroText = t("btn_start_hero");
        let headerText = t("btn_start_header");

        if (state.quizActive && state.sessionStatus === "started" && state.questions.length > 0) {
            const total = state.questions.length || state.totalQuestions;
            const pos = Math.min(state.currentIndex + 1, total);
            heroText = t("btn_continue_hero", { pos, total });
            headerText = t("btn_continue_header");
        } else if (state.sessionStatus === "completed") {
            heroText = state.paymentStatus === "paid" ? t("btn_open_report_hero") : t("btn_back_result_hero");
            headerText = state.paymentStatus === "paid" ? t("btn_my_report_header") : t("btn_to_result_header");
        }

        if (heroLabelEl) heroLabelEl.textContent = heroText;
        if (bottomLabelEl) bottomLabelEl.textContent = heroText;
        headerBtn.textContent = headerText;
    }

    function demoOuterSvg(shape, cx, cy, r = 20) {
        if (shape === "circle") {
            return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="currentColor" stroke-width="2.4"/>`;
        }
        if (shape === "diamond") {
            const pts = `${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}`;
            return `<polygon points="${pts}" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>`;
        }
        if (shape === "triangle") {
            const pts = `${cx},${cy - r} ${(cx + r * 0.95).toFixed(1)},${(cy + r * 0.78).toFixed(1)} ${(cx - r * 0.95).toFixed(1)},${(cy + r * 0.78).toFixed(1)}`;
            return `<polygon points="${pts}" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/>`;
        }
        return "";
    }

    function demoInnerSvg(mark, cx, cy, r = 9, yOff = 0) {
        const yc = cy + yOff;
        if (mark === "h") {
            return `<line x1="${cx - r}" y1="${yc}" x2="${cx + r}" y2="${yc}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>`;
        }
        if (mark === "v") {
            return `<line x1="${cx}" y1="${yc - r}" x2="${cx}" y2="${yc + r}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>`;
        }
        if (mark === "plus") {
            return (
                `<line x1="${cx - r}" y1="${yc}" x2="${cx + r}" y2="${yc}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>` +
                `<line x1="${cx}" y1="${yc - r}" x2="${cx}" y2="${yc + r}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>`
            );
        }
        if (mark === "cross") {
            const d = (r * 0.78).toFixed(1);
            return (
                `<line x1="${cx - d}" y1="${yc - d}" x2="${cx + Number(d)}" y2="${yc + Number(d)}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>` +
                `<line x1="${cx + Number(d)}" y1="${yc - d}" x2="${cx - d}" y2="${yc + Number(d)}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>`
            );
        }
        return "";
    }

    function renderHeroDemo() {
        const matrixEl = $("hero-demo-matrix");
        const optionsEl = $("hero-demo-options");
        const feedbackEl = $("hero-demo-feedback");
        const resetBtn = $("btn-demo-reset");
        if (!matrixEl || !optionsEl) return;

        const cell = 80;
        const rows = [["circle", "h"], ["diamond", "v"], ["triangle", "plus"]];
        const parts = [ ];
        rows.forEach(([outer, inner], rIdx) => {
            for (let cIdx = 0; cIdx < 3; cIdx += 1) {
                const x = cIdx * cell;
                const y = rIdx * cell;
                const cx = x + cell / 2;
                const cy = y + cell / 2;
                if (rIdx === 2 && cIdx === 2) {
                    parts.push(`<rect x="${x + 2}" y="${y + 2}" width="${cell - 4}" height="${cell - 4}" rx="8" fill="var(--accent-soft)" stroke="var(--accent)" stroke-opacity="0.65" stroke-dasharray="4 3" stroke-width="2"/>`);
                    parts.push(`<text x="${cx}" y="${y + 51}" text-anchor="middle" font-size="32" font-weight="700" fill="var(--accent)">?</text>`);
                } else {
                    parts.push(`<rect x="${x + 2}" y="${y + 2}" width="${cell - 4}" height="${cell - 4}" rx="8" fill="none" stroke="currentColor" stroke-opacity="0.2" stroke-width="1.8"/>`);
                    const yOff = outer === "triangle" ? 4 : 0;
                    const rIn = outer === "triangle" ? 7 : 9;
                    if (cIdx === 0) parts.push(demoOuterSvg(outer, cx, cy));
                    else if (cIdx === 1) parts.push(demoInnerSvg(inner, cx, cy, 11, 0));
                    else parts.push(demoOuterSvg(outer, cx, cy) + demoInnerSvg(inner, cx, cy, rIn, yOff));
                }
            }
        });
        matrixEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240" role="img" aria-label="${escapeHtml(t("demo_matrix_aria"))}">${parts.join("")}</svg>`;

        const correctIdx = 1;
        const specs = [
            ["triangle", "cross", 4, 7],
            ["triangle", "plus", 4, 7],
            ["diamond", "plus", 0, 9],
            ["triangle", "h", 4, 7]
        ];
        const answered = state.demoChoice !== null;
        optionsEl.innerHTML = specs.map(([outer, inner, yOff, rIn], idx) => {
            let cls = "hero-demo-opt";
            if (answered) {
                if (idx === correctIdx) cls += " is-correct";
                else if (idx === state.demoChoice) cls += " is-wrong";
            }
            const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">${demoOuterSvg(outer, 40, 40)}${demoInnerSvg(inner, 40, 40, rIn, yOff)}</svg>`;
            return `<button type="button" class="${cls}" data-demo-opt="${idx}" aria-label="${escapeHtml(t("demo_option_aria", { n: idx + 1 }))}">${svg}</button>`;
        }).join("");

        resetBtn.hidden = !answered;
        if (answered) {
            const isOk = state.demoChoice === correctIdx;
            feedbackEl.className = `hero-demo-feedback ${isOk ? "is-correct" : "is-wrong"}`;
            $("hero-demo-status").textContent = isOk ? t("demo_correct_title") : t("demo_wrong_title");
            $("hero-demo-explain").textContent = t("demo_explain");
            feedbackEl.hidden = false;
        } else {
            feedbackEl.hidden = true;
        }
    }

    function renderDomainExplorer() {
        const tabsEl = $("explorer-tabs");
        const previewEl = $("explorer-preview");
        if (!tabsEl || !previewEl) return;

        const key = ["spatial", "numerical", "verbal_logic", "speed"].includes(state.activeDomainTab)
            ? state.activeDomainTab
            : "spatial";

        tabsEl.querySelectorAll("[data-domain-tab]").forEach((btn) => {
            const active = btn.dataset.domainTab === key;
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-selected", String(active));
        });

        $("explorer-weight").textContent = t(`exp_${key}_weight`);
        $("explorer-title").textContent = t(`exp_${key}_title`);
        $("explorer-desc").textContent = t(`exp_${key}_desc`);
        $("explorer-note").textContent = t(`exp_${key}_note`);

        const svgs = {
            spatial: `<svg viewBox="0 0 220 120" xmlns="http://www.w3.org/2000/svg">
                <rect x="12" y="22" width="52" height="52" rx="10" fill="none" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.8"/>
                <path d="M 38 34 L 50 48 L 38 62" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M 70 48 L 82 48" stroke="var(--accent)" stroke-width="2" stroke-dasharray="3 2"/>
                <rect x="86" y="22" width="52" height="52" rx="10" fill="none" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.8"/>
                <path d="M 98 48 L 112 60 L 126 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M 144 48 L 156 48" stroke="var(--accent)" stroke-width="2" stroke-dasharray="3 2"/>
                <rect x="160" y="22" width="52" height="52" rx="10" fill="var(--accent-soft)" stroke="var(--accent)" stroke-dasharray="4 3" stroke-width="1.8"/>
                <text x="186" y="56" text-anchor="middle" font-size="22" font-weight="700" fill="var(--accent)">?</text>
                <text x="112" y="102" text-anchor="middle" font-size="11" font-family="var(--font-mono)" fill="var(--muted)">+90°</text>
            </svg>`,
            numerical: `<svg viewBox="0 0 220 120" xmlns="http://www.w3.org/2000/svg">
                <path d="M 30 42 Q 52 16 74 42" fill="none" stroke="var(--accent)" stroke-width="1.6"/>
                <path d="M 74 42 Q 96 16 118 42" fill="none" stroke="var(--accent)" stroke-width="1.6"/>
                <path d="M 118 42 Q 140 16 162 42" fill="none" stroke="var(--accent)" stroke-width="1.6"/>
                <text x="52" y="22" text-anchor="middle" font-size="10" font-family="var(--font-mono)" fill="var(--accent)">+4</text>
                <text x="96" y="22" text-anchor="middle" font-size="10" font-family="var(--font-mono)" fill="var(--accent)">+6</text>
                <text x="140" y="22" text-anchor="middle" font-size="10" font-family="var(--font-mono)" fill="var(--accent)">+8</text>
                <circle cx="30" cy="60" r="16" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.6"/>
                <circle cx="74" cy="60" r="16" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.6"/>
                <circle cx="118" cy="60" r="16" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.6"/>
                <circle cx="162" cy="60" r="16" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.25" stroke-width="1.6"/>
                <circle cx="198" cy="60" r="16" fill="var(--accent-soft)" stroke="var(--accent)" stroke-dasharray="3 2" stroke-width="1.8"/>
                <text x="30" y="64" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">2</text>
                <text x="74" y="64" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">6</text>
                <text x="118" y="64" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">12</text>
                <text x="162" y="64" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">20</text>
                <text x="198" y="65" text-anchor="middle" font-size="13" font-family="var(--font-mono)" font-weight="700" fill="var(--accent)">?</text>
                <text x="110" y="102" text-anchor="middle" font-size="11" font-family="var(--font-mono)" fill="var(--muted)">Δ = +2n</text>
            </svg>`,
            verbal_logic: `<svg viewBox="0 0 220 120" xmlns="http://www.w3.org/2000/svg">
                <rect x="16" y="34" width="48" height="32" rx="8" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.6"/>
                <rect x="86" y="34" width="48" height="32" rx="8" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1.8"/>
                <rect x="156" y="34" width="48" height="32" rx="8" fill="var(--surface)" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.6"/>
                <line x1="64" y1="50" x2="84" y2="50" stroke="var(--accent)" stroke-width="1.8"/>
                <line x1="134" y1="50" x2="154" y2="50" stroke="var(--accent)" stroke-width="1.8"/>
                <text x="40" y="54" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">A</text>
                <text x="110" y="54" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="var(--accent)">B</text>
                <text x="180" y="54" text-anchor="middle" font-size="12" font-family="var(--font-mono)" font-weight="700" fill="currentColor">C</text>
                <text x="110" y="96" text-anchor="middle" font-size="11" font-family="var(--font-mono)" fill="var(--muted)">A → B → C</text>
            </svg>`,
            speed: `<svg viewBox="0 0 220 120" xmlns="http://www.w3.org/2000/svg">
                <path d="M 52 78 A 58 58 0 0 1 168 78" fill="none" stroke="var(--track-bg)" stroke-width="10" stroke-linecap="round"/>
                <path d="M 52 78 A 58 58 0 0 1 148 34" fill="none" stroke="var(--success)" stroke-width="10" stroke-linecap="round"/>
                <circle cx="110" cy="78" r="5" fill="var(--ink)"/>
                <line x1="110" y1="78" x2="144" y2="39" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round"/>
                <text x="110" y="106" text-anchor="middle" font-size="11" font-family="var(--font-mono)" fill="var(--muted)">ms × %</text>
            </svg>`
        };
        previewEl.innerHTML = svgs[key] || svgs.spatial;
    }

    function showScreen(name) {
        state.screen = name;
        const screens = ["landing", "quiz", "analyzing", "email", "paywall", "checkout", "result"];
        screens.forEach((s) => { $(`screen-${s}`).hidden = s !== name; });

        const onLanding = name === "landing";
        $("btn-header-start").hidden = !onLanding;
        $("btn-header-restart").hidden = onLanding || name === "analyzing";
        if (onLanding) updateLandingCta();
        if (name !== "quiz") pauseTimer();
        window.scrollTo({ top: 0, behavior: "smooth" });
    }

    function findFirstUnanswered() {
        const idx = state.questions.findIndex((q) => state.answered[String(q.id)] === undefined);
        return idx === -1 ? Math.max(0, state.questions.length - 1) : idx;
    }

    function renderQuestion({ resetQuestionTimer = true, animate = false } = { }) {
        const q = state.questions[state.currentIndex];
        if (!q) return;

        const total = state.questions.length || state.totalQuestions;
        const qKey = String(q.id);
        const savedOption = state.answered[qKey];
        const isLocked = savedOption !== undefined;
        const activeOption = isLocked ? savedOption : state.draftOption;

        $("quiz-counter").textContent = t("quiz_counter", { n: state.currentIndex + 1, total });
        const kindKey = `kind_${q.kind}`;
        const kindText = t(kindKey);
        $("quiz-kind-badge").textContent = kindText === kindKey ? t("kind_logic") : kindText;
        $("quiz-progress-fill").style.width = `${Math.round(((state.currentIndex + 1) / total) * 100)}%`;
        if (animate) {
            const cardEl = $("quiz-card");
            if (cardEl) {
                cardEl.classList.remove("is-entering");
                void cardEl.offsetWidth;
                cardEl.classList.add("is-entering");
            }
        }
        $("quiz-prompt").textContent = q.prompt;

        const visualEl = $("quiz-svg");
        if (q.svg) {
            visualEl.innerHTML = q.svg;
            visualEl.hidden = false;
        } else {
            visualEl.innerHTML = "";
            visualEl.hidden = true;
        }

        $("quiz-locked-note").hidden = !isLocked;

        const isSvgOpts = q.options.some((opt) => opt.type === "svg");
        const gridEl = $("quiz-options");
        gridEl.className = isSvgOpts ? "options-grid options-grid--svg" : "options-grid";

        const letters = ["A", "B", "C", "D"];
        gridEl.innerHTML = q.options.map((opt, idx) => {
            const selectedCls = activeOption === idx ? " is-selected" : "";
            const lockedCls = isLocked ? " is-locked" : "";
            const svgCls = isSvgOpts ? " option-btn--svg" : "";
            const content = opt.type === "svg"
                ? opt.value
                : `<span class="option-key">${letters[idx]}</span><span>${escapeHtml(opt.value)}</span>`;
            return `<button type="button" class="option-btn${svgCls}${selectedCls}${lockedCls}" data-opt="${idx}">${content}</button>`;
        }).join("");

        $("btn-prev").disabled = state.currentIndex === 0;
        const nextBtn = $("btn-next");
        const isLast = state.currentIndex === total - 1;
        nextBtn.textContent = isLast ? t("quiz_finish") : t("quiz_next");
        nextBtn.disabled = activeOption === null;

        if (resetQuestionTimer) {
            state.questionElapsedMs = 0;
            state.questionStartedAt = Date.now();
        } else if (!state.questionStartedAt) {
            state.questionStartedAt = Date.now();
        }
    }

    async function beginQuiz(restart = false) {
        const startBtn = $("btn-start-quiz");
        const bottomStartBtn = $("btn-bottom-start");
        const headerStartBtn = $("btn-header-start");
        const headerRestartBtn = $("btn-header-restart");
        startBtn.disabled = true;
        if (bottomStartBtn) bottomStartBtn.disabled = true;
        headerStartBtn.disabled = true;
        headerRestartBtn.disabled = true;
        try {
            if (restart) {
                clearQuizProgress();
            }
            const data = await apiFetch("/api/session/start", "POST", { restart });
            state.sessionStatus = "started";
            state.paymentStatus = "unpaid";
            state.hasEmail = false;
            state.quizActive = true;
            state.returnScreen = null;
            state.questions = data.questions || [ ];
            state.totalQuestions = data.total_questions || 15;
            state.answered = data.answered || { };
            state.draftOption = null;
            state.result = null;
            state.reviewFilter = "all";
            state.quizElapsedMs = 0;
            state.timerStartedAt = 0;
            state.questionElapsedMs = 0;
            state.questionStartedAt = 0;
            state.currentIndex = findFirstUnanswered();
            showScreen("quiz");
            startTimer();
            renderQuestion({ resetQuestionTimer: true });
            saveQuizProgress(false);
        } catch (err) {
            console.error("[QuizStart]", err);
            showToast(err.message, true);
        } finally {
            startBtn.disabled = false;
            if (bottomStartBtn) bottomStartBtn.disabled = false;
            headerStartBtn.disabled = false;
            headerRestartBtn.disabled = false;
        }
    }

    async function handleStartAction() {
        if (state.quizActive && state.sessionStatus === "started" && state.questions.length > 0) {
            showScreen("quiz");
            startTimer();
            renderQuestion({ resetQuestionTimer: false });
            saveQuizProgress(false);
            return;
        }
        if (state.sessionStatus === "completed") {
            if (state.paymentStatus === "paid") {
                renderResult(true);
                showScreen("result");
            } else if (state.returnScreen === "checkout") {
                openCheckout();
            } else if (state.hasEmail) {
                openPaywall();
            } else {
                showScreen("email");
            }
            return;
        }
        await beginQuiz(false);
    }

    async function handleNextQuestion() {
        const q = state.questions[state.currentIndex];
        if (!q) return;

        const qKey = String(q.id);
        const alreadySaved = state.answered[qKey] !== undefined;
        const nextBtn = $("btn-next");

        if (!alreadySaved) {
            if (state.draftOption === null) return;
            nextBtn.disabled = true;
            try {
                const timeMs = Math.max(200, getCurrentQuestionElapsedMs());
                await apiFetch("/api/quiz/answer", "POST", {
                    question_id: q.id,
                    option_index: state.draftOption,
                    time_ms: timeMs
                });
                state.answered[qKey] = state.draftOption;
                state.draftOption = null;
            } catch (err) {
                console.error("[SubmitAnswer]", err);
                showToast(err.message, true);
                nextBtn.disabled = false;
                return;
            }
        }

        const total = state.questions.length || state.totalQuestions;
        if (state.currentIndex < total - 1) {
            state.currentIndex += 1;
            state.draftOption = null;
            renderQuestion({ resetQuestionTimer: true, animate: true });
            saveQuizProgress(false);
            return;
        }

        // Обновляем UI последнего вопроса до открытия модалки, чтобы кнопка не оставалась disabled при отмене
        renderQuestion({ resetQuestionTimer: false });
        saveQuizProgress(false);

        if (Object.keys(state.answered).length >= total) {
            openConfirmModal({
                title: t("confirm_finish_title"),
                message: t("confirm_finish_body", { total }),
                confirmText: t("confirm_finish_ok"),
                cancelText: t("confirm_finish_cancel"),
                onConfirm: finishQuizFlow
            });
        } else {
            state.currentIndex = findFirstUnanswered();
            renderQuestion({ resetQuestionTimer: true });
            saveQuizProgress(false);
            showToast(t("quiz_answer_all_toast"), true);
        }
    }

    function handleQuizKeydown(e) {
        if (state.screen !== "quiz") return;
        if (!$("modal-confirm").hidden || !$("modal-info").hidden) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;

        const q = state.questions[state.currentIndex];
        if (!q) return;

        const codeMap = {
            Digit1: 0, Numpad1: 0, KeyA: 0,
            Digit2: 1, Numpad2: 1, KeyB: 1,
            Digit3: 2, Numpad3: 2, KeyC: 2,
            Digit4: 3, Numpad4: 3, KeyD: 3
        };
        if (Object.prototype.hasOwnProperty.call(codeMap, e.code)) {
            if (state.answered[String(q.id)] !== undefined) return;
            const idx = codeMap[e.code];
            if (idx < q.options.length) {
                state.draftOption = idx;
                renderQuestion({ resetQuestionTimer: false });
                saveQuizProgress(false);
            }
            return;
        }
        if (e.code === "ArrowLeft" && !$("btn-prev").disabled) {
            e.preventDefault();
            $("btn-prev").click();
            return;
        }
        if (e.code === "ArrowRight" && state.answered[String(q.id)] !== undefined && !$("btn-next").disabled) {
            e.preventDefault();
            handleNextQuestion();
            return;
        }
        if (e.code === "Enter" && !$("btn-next").disabled) {
            e.preventDefault();
            handleNextQuestion();
        }
    }

    function runAnalyzingSteps() {
        const items = Array.from(document.querySelectorAll("#analyzing-steps li"));
        items.forEach((li) => { li.className = ""; });
        return new Promise((resolve) => {
            let idx = 0;
            const step = () => {
                if (idx > 0) items[idx - 1].className = "is-done";
                if (idx < items.length) {
                    items[idx].className = "is-active";
                    idx += 1;
                    setTimeout(step, 440);
                } else {
                    setTimeout(resolve, 260);
                }
            };
            step();
        });
    }

    async function finishQuizFlow() {
        closeConfirmModal();
        showScreen("analyzing");
        try {
            const [res] = await Promise.all([
                apiFetch("/api/quiz/finish", "POST", { }),
                runAnalyzingSteps()
            ]);
            state.sessionStatus = "completed";
            state.quizActive = false;
            state.hasEmail = Boolean(res.has_email);
            state.paymentStatus = res.payment_status || "unpaid";
            clearQuizProgress();
            if (res.payment_status === "paid") {
                const paid = await apiFetch("/api/result");
                state.result = paid.result;
                renderResult(true);
                showScreen("result");
            } else if (!res.has_email) {
                showScreen("email");
            } else {
                openPaywall();
            }
        } catch (err) {
            console.error("[FinishQuiz]", err);
            showToast(err.message, true);
            showScreen("quiz");
            startTimer();
            renderQuestion({ resetQuestionTimer: false });
        }
    }

    function openPaywall() {
        renderPlans();
        trackEvent("paywall_view");
        showScreen("paywall");
    }

    function updateDynamicFaq() {
        const faqEl = $("faq-answer-trial");
        if (!faqEl) return;
        const trial = state.plans.find((p) => p.id === "trial_sub");
        if (trial && trial.price_label && trial.renewal_price_label) {
            faqEl.textContent = t("faq_a1_tpl", {
                trial_price: trial.price_label,
                renewal_price: trial.renewal_price_label
            });
        } else {
            faqEl.textContent = t("faq_a1_fallback");
        }
    }

    function renderPlans() {
        const grid = $("paywall-plans");
        if (!state.plans.length) return;
        if (!state.plans.some((p) => p.id === state.selectedPlanId)) {
            state.selectedPlanId = state.plans[0].id;
        }
        grid.innerHTML = state.plans.map((plan) => {
            const activeCls = plan.id === state.selectedPlanId ? " is-selected" : "";
            const badge = plan.badge ? `<span class="plan-card__badge">${escapeHtml(plan.badge)}</span>` : "";
            const feats = (plan.features || [ ]).map((f) => `<li>${escapeHtml(f)}</li>`).join("");
            const isRecurring = Boolean(plan.renewal_price_label) && plan.id === "trial_sub";
            const termsText = plan.renewal_price_label ? plan.billing_note : t("plan_terms_one_time");
            return `
                <button type="button" class="plan-card${activeCls}" data-plan="${escapeHtml(plan.id)}">
                    ${badge}
                    <h3>${escapeHtml(plan.title)}</h3>
                    <div class="plan-card__price">${escapeHtml(plan.price_label)} <small class="muted">${escapeHtml(plan.period_label)}</small></div>
                    <div class="plan-card__terms${isRecurring ? " is-recurring" : ""}">
                        <span>${escapeHtml(t("plan_renewal_label"))}</span>
                        <strong>${escapeHtml(termsText)}</strong>
                    </div>
                    <ul class="plan-card__features">${feats}</ul>
                </button>`;
        }).join("");

        const chosen = state.plans.find((p) => p.id === state.selectedPlanId) || state.plans[0];
        $("btn-open-checkout").textContent = t("paywall_cta", { price: chosen.price_label });
        $("paywall-selected-note").textContent = chosen.billing_note;
        updateDynamicFaq();
    }

    function renderCheckoutSummary() {
        const chosen = state.plans.find((p) => p.id === state.selectedPlanId) || state.plans[0];
        if (!chosen) return;
        $("checkout-plan-title").textContent = chosen.title;
        $("checkout-plan-renewal").textContent = chosen.billing_note;
        $("checkout-plan-price").textContent = chosen.price_label;
        $("btn-pay-submit").textContent = t("checkout_pay_btn", { price: chosen.price_label });
    }

    function openCheckout() {
        if (!state.plans.length) return;
        renderCheckoutSummary();
        $("checkout-error").hidden = true;
        trackEvent("checkout_open");
        showScreen("checkout");
    }

    function renderBellCurve(iq, bandLow = iq - 7, bandHigh = iq + 8) {
        const w = 360, h = 178, padX = 22, baseY = 126, amp = 84;
        const minX = 65, maxX = 145;
        const toX = (val) => padX + ((val - minX) / (maxX - minX)) * (w - padX * 2);
        const pdfY = (val) => {
            const z = (val - 100) / 15;
            return baseY - amp * Math.exp(-0.5 * z * z);
        };

        const fullPts = [ ];
        const areaPts = [`${toX(minX).toFixed(1)},${baseY}`];
        for (let x = minX; x <= maxX; x += 1) {
            const px = toX(x).toFixed(1);
            const py = pdfY(x).toFixed(1);
            fullPts.push(`${px},${py}`);
            if (x <= iq) areaPts.push(`${px},${py}`);
        }
        const userX = toX(iq);
        const userY = pdfY(iq);
        areaPts.push(`${userX.toFixed(1)},${userY.toFixed(1)}`, `${userX.toFixed(1)},${baseY}`);
        const lowX = toX(Math.max(minX, bandLow));
        const highX = toX(Math.min(maxX, bandHigh));
        const labelX = Math.max(52, Math.min(w - 52, userX));
        const meanX = toX(100);
        const ticks = [70, 85, 100, 115, 130, 145].map((tVal) =>
            `<text x="${toX(tVal).toFixed(1)}" y="146" text-anchor="middle" font-size="11" font-family="var(--font-mono)" fill="var(--muted)">${tVal}</text>`
        ).join("");

        return `
            <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${escapeHtml(t("chart_bell_aria"))}">
                <defs>
                    <linearGradient id="bell-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.28"/>
                        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.03"/>
                    </linearGradient>
                </defs>
                <line x1="${meanX.toFixed(1)}" y1="${pdfY(100).toFixed(1)}" x2="${meanX.toFixed(1)}" y2="${baseY}" stroke="var(--border-strong)" stroke-dasharray="2 3" stroke-width="1.2"/>
                <polygon points="${areaPts.join(" ")}" fill="url(#bell-fill)"/>
                <polyline points="${fullPts.join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2.6" stroke-linecap="round"/>
                <line x1="${padX}" y1="${baseY}" x2="${w - padX}" y2="${baseY}" stroke="var(--border-strong)" stroke-width="1.5"/>
                <line x1="${lowX.toFixed(1)}" y1="${baseY}" x2="${highX.toFixed(1)}" y2="${baseY}" stroke="var(--success)" stroke-width="4" stroke-linecap="round"/>
                <line x1="${userX.toFixed(1)}" y1="${userY.toFixed(1)}" x2="${userX.toFixed(1)}" y2="${baseY}" stroke="var(--ink)" stroke-dasharray="3 3" stroke-width="1.5"/>
                <circle cx="${userX.toFixed(1)}" cy="${userY.toFixed(1)}" r="5" fill="var(--ink)" stroke="var(--surface)" stroke-width="2"/>
                <rect x="${(labelX - 38).toFixed(1)}" y="5" width="76" height="22" rx="11" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="1"/>
                <text x="${labelX.toFixed(1)}" y="20" text-anchor="middle" font-size="11.5" font-family="var(--font-mono)" font-weight="700" fill="var(--accent)">${escapeHtml(t("chart_you"))}: ${iq}</text>
                ${ticks}
                <text x="180" y="168" text-anchor="middle" font-size="10.5" font-weight="600" fill="var(--success)">● ${escapeHtml(t("chart_band_label", { low: bandLow, high: bandHigh }))}</text>
            </svg>`;
    }

    function renderPercentileRing(pct) {
        const r = 52;
        const c = 2 * Math.PI * r;
        const offset = c - (pct / 100) * c;
        return `
            <svg viewBox="0 0 140 140" width="136" height="136" role="img" aria-label="${escapeHtml(t("chart_ring_aria", { pct }))}">
                <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--track-bg)" stroke-width="12"/>
                <circle cx="70" cy="70" r="${r}" fill="none" stroke="var(--accent)" stroke-width="12"
                    stroke-linecap="round" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${offset.toFixed(2)}"
                    transform="rotate(-90 70 70)"/>
                <text x="70" y="76" text-anchor="middle" font-size="25" font-family="var(--font-mono)" font-weight="700" fill="var(--ink)">${pct}%</text>
            </svg>`;
    }

    function renderCognitiveRadar(domains) {
        if (!Array.isArray(domains) || !domains.length) return "";
        const map = { };
        domains.forEach((d) => { map[d.key] = Number(d.score) || 0; });
        const axes = [
            { key: "spatial", label: t("radar_spatial"), angle: -Math.PI / 2, tx: 160, ty: 24, anchor: "middle", py: 39 },
            { key: "numerical", label: t("radar_numerical"), angle: 0, tx: 244, ty: 127, anchor: "start", py: 142 },
            { key: "verbal_logic", label: t("radar_verbal_logic"), angle: Math.PI / 2, tx: 160, ty: 226, anchor: "middle", py: 241 },
            { key: "speed", label: t("radar_speed"), angle: Math.PI, tx: 76, ty: 127, anchor: "end", py: 142 }
        ];
        const cx = 160, cy = 130, maxR = 72;
        const rings = [0.25, 0.5, 0.75, 1].map((lvl) => {
            const pts = axes.map((a) => `${(cx + maxR * lvl * Math.cos(a.angle)).toFixed(1)},${(cy + maxR * lvl * Math.sin(a.angle)).toFixed(1)}`).join(" ");
            return `<polygon points="${pts}" fill="none" stroke="var(--border-strong)" stroke-opacity="0.55" stroke-width="1"/>`;
        }).join("");

        const spokes = axes.map((a) => {
            const x2 = (cx + maxR * Math.cos(a.angle)).toFixed(1);
            const y2 = (cy + maxR * Math.sin(a.angle)).toFixed(1);
            return `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="var(--border-strong)" stroke-opacity="0.7" stroke-width="1"/>`;
        }).join("");

        const dataPts = axes.map((a) => {
            const ratio = Math.max(0.08, Math.min(1, (map[a.key] || 0) / 100));
            return {
                x: cx + maxR * ratio * Math.cos(a.angle),
                y: cy + maxR * ratio * Math.sin(a.angle),
                score: map[a.key] || 0
            };
        });
        const polyPts = dataPts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
        const dots = dataPts.map((p) =>
            `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4.5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`
        ).join("");
        const labels = axes.map((a, idx) => `
            <text x="${a.tx}" y="${a.ty}" text-anchor="${a.anchor}" font-size="11.5" font-weight="700" fill="var(--ink)">${escapeHtml(a.label)}</text>
            <text x="${a.tx}" y="${a.py}" text-anchor="${a.anchor}" font-size="11" font-family="var(--font-mono)" font-weight="600" fill="var(--accent)">${dataPts[idx].score}%</text>`
        ).join("");

        return `
            <svg viewBox="0 0 320 260" role="img" aria-label="${escapeHtml(t("radar_aria"))}">
                ${rings}
                ${spokes}
                <polygon points="${polyPts}" fill="var(--accent)" fill-opacity="0.2" stroke="var(--accent)" stroke-width="2.4" stroke-linejoin="round"/>
                ${dots}
                ${labels}
            </svg>`;
    }

    function renderReviewList() {
        const r = state.result;
        if (!r) return;
        const items = (r.review || [ ]).filter((item) => state.reviewFilter === "all" || !item.is_correct);
        const listEl = $("res-review");
        if (!items.length) {
            listEl.innerHTML = `<p class="muted">${escapeHtml(t("review_no_mistakes"))}</p>`;
            return;
        }
        listEl.innerHTML = items.map((item) => {
            const renderOpt = (idx) => {
                if (idx === null || idx === undefined) return escapeHtml(t("review_no_answer"));
                const opt = item.options[idx];
                if (!opt) return escapeHtml(t("review_no_answer"));
                return opt.type === "svg" ? opt.value : escapeHtml(opt.value);
            };
            const sec = (item.time_ms / 1000).toFixed(1);
            const statusCls = item.is_correct ? "is-correct" : "is-wrong";
            const statusText = item.is_correct ? t("review_status_ok") : t("review_status_bad");
            const userPill = item.is_correct
                ? ""
                : `<span class="review-ans-pill is-bad">${escapeHtml(t("review_user_ans"))}: ${renderOpt(item.user_option)}</span>`;
            const svgHtml = item.svg ? `<div class="review-item__svg">${item.svg}</div>` : "";
            return `
                <article class="review-item ${statusCls}">
                    <div class="review-item__head">
                        <strong>${escapeHtml(t("review_q_head", { id: item.id, sec }))}</strong>
                        <span class="review-badge">${escapeHtml(statusText)}</span>
                    </div>
                    <p>${escapeHtml(item.prompt)}</p>
                    ${svgHtml}
                    <div class="review-answers">
                        ${userPill}
                        <span class="review-ans-pill is-ok">${escapeHtml(t("review_correct_ans"))}: ${renderOpt(item.correct_option)}</span>
                    </div>
                </article>`;
        }).join("");
    }

    function animateIqValue(targetIq, shouldAnimate) {
        const el = $("res-iq");
        if (!el) return;
        const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (!shouldAnimate || reduced) {
            el.textContent = targetIq;
            return;
        }
        const startVal = Math.max(70, targetIq - 28);
        const duration = 700;
        const startTs = performance.now();
        const frame = (now) => {
            const p = Math.min(1, (now - startTs) / duration);
            const eased = 1 - Math.pow(1 - p, 3);
            el.textContent = Math.round(startVal + (targetIq - startVal) * eased);
            if (p < 1) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
    }

    function renderResult(animateIq = false) {
        const r = state.result;
        if (!r) return;
        const plan = state.plans.find((p) => p.id === r.plan);
        $("res-plan-badge").textContent = plan ? `${t("res_plan_prefix")}: ${plan.title}` : t("res_plan_active");
        animateIqValue(r.iq, animateIq);
        $("res-category").textContent = r.category;
        $("res-band").textContent = `${r.band_low}–${r.band_high}`;
        $("res-raw").textContent = `${r.raw_score} / ${r.total_questions}`;
        $("res-time").textContent = `${r.avg_time_sec} ${t("unit_sec")}`;
        $("res-percentile-text").textContent = t("res_percentile_text", { pct: r.percentile });
        $("chart-bell").innerHTML = renderBellCurve(r.iq, r.band_low, r.band_high);
        $("chart-ring").innerHTML = renderPercentileRing(r.percentile);
        const radarEl = $("chart-radar");
        if (radarEl) radarEl.innerHTML = renderCognitiveRadar(r.domains || [ ]);

        $("res-domains").innerHTML = (r.domains || [ ]).map((d) => `
            <div class="domain-item">
                <div class="domain-item__head">
                    <span>${escapeHtml(d.title)}</span>
                    <span>${d.score}%</span>
                </div>
                <div class="domain-bar"><div class="domain-bar__fill" style="width:${d.score}%"></div></div>
                <span class="domain-item__meta">${escapeHtml(d.description)} (${d.solved}/${d.total})</span>
            </div>`
        ).join("");
        renderReviewList();
    }

    function openConfirmModal({ title, message, confirmText, cancelText = "Вернуться", onConfirm }) {
        $("confirm-title").textContent = title;
        $("confirm-body").textContent = message;
        $("btn-confirm-ok").textContent = confirmText;
        $("btn-confirm-cancel").textContent = cancelText;
        state.confirmAction = onConfirm;
        $("modal-confirm").hidden = false;
    }

    function closeConfirmModal() {
        $("modal-confirm").hidden = true;
        state.confirmAction = null;
    }

    function initScrollReveal() {
        const targets = document.querySelectorAll(".reveal-on-scroll");
        if (!targets.length) return;
        const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduced || !("IntersectionObserver" in window)) {
            targets.forEach((el) => el.classList.add("is-revealed"));
            return;
        }
        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-revealed");
                    obs.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1, rootMargin: "0px 0px -16px 0px" });
        targets.forEach((el) => observer.observe(el));
    }

    function bindEvents() {
        $("btn-lang-toggle").addEventListener("click", toggleLanguage);
        $("btn-theme-toggle").addEventListener("click", toggleTheme);

        $("btn-logo").addEventListener("click", () => {
            if (state.screen === "landing") {
                window.scrollTo({ top: 0, behavior: "smooth" });
                return;
            }
            if (state.screen === "analyzing") return;
            if (state.screen === "quiz") {
                pauseTimer();
                saveQuizProgress(true);
            } else {
                state.returnScreen = state.screen;
            }
            showScreen("landing");
        });

        $("btn-start-quiz").addEventListener("click", handleStartAction);
        const bottomStartBtn = $("btn-bottom-start");
        if (bottomStartBtn) bottomStartBtn.addEventListener("click", handleStartAction);
        const explorerTabs = $("explorer-tabs");
        if (explorerTabs) {
            explorerTabs.addEventListener("click", (e) => {
                const tab = e.target.closest("[data-domain-tab]");
                if (!tab) return;
                state.activeDomainTab = tab.dataset.domainTab;
                renderDomainExplorer();
            });
        }
        $("btn-header-start").addEventListener("click", handleStartAction);
        $("btn-header-restart").addEventListener("click", () => {
            const inQuiz = state.screen === "quiz";
            openConfirmModal({
                title: inQuiz ? t("confirm_restart_quiz_title") : t("confirm_restart_done_title"),
                message: inQuiz ? t("confirm_restart_quiz_body") : t("confirm_restart_done_body"),
                confirmText: t("confirm_restart_ok"),
                cancelText: t("confirm_cancel"),
                onConfirm: () => beginQuiz(true)
            });
        });
        $("btn-print-result").addEventListener("click", () => window.print());

        $("quiz-options").addEventListener("click", (e) => {
            const btn = e.target.closest("[data-opt]");
            if (!btn || btn.classList.contains("is-locked")) return;
            state.draftOption = Number(btn.dataset.opt);
            renderQuestion({ resetQuestionTimer: false });
            saveQuizProgress(false);
        });

        $("hero-demo-options").addEventListener("click", (e) => {
            const btn = e.target.closest("[data-demo-opt]");
            if (!btn) return;
            state.demoChoice = Number(btn.dataset.demoOpt);
            renderHeroDemo();
        });
        $("btn-demo-reset").addEventListener("click", () => {
            state.demoChoice = null;
            renderHeroDemo();
        });

        $("btn-prev").addEventListener("click", () => {
            if (state.currentIndex > 0) {
                state.currentIndex -= 1;
                state.draftOption = null;
                renderQuestion({ resetQuestionTimer: true, animate: true });
                saveQuizProgress(false);
            }
        });
        $("btn-next").addEventListener("click", handleNextQuestion);

        $("btn-confirm-cancel").addEventListener("click", closeConfirmModal);
        $("btn-confirm-ok").addEventListener("click", () => {
            const action = state.confirmAction;
            closeConfirmModal();
            if (typeof action === "function") action();
        });
        $("modal-confirm").addEventListener("click", (e) => {
            if (e.target.id === "modal-confirm") closeConfirmModal();
        });

        document.querySelectorAll("[data-doc]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const docKey = btn.dataset.doc;
                if (docKey !== "terms" && docKey !== "privacy") return;
                $("info-title").textContent = t(`legal_${docKey}_title`);
                $("info-body").textContent = t(`legal_${docKey}_body`);
                $("modal-info").hidden = false;
            });
        });
        $("btn-info-close").addEventListener("click", () => { $("modal-info").hidden = true; });
        $("modal-info").addEventListener("click", (e) => {
            if (e.target.id === "modal-info") $("modal-info").hidden = true;
        });

        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                closeConfirmModal();
                $("modal-info").hidden = true;
                return;
            }
            handleQuizKeydown(e);
        });

        $("input-email").addEventListener("input", () => {
            $("email-error").hidden = true;
        });

        $("email-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const errEl = $("email-error");
            const submitBtn = $("btn-email-submit");
            const email = $("input-email").value.trim().toLowerCase();
            const consent = $("input-consent").checked;
            errEl.hidden = true;

            if (email.length > 254 || !EMAIL_RE.test(email)) {
                errEl.textContent = t("err_email_invalid");
                errEl.hidden = false;
                return;
            }
            if (!consent) {
                errEl.textContent = t("err_consent");
                errEl.hidden = false;
                return;
            }
            submitBtn.disabled = true;
            try {
                await apiFetch("/api/quiz/email", "POST", { email, consent });
                state.hasEmail = true;
                openPaywall();
            } catch (err) {
                errEl.textContent = err.message;
                errEl.hidden = false;
            } finally {
                submitBtn.disabled = false;
            }
        });

        $("paywall-plans").addEventListener("click", (e) => {
            const card = e.target.closest("[data-plan]");
            if (!card) return;
            state.selectedPlanId = card.dataset.plan;
            renderPlans();
        });
        $("btn-open-checkout").addEventListener("click", openCheckout);
        $("btn-back-paywall").addEventListener("click", () => {
            trackEvent("checkout_cancel");
            openPaywall();
        });

        $("checkout-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const errEl = $("checkout-error");
            const submitBtn = $("btn-pay-submit");
            const card = $("card-number").value.replace(/\s+/g, "");
            const exp = $("card-exp").value.trim();
            const cvc = $("card-cvc").value.trim();
            errEl.hidden = true;

            if (card.length < 12 || exp.length < 4 || cvc.length < 3) {
                errEl.textContent = t("err_card");
                errEl.hidden = false;
                return;
            }
            submitBtn.disabled = true;
            try {
                const res = await apiFetch("/api/checkout/pay", "POST", { plan: state.selectedPlanId });
                state.paymentStatus = "paid";
                state.returnScreen = "result";
                state.result = res.result;
                renderResult(true);
                showScreen("result");
            } catch (err) {
                errEl.textContent = err.message;
                errEl.hidden = false;
            } finally {
                submitBtn.disabled = false;
            }
        });

        $("review-filters").addEventListener("click", (e) => {
            const btn = e.target.closest("[data-filter]");
            if (!btn) return;
            state.reviewFilter = btn.dataset.filter;
            document.querySelectorAll("#review-filters .filter-btn").forEach((el) => {
                el.classList.toggle("is-active", el === btn);
            });
            renderReviewList();
        });

        window.addEventListener("pagehide", () => {
            if (state.quizActive) {
                saveQuizProgress(state.screen === "landing");
            }
        });
    }

    async function initApp() {
        initLanguage();
        initTheme();
        bindEvents();
        initScrollReveal();
        try {
            const data = await apiFetch("/api/session/state");
            state.plans = data.plans || [ ];
            state.totalQuestions = data.total_questions || 15;
            updateDynamicFaq();

            if (!data.has_session) {
                state.sessionStatus = "none";
                state.quizActive = false;
                clearQuizProgress();
                apiFetch("/api/session/visit", "POST", { }).catch(() => { });
                showScreen("landing");
                return;
            }
            if (data.payment_status === "paid" && data.result) {
                state.sessionStatus = "completed";
                state.paymentStatus = "paid";
                state.hasEmail = Boolean(data.has_email);
                state.quizActive = false;
                clearQuizProgress();
                state.result = data.result;
                renderResult(true);
                showScreen("result");
                return;
            }
            if (data.status === "completed") {
                state.sessionStatus = "completed";
                state.paymentStatus = data.payment_status || "unpaid";
                state.hasEmail = Boolean(data.has_email);
                state.quizActive = false;
                clearQuizProgress();
                if (!data.has_email) showScreen("email");
                else openPaywall();
                return;
            }

            state.sessionStatus = "started";
            state.questions = data.questions || [ ];
            state.answered = data.answered || { };
            const answeredCount = Object.keys(state.answered).length;
            const saved = loadQuizProgress();
            const hasMatchingProgress = Boolean(saved && saved.answeredSig === getAnsweredSignature(state.answered));

            if (hasMatchingProgress) {
                if (answeredCount >= state.totalQuestions && !saved.pausedOnLanding) {
                    await finishQuizFlow();
                    return;
                }
                state.quizActive = true;
                state.currentIndex = Math.max(0, Math.min(state.questions.length - 1, Number(saved.currentIndex) || 0));
                state.draftOption = typeof saved.draftOption === "number" ? saved.draftOption : null;
                state.quizElapsedMs = Math.max(0, Number(saved.quizElapsedMs) || 0);
                state.questionElapsedMs = Math.max(0, Number(saved.questionElapsedMs) || 0);
                if (saved.pausedOnLanding) {
                    showScreen("landing");
                } else {
                    showScreen("quiz");
                    startTimer();
                    renderQuestion({ resetQuestionTimer: false });
                }
                return;
            }

            if (answeredCount > 0) {
                if (answeredCount >= state.totalQuestions) {
                    await finishQuizFlow();
                    return;
                }
                state.quizActive = true;
                state.currentIndex = findFirstUnanswered();
                state.quizElapsedMs = 0;
                state.questionElapsedMs = 0;
                showScreen("quiz");
                startTimer();
                renderQuestion({ resetQuestionTimer: true });
                saveQuizProgress(false);
                return;
            }

            state.quizActive = false;
            showScreen("landing");
        } catch (err) {
            console.error("[InitApp]", err);
            showScreen("landing");
            showToast(t("err_restore"), true);
        }
    }

    document.addEventListener("DOMContentLoaded", initApp);
})();