(function () {
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var searchShell = document.getElementById("search-shell");
  var standardSearchForm = document.getElementById("search-form");
  var aiSearchForm = document.getElementById("ai-search-form");
  var searchInput = document.getElementById("main-search-input") || document.getElementById("search-input");
  var aiSearchInput = document.getElementById("ai-search-input");
  var typedPlaceholder = document.getElementById("typed-placeholder");
  var dialogToggle = document.getElementById("dialog-toggle");
  var aiModeChoice = document.getElementById("ai-mode-choice");
  var dialogPanel = document.getElementById("dialog-panel");
  var dialogClose = document.getElementById("dialog-close");
  var dialogInput = document.getElementById("dialog-input");
  var dialogThread = document.getElementById("discovery-messages") || document.getElementById("dialog-thread");
  var scrollCue = document.getElementById("scroll-cue");
  var topScreen = document.getElementById("top-screen");
  var homeStream = document.getElementById("home-stream");
  var typewriterNavLogo = document.getElementById("typewriter-nav-logo");
  var heroMark = document.querySelector(".hero-mark");
  var mobileDialogQuery = window.matchMedia ? window.matchMedia("(max-width: 680px)") : null;
  var desktopInlineQuery = window.matchMedia ? window.matchMedia("(min-width: 681px)") : null;
  var settingsTrigger = document.getElementById("settings-trigger");
  var historyTrigger = document.getElementById("history-trigger");
  var desktopSettingsPanel = document.getElementById("desktop-settings-panel");
  var desktopHistoryPanel = document.getElementById("desktop-history-panel");
  var desktopAiMode = document.getElementById("desktop-ai-mode");
  var desktopDialogMode = document.getElementById("desktop-dialog-mode");

  var phrases = [
    "книга после тяжёлой недели",
    "короткая проза с тихим светом",
    "роман о выборе и памяти",
    "закрытый мир и длинный сюжет",
    "что читать после выгорания"
  ];

  var typingTimer = null;
  var phraseIndex = 0;
  var inputActive = false;
  var dialogExitTimer = null;
  var dialogEnterTimer = null;
  var dialogLeaveTimer = null;
  var dialogReturnTimer = null;
  var navLogoVisible = false;
  var navLogoFlight = null;
  var navLogoAnimation = null;
  var navLogoTimer = null;
  var navLogoCleanupTimer = null;
  var navLogoCleanupFlight = null;
  var navLogoTicking = false;
  var navLogoReady = false;

  function wait(ms) {
    return new Promise(function (resolve) {
      typingTimer = window.setTimeout(resolve, ms);
    });
  }

  function isDesktopInline() {
    return desktopInlineQuery && desktopInlineQuery.matches;
  }

  function isMobileDialog() {
    return mobileDialogQuery && mobileDialogQuery.matches && !reducedMotion;
  }

  function activeInput() {
    return searchShell && searchShell.classList.contains("is-ai") ? aiSearchInput : searchInput;
  }

  function shouldShowGhost() {
    return Boolean(searchInput && typedPlaceholder && !inputActive && !searchInput.value && !searchShell.classList.contains("is-dialog") && !searchShell.classList.contains("is-ai"));
  }

  function refreshGhost() {
    if (!typedPlaceholder) return;
    typedPlaceholder.classList.toggle("is-hidden", !shouldShowGhost());
  }

  async function typeLoop() {
    if (!typedPlaceholder || reducedMotion) {
      if (typedPlaceholder) typedPlaceholder.textContent = phrases[0];
      return;
    }

    while (true) {
      var phrase = phrases[phraseIndex % phrases.length];
      if (shouldShowGhost()) {
        typedPlaceholder.classList.remove("is-hidden");
        for (var i = 0; i <= phrase.length; i++) {
          if (!shouldShowGhost()) break;
          typedPlaceholder.textContent = phrase.slice(0, i);
          await wait(44);
        }
        await wait(2300);
        for (var j = phrase.length; j >= 0; j--) {
          if (!shouldShowGhost()) break;
          typedPlaceholder.textContent = phrase.slice(0, j);
          await wait(24);
        }
      } else {
        typedPlaceholder.classList.add("is-hidden");
        typedPlaceholder.textContent = "";
        await wait(520);
      }
      phraseIndex += 1;
      await wait(420);
    }
  }

  if (searchInput) {
    searchInput.addEventListener("focus", function () {
      inputActive = true;
      refreshGhost();
    });
    searchInput.addEventListener("blur", function () {
      inputActive = false;
      refreshGhost();
    });
    searchInput.addEventListener("input", refreshGhost);
  }

  function rememberQuery(text) {
    text = (text || "").trim();
    if (!text) return;
    try {
      var key = "stroka.localSearchHistory";
      var existing = JSON.parse(localStorage.getItem(key) || "[]");
      var next = [text].concat(existing.filter(function (item) {
        return String(item).toLowerCase() !== text.toLowerCase();
      })).slice(0, 15);
      localStorage.setItem(key, JSON.stringify(next));
      renderLocalHistory();
    } catch (e) {}
  }

  function getLocalHistory() {
    try {
      return JSON.parse(localStorage.getItem("stroka.localSearchHistory") || "[]").filter(Boolean).slice(0, 15);
    } catch (e) {
      return [];
    }
  }

  function fillSearchFromHistory(query) {
    setDialog(false);
    setSearchMode("standard");
    closeModals();
    if (!searchInput) return;
    searchInput.value = query;
    refreshGhost();
    searchInput.focus();
    if (window.htmx) window.htmx.trigger(searchInput, "search");
  }

  function renderLocalHistory() {
    var history = getLocalHistory();
    [
      document.querySelector("[data-local-history]"),
      document.querySelector("[data-local-history-mobile]")
    ].forEach(function (host) {
      if (!host || !history.length) return;
      host.innerHTML = "";
      history.forEach(function (query) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = query;
        btn.setAttribute("data-history-query", query);
        if (host.hasAttribute("data-local-history")) {
          btn.setAttribute("data-typewrite", query);
          var span = document.createElement("span");
          span.textContent = query;
          btn.textContent = "";
          btn.appendChild(span);
        }
        host.appendChild(btn);
      });
    });
  }

  function typeAutocomplete(root) {
    if (!root || reducedMotion) return;
    (root._autotypeTimers || []).forEach(function (timer) {
      window.clearTimeout(timer);
      window.clearInterval(timer);
    });
    root._autotypeTimers = [];
    var nodes = Array.prototype.slice.call(root.querySelectorAll("[data-autotype]"));
    nodes.forEach(function (node) {
      node.setAttribute("data-autotype-full", (node.textContent || "").trim());
      node.textContent = "";
    });
    nodes.forEach(function (node, index) {
      var text = node.getAttribute("data-autotype-full") || "";
      var delayTimer = window.setTimeout(function () {
        var i = 0;
        var timer = window.setInterval(function () {
          node.textContent = text.slice(0, i);
          i += 1;
          if (i > text.length) window.clearInterval(timer);
        }, 12);
        root._autotypeTimers.push(timer);
      }, index * 34);
      root._autotypeTimers.push(delayTimer);
    });
  }

  function catalogSearchUrl(query) {
    if (!standardSearchForm) return "";
    var base = standardSearchForm.getAttribute("data-catalog-url") || standardSearchForm.action || "/books/";
    var separator = base.indexOf("?") === -1 ? "?" : "&";
    return base + separator + "search=" + encodeURIComponent((query || "").trim());
  }

  function goToCatalogSearch(query) {
    query = (query || "").trim();
    if (!query) return;
    rememberQuery(query);
    window.location.href = catalogSearchUrl(query);
  }

  function initAutocomplete() {
    var dropdown = document.getElementById("autocomplete-dropdown");
    if (!searchInput || !dropdown) return;
    var url = dropdown.getAttribute("data-autocomplete-url") || dropdown.getAttribute("hx-get");
    if (!url || !window.fetch) return;

    var timer = null;
    var controller = null;
    var lastQuery = "";

    function clearDropdown() {
      dropdown.innerHTML = "";
      lastQuery = "";
    }

    function loadSuggestions() {
      var query = (searchInput.value || "").trim();
      if (query.length < 2) {
        clearDropdown();
        return;
      }
      if (query === lastQuery) return;
      lastQuery = query;
      if (controller) controller.abort();
      controller = new AbortController();
      fetch(url + "?q=" + encodeURIComponent(query), {
        credentials: "same-origin",
        signal: controller.signal
      })
        .then(function (response) {
          if (!response.ok) throw new Error("autocomplete");
          return response.text();
        })
        .then(function (html) {
          if ((searchInput.value || "").trim() !== query) return;
          dropdown.innerHTML = html;
          typeAutocomplete(dropdown);
        })
        .catch(function (error) {
          if (error && error.name === "AbortError") return;
          clearDropdown();
        });
    }

    searchInput.addEventListener("input", function () {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(loadSuggestions, 180);
    });
    searchInput.addEventListener("search", loadSuggestions);
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") clearDropdown();
    });
    document.addEventListener("click", function (event) {
      if (event.target.closest("#search-shell") || event.target.closest("#autocomplete-dropdown")) return;
      clearDropdown();
    });
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.id === "autocomplete-dropdown") typeAutocomplete(event.target);
  });

  if (standardSearchForm) {
    standardSearchForm.addEventListener("submit", function (event) {
      var query = searchInput && searchInput.value;
      if ((query || "").trim()) {
        event.preventDefault();
        goToCatalogSearch(query);
        return;
      }
      rememberQuery(query);
    });
  }

  if (aiSearchForm) {
    aiSearchForm.addEventListener("submit", function () {
      rememberQuery(aiSearchInput && aiSearchInput.value);
    });
  }

  document.addEventListener("click", function (event) {
    var historyButton = event.target.closest("[data-history-query], [data-typewrite]");
    if (historyButton && !historyButton.classList.contains("desktop-mode")) {
      var query = historyButton.getAttribute("data-history-query") || historyButton.getAttribute("data-typewrite");
      if (query && !historyButton.hasAttribute("data-local-history-empty")) fillSearchFromHistory(query);
    }

    var chip = event.target.closest(".disc-chip");
    if (chip && dialogInput) {
      var prompt = chip.getAttribute("data-prompt");
      if (!prompt) return;
      dialogInput.value = prompt;
      chip.classList.add("active");
      window.setTimeout(function () { chip.classList.remove("active"); }, 900);
      var form = document.getElementById("discovery-form");
      if (form) {
        rememberQuery(prompt);
        if (window.htmx) window.htmx.trigger(form, "submit");
        else form.requestSubmit();
      }
    }
  });

  function makeTypedPanel(element, trigger, speed, eraseSpeed, lineDelay) {
    if (!element) return null;
    return {
      element: element,
      trigger: trigger,
      speed: speed,
      eraseSpeed: eraseSpeed,
      lineDelay: lineDelay,
      isOpen: false,
      token: 0,
      lines: Array.prototype.slice.call(element.querySelectorAll("[data-typewrite]")).map(function (button) {
        return {
          button: button,
          span: button.querySelector("span") || button,
          text: button.getAttribute("data-typewrite") || ""
        };
      })
    };
  }

  var typedPanels = {
    settings: makeTypedPanel(desktopSettingsPanel, settingsTrigger, 28, 15, 80),
    history: makeTypedPanel(desktopHistoryPanel, historyTrigger, 8, 5, 18)
  };

  function typedWait(ms) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, ms);
    });
  }

  function setTriggerExpanded(trigger, open) {
    if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  async function animateTypedPanel(name, open) {
    var panel = typedPanels[name];
    if (!panel) return;

    var token = panel.token + 1;
    panel.token = token;
    panel.isOpen = open;
    setTriggerExpanded(panel.trigger, open);

    if (open) {
      panel.lines = Array.prototype.slice.call(panel.element.querySelectorAll("[data-typewrite]")).map(function (button) {
        return { button: button, span: button.querySelector("span") || button, text: button.getAttribute("data-typewrite") || "" };
      });
      panel.element.classList.add("is-open");
      panel.element.setAttribute("aria-hidden", "false");
      panel.lines.forEach(function (line) { line.span.textContent = ""; });

      for (var i = 0; i < panel.lines.length; i++) {
        var line = panel.lines[i];
        for (var c = 0; c <= line.text.length; c++) {
          if (panel.token !== token) return;
          line.span.textContent = line.text.slice(0, c);
          await typedWait(panel.speed);
        }
        await typedWait(panel.lineDelay);
      }
      return;
    }

    for (var j = panel.lines.length - 1; j >= 0; j--) {
      var eraseLine = panel.lines[j];
      var currentText = eraseLine.span.textContent || "";
      for (var e = currentText.length; e >= 0; e--) {
        if (panel.token !== token) return;
        eraseLine.span.textContent = currentText.slice(0, e);
        await typedWait(panel.eraseSpeed);
      }
    }

    if (panel.token === token) {
      panel.element.classList.remove("is-open");
      panel.element.setAttribute("aria-hidden", "true");
    }
  }

  function toggleTypedPanel(name) {
    var panel = typedPanels[name];
    if (!panel) return;
    animateTypedPanel(name, !panel.isOpen);
  }

  function setDesktopMode(mode) {
    if (desktopAiMode) desktopAiMode.classList.toggle("is-active", mode === "ai");
    if (desktopDialogMode) desktopDialogMode.classList.toggle("is-active", mode === "dialog");
    if (desktopAiMode) desktopAiMode.setAttribute("aria-pressed", mode === "ai" ? "true" : "false");
    if (desktopDialogMode) desktopDialogMode.setAttribute("aria-pressed", mode === "dialog" ? "true" : "false");
    if (aiModeChoice) {
      aiModeChoice.classList.toggle("is-active", mode === "ai");
      aiModeChoice.setAttribute("aria-pressed", mode === "ai" ? "true" : "false");
    }
    if (dialogToggle) {
      dialogToggle.classList.toggle("is-active", mode === "dialog");
      dialogToggle.setAttribute("aria-pressed", mode === "dialog" ? "true" : "false");
    }
  }

  function setSearchMode(mode) {
    if (!searchShell) return;
    searchShell.classList.toggle("is-ai", mode === "ai");
    refreshGhost();
    setDesktopMode(mode === "ai" ? "ai" : "standard");
    var input = activeInput();
    if (input) window.setTimeout(function () { input.focus(); }, 80);
  }

  function clearDialogTimers() {
    [dialogExitTimer, dialogEnterTimer, dialogLeaveTimer, dialogReturnTimer].forEach(function (timer) {
      if (timer) window.clearTimeout(timer);
    });
    dialogExitTimer = dialogEnterTimer = dialogLeaveTimer = dialogReturnTimer = null;
  }

  function setDialogState(open) {
    if (!searchShell || !dialogPanel) return;
    searchShell.classList.toggle("is-dialog", open);
    document.body.classList.toggle("dialog-open", open);
    dialogPanel.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) searchShell.classList.remove("is-ai");
    setDesktopMode(open ? "dialog" : (searchShell.classList.contains("is-ai") ? "ai" : "standard"));
    refreshGhost();
    if (open && dialogThread) window.setTimeout(function () {
      dialogThread.scrollTop = dialogThread.scrollHeight;
    }, 40);
  }

  function setDialog(open) {
    if (!searchShell || !dialogPanel) return;
    var isOpening = document.body.classList.contains("dialog-exiting");
    var willOpen = typeof open === "boolean" ? open : !(searchShell.classList.contains("is-dialog") || isOpening);
    clearDialogTimers();

    if (!willOpen) {
      if (isMobileDialog() && searchShell.classList.contains("is-dialog")) {
        document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-returning");
        document.body.classList.add("dialog-leaving");
        dialogLeaveTimer = window.setTimeout(function () {
          document.body.classList.remove("dialog-leaving");
          setDialogState(false);
          document.body.classList.add("dialog-returning");
          dialogReturnTimer = window.setTimeout(function () {
            document.body.classList.remove("dialog-returning");
          }, 520);
        }, 420);
        return;
      }
      document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-leaving", "dialog-returning");
      setDialogState(false);
      return;
    }

    closeModals();

    if (isMobileDialog()) {
      document.body.classList.remove("dialog-leaving", "dialog-returning");
      document.body.classList.add("dialog-exiting");
      setDesktopMode("dialog");
      dialogExitTimer = window.setTimeout(function () {
        document.body.classList.remove("dialog-exiting");
        document.body.classList.add("dialog-entering");
        setDialogState(true);
        dialogEnterTimer = window.setTimeout(function () {
          document.body.classList.remove("dialog-entering");
        }, 920);
        if (dialogInput) window.setTimeout(function () { dialogInput.focus(); }, 460);
      }, 430);
      return;
    }

    setDialogState(true);
    if (dialogInput) window.setTimeout(function () { dialogInput.focus(); }, 240);
  }

  if (dialogToggle) dialogToggle.addEventListener("click", function () { setDialog(); });
  if (dialogClose) dialogClose.addEventListener("click", function () { setDialog(false); });
  if (aiModeChoice) aiModeChoice.addEventListener("click", function () {
    setDialog(false);
    setSearchMode("ai");
  });
  if (desktopAiMode) desktopAiMode.addEventListener("click", function () {
    setDialog(false);
    setSearchMode("ai");
  });
  if (desktopDialogMode) desktopDialogMode.addEventListener("click", function () {
    setDialog(true);
  });

  document.querySelectorAll("[data-open-modal]").forEach(function (button) {
    button.addEventListener("click", function () {
      var modalId = button.getAttribute("data-open-modal");
      if (isDesktopInline() && modalId === "settings-modal") {
        if (searchShell && searchShell.classList.contains("is-dialog")) {
          setDialog(false);
          window.setTimeout(function () { animateTypedPanel("settings", true); }, 360);
          return;
        }
        toggleTypedPanel("settings");
        return;
      }
      if (isDesktopInline() && modalId === "history-modal") {
        if (searchShell && searchShell.classList.contains("is-dialog")) {
          setDialog(false);
          window.setTimeout(function () { animateTypedPanel("history", true); }, 360);
          return;
        }
        toggleTypedPanel("history");
        return;
      }
      var modal = document.getElementById(modalId);
      if (!modal) return;
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
    });
  });

  function closeModals() {
    document.querySelectorAll(".modal.is-open").forEach(function (modal) {
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
    });
    document.body.classList.remove("modal-open");
  }

  document.querySelectorAll("[data-close-modal]").forEach(function (button) {
    button.addEventListener("click", closeModals);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeModals();
      setDialog(false);
    }
  });

  function clearNavLogoFlight() {
    if (navLogoTimer) window.clearTimeout(navLogoTimer);
    navLogoTimer = null;
    if (navLogoCleanupTimer) window.clearTimeout(navLogoCleanupTimer);
    navLogoCleanupTimer = null;
    if (navLogoCleanupFlight) {
      navLogoCleanupFlight.remove();
      navLogoCleanupFlight = null;
    }
    if (navLogoAnimation) {
      navLogoAnimation.onfinish = null;
      navLogoAnimation.cancel();
      navLogoAnimation = null;
    }
    if (navLogoFlight) {
      navLogoFlight.remove();
      navLogoFlight = null;
    }
  }

  function setNavLogoVisible(show) {
    if (!typewriterNavLogo || navLogoVisible === show) return;
    if (!heroMark || reducedMotion || !navLogoReady) {
      navLogoVisible = show;
      document.body.classList.toggle("nav-logo-visible", show);
      return;
    }

    var logoImage = typewriterNavLogo.querySelector("img");
    if (!logoImage) return;

    var fromElement = show ? heroMark : typewriterNavLogo;
    var toElement = show ? typewriterNavLogo : heroMark;
    var fromRect = fromElement.getBoundingClientRect();
    var toRect = toElement.getBoundingClientRect();
    if (!fromRect.width || !fromRect.height || !toRect.width || !toRect.height) return;

    navLogoVisible = show;
    clearNavLogoFlight();

    navLogoFlight = document.createElement("div");
    navLogoFlight.className = "nav-logo-flight";
    navLogoFlight.style.left = fromRect.left + "px";
    navLogoFlight.style.top = fromRect.top + "px";
    navLogoFlight.style.width = fromRect.width + "px";
    navLogoFlight.style.height = fromRect.height + "px";
    navLogoFlight.appendChild(logoImage.cloneNode(true));
    document.body.appendChild(navLogoFlight);

    document.body.classList.add("nav-logo-flying");
    document.body.classList.remove("nav-logo-visible");

    var dx = toRect.left - fromRect.left;
    var dy = toRect.top - fromRect.top;
    var sx = toRect.width / fromRect.width;
    var sy = toRect.height / fromRect.height;

    function finishFlight() {
      if (navLogoTimer) window.clearTimeout(navLogoTimer);
      navLogoTimer = null;
      navLogoAnimation = null;
      document.body.classList.toggle("nav-logo-visible", show);
      document.body.classList.remove("nav-logo-flying");
      var finishedFlight = navLogoFlight;
      navLogoFlight = null;
      if (finishedFlight) {
        navLogoCleanupFlight = finishedFlight;
        finishedFlight.style.transition = "opacity .16s ease";
        finishedFlight.style.opacity = "0";
      }
      navLogoCleanupTimer = window.setTimeout(function () {
        navLogoCleanupTimer = null;
        if (navLogoCleanupFlight) {
          navLogoCleanupFlight.remove();
          navLogoCleanupFlight = null;
        }
      }, 180);
    }

    if (!navLogoFlight.animate) {
      finishFlight();
      return;
    }

    navLogoAnimation = navLogoFlight.animate(
      [
        { transform: "translate3d(0, 0, 0) scale(1, 1)" },
        { transform: "translate3d(" + dx + "px, " + dy + "px, 0) scale(" + sx + ", " + sy + ")" }
      ],
      { duration: 620, easing: "cubic-bezier(.2,.72,.18,1)", fill: "forwards" }
    );
    navLogoAnimation.onfinish = finishFlight;
    navLogoTimer = window.setTimeout(finishFlight, 760);
  }

  function updateNavLogoFromScroll() {
    if (!typewriterNavLogo || !topScreen || !heroMark) return;
    if (!navLogoVisible && window.scrollY > 10) setNavLogoVisible(true);
    else if (navLogoVisible && window.scrollY <= 1) setNavLogoVisible(false);
  }

  function requestNavLogoScrollUpdate() {
    if (navLogoTicking) return;
    navLogoTicking = true;
    window.requestAnimationFrame(function () {
      navLogoTicking = false;
      updateNavLogoFromScroll();
    });
  }

  function waitForImage(img) {
    return new Promise(function (resolve) {
      if (!img || img.complete) {
        resolve();
        return;
      }
      img.addEventListener("load", resolve, { once: true });
      img.addEventListener("error", resolve, { once: true });
    });
  }

  if (typewriterNavLogo && topScreen && heroMark) {
    Promise.all([
      waitForImage(typewriterNavLogo.querySelector("img")),
      waitForImage(heroMark)
    ]).then(function () {
      window.requestAnimationFrame(function () {
        navLogoReady = true;
        updateNavLogoFromScroll();
      });
    });
    window.addEventListener("scroll", requestNavLogoScrollUpdate, { passive: true });
    window.addEventListener("resize", requestNavLogoScrollUpdate);
  }

  if (typewriterNavLogo && topScreen) {
    typewriterNavLogo.addEventListener("click", function (event) {
      var homeNav = typewriterNavLogo.closest(".typewriter-nav--home, .tw-nav--home");
      if (!homeNav) return;
      event.preventDefault();
      topScreen.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    });
  }

  if ("IntersectionObserver" in window && topScreen) {
    var topObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var topMode = !entry.isIntersecting;
        if (scrollCue) {
          scrollCue.classList.toggle("is-top-mode", topMode);
          scrollCue.textContent = topMode ? "↑" : "↓";
          scrollCue.setAttribute("aria-label", topMode ? "Наверх" : "Промотать вниз");
        }
      });
    }, { threshold: .18 });
    topObserver.observe(topScreen);
  }

  if (scrollCue) scrollCue.addEventListener("click", function () {
    if (scrollCue.classList.contains("is-top-mode")) {
      topScreen.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    } else if (homeStream) {
      homeStream.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    }
  });

  function typeMobileLabels() {
    var sheet = document.querySelector(".typewriter-mobile-nav--open .typewriter-mobile-nav__sheet, .tw-mobile-nav--open .tw-mobile-nav__sheet");
    if (!sheet) return;
    var labels = Array.prototype.slice.call(sheet.querySelectorAll("[data-type-label]"));
    labels.forEach(function (label) {
      label.textContent = "";
    });
    labels.forEach(function (label, index) {
      var text = label.getAttribute("data-type-label") || "";
      window.setTimeout(function () {
        var i = 0;
        var timer = window.setInterval(function () {
          label.textContent = text.slice(0, i);
          i += 1;
          if (i > text.length) window.clearInterval(timer);
        }, 20);
      }, index * 45);
    });
  }

  var mobileButton = document.querySelector(".typewriter-mobile-trigger, .tw-nav__hamburger");
  if (mobileButton) {
    mobileButton.addEventListener("click", function () {
      window.setTimeout(typeMobileLabels, 70);
    });
  }

  function initVoiceInput() {
    var voiceBtn = document.getElementById("dialog-voice");
    if (!voiceBtn || !dialogInput) return;
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      voiceBtn.style.display = "none";
      return;
    }
    var recognition = null;
    var listening = false;
    voiceBtn.addEventListener("click", function () {
      if (listening && recognition) {
        recognition.stop();
        return;
      }
      recognition = new SpeechRecognition();
      recognition.lang = "ru-RU";
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.onstart = function () {
        listening = true;
        voiceBtn.classList.add("listening");
      };
      recognition.onresult = function (event) {
        var text = "";
        for (var i = event.resultIndex; i < event.results.length; i++) text += event.results[i][0].transcript;
        dialogInput.value = text;
      };
      recognition.onend = function () {
        listening = false;
        voiceBtn.classList.remove("listening");
      };
      recognition.onerror = function () {
        listening = false;
        voiceBtn.classList.remove("listening");
      };
      try { recognition.start(); } catch (e) {}
    });
  }

  renderLocalHistory();
  initAutocomplete();
  initVoiceInput();
  if (searchInput && typedPlaceholder && searchShell) typeLoop();
  window.addEventListener("beforeunload", function () {
    if (typingTimer) window.clearTimeout(typingTimer);
    clearNavLogoFlight();
  });
})();
