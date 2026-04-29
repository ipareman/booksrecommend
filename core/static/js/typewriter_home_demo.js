(function () {
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var searchShell = document.getElementById("search-shell");
  var searchInput = document.getElementById("main-search-input");
  var typedPlaceholder = document.getElementById("typed-placeholder");
  var dialogToggle = document.getElementById("dialog-toggle");
  var aiModeChoice = document.getElementById("ai-mode-choice");
  var dialogPanel = document.getElementById("dialog-panel");
  var dialogClose = document.getElementById("dialog-close");
  var dialogInput = document.getElementById("dialog-input");
  var dialogThread = document.getElementById("dialog-thread");
  var dialogSend = document.getElementById("dialog-send");
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
    "роман о выборе и памяти",
    "что читать после выгорания",
    "закрытый мир и длинный сюжет",
    "короткая проза с тихим светом"
  ];

  document.querySelectorAll("form[action='#']").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
    });
  });

  var phraseIndex = 0;
  var typingTimer = null;
  var dialogExitTimer = null;
  var dialogEnterTimer = null;
  var dialogLeaveTimer = null;
  var dialogReturnTimer = null;
  var navLogoTimer = null;
  var navLogoFlight = null;
  var navLogoAnimation = null;
  var navLogoVisible = false;
  var navLogoScrollTicking = false;
  var inputActive = false;

  function wait(ms) {
    return new Promise(function (resolve) {
      typingTimer = window.setTimeout(resolve, ms);
    });
  }

  function shouldShowGhost() {
    return !inputActive && !searchInput.value && !searchShell.classList.contains("is-dialog");
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
        await wait(2600);
        for (var j = phrase.length; j >= 0; j--) {
          if (!shouldShowGhost()) break;
          typedPlaceholder.textContent = phrase.slice(0, j);
          await wait(24);
        }
      } else {
        typedPlaceholder.classList.add("is-hidden");
        typedPlaceholder.textContent = "";
        await wait(500);
      }

      phraseIndex += 1;
      await wait(500);
    }
  }

  function refreshGhost() {
    if (!typedPlaceholder) return;
    typedPlaceholder.classList.toggle("is-hidden", !shouldShowGhost());
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

  function isDesktopInline() {
    return desktopInlineQuery && desktopInlineQuery.matches;
  }

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
      panel.element.classList.add("is-open");
      panel.element.setAttribute("aria-hidden", "false");
      panel.lines.forEach(function (line) {
        line.span.textContent = "";
      });

      for (var lineIndex = 0; lineIndex < panel.lines.length; lineIndex++) {
        var line = panel.lines[lineIndex];
        for (var charIndex = 0; charIndex <= line.text.length; charIndex++) {
          if (panel.token !== token) return;
          line.span.textContent = line.text.slice(0, charIndex);
          await typedWait(panel.speed);
        }
        await typedWait(panel.lineDelay);
      }
      return;
    }

    for (var eraseIndex = panel.lines.length - 1; eraseIndex >= 0; eraseIndex--) {
      var eraseLine = panel.lines[eraseIndex];
      var currentText = eraseLine.span.textContent || "";
      for (var eraseChar = currentText.length; eraseChar >= 0; eraseChar--) {
        if (panel.token !== token) return;
        eraseLine.span.textContent = currentText.slice(0, eraseChar);
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
  }

  setDesktopMode("ai");

  function clearNavLogoFlight() {
    if (navLogoTimer) {
      window.clearTimeout(navLogoTimer);
      navLogoTimer = null;
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
    if (!heroMark || reducedMotion) {
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
      if (navLogoTimer) {
        window.clearTimeout(navLogoTimer);
        navLogoTimer = null;
      }
      if (navLogoFlight) {
        navLogoFlight.remove();
        navLogoFlight = null;
      }
      navLogoAnimation = null;
      document.body.classList.remove("nav-logo-flying");
      document.body.classList.toggle("nav-logo-visible", show);
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
      {
        duration: 620,
        easing: "cubic-bezier(.2, .72, .18, 1)",
        fill: "forwards"
      }
    );
    navLogoAnimation.onfinish = finishFlight;
    navLogoTimer = window.setTimeout(finishFlight, 760);
  }

  function updateNavLogoFromScroll() {
    if (!typewriterNavLogo || !topScreen || !heroMark) return;
    if (!navLogoVisible && window.scrollY > 10) {
      setNavLogoVisible(true);
    } else if (navLogoVisible && window.scrollY <= 1) {
      setNavLogoVisible(false);
    }
  }

  function requestNavLogoScrollUpdate() {
    if (navLogoScrollTicking) return;
    navLogoScrollTicking = true;
    window.requestAnimationFrame(function () {
      navLogoScrollTicking = false;
      updateNavLogoFromScroll();
    });
  }

  function isMobileDialog() {
    return mobileDialogQuery && mobileDialogQuery.matches && !reducedMotion;
  }

  function clearDialogTimers() {
    if (dialogExitTimer) {
      window.clearTimeout(dialogExitTimer);
      dialogExitTimer = null;
    }
    if (dialogEnterTimer) {
      window.clearTimeout(dialogEnterTimer);
      dialogEnterTimer = null;
    }
    if (dialogLeaveTimer) {
      window.clearTimeout(dialogLeaveTimer);
      dialogLeaveTimer = null;
    }
    if (dialogReturnTimer) {
      window.clearTimeout(dialogReturnTimer);
      dialogReturnTimer = null;
    }
  }

  function setDialogState(open) {
    searchShell.classList.toggle("is-dialog", open);
    document.body.classList.toggle("dialog-open", open);
    dialogPanel.setAttribute("aria-hidden", open ? "false" : "true");
    if (dialogToggle) {
      dialogToggle.classList.toggle("is-active", open);
      dialogToggle.setAttribute("aria-pressed", open ? "true" : "false");
    }
    setDesktopMode(open ? "dialog" : "ai");
    refreshGhost();
  }

  function setDialog(open) {
    var isOpening = document.body.classList.contains("dialog-exiting");
    var willOpen = typeof open === "boolean" ? open : !(searchShell.classList.contains("is-dialog") || isOpening);
    clearDialogTimers();

    if (!willOpen) {
      if (isMobileDialog() && searchShell.classList.contains("is-dialog")) {
        document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-returning");
        document.body.classList.add("dialog-leaving");

        dialogLeaveTimer = window.setTimeout(function () {
          dialogLeaveTimer = null;
          document.body.classList.remove("dialog-leaving");
          setDialogState(false);
          document.body.classList.add("dialog-returning");

          dialogReturnTimer = window.setTimeout(function () {
            dialogReturnTimer = null;
            document.body.classList.remove("dialog-returning");
          }, 520);
        }, 520);
        return;
      }

      document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-leaving", "dialog-returning");
      setDialogState(false);
      return;
    }

    if (willOpen && aiModeChoice) {
      aiModeChoice.classList.remove("is-active");
      aiModeChoice.setAttribute("aria-pressed", "false");
    }

    closeModals();

    if (isMobileDialog()) {
      document.body.classList.remove("dialog-leaving", "dialog-returning");
      document.body.classList.add("dialog-exiting");
      if (dialogToggle) {
        dialogToggle.classList.add("is-active");
        dialogToggle.setAttribute("aria-pressed", "true");
      }
      refreshGhost();

      dialogExitTimer = window.setTimeout(function () {
        dialogExitTimer = null;
        document.body.classList.remove("dialog-exiting");
        document.body.classList.add("dialog-entering");
        setDialogState(true);

        dialogEnterTimer = window.setTimeout(function () {
          dialogEnterTimer = null;
          document.body.classList.remove("dialog-entering");
        }, 920);

        window.setTimeout(function () {
          dialogInput.focus();
        }, 520);
      }, 430);
      return;
    }

    setDialogState(true);
    window.setTimeout(function () {
      dialogInput.focus();
    }, 260);
  }

  if (mobileDialogQuery && mobileDialogQuery.addEventListener) {
    mobileDialogQuery.addEventListener("change", function () {
      if (!mobileDialogQuery.matches && document.body.classList.contains("dialog-exiting")) {
        clearDialogTimers();
        document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-leaving", "dialog-returning");
        setDialogState(true);
      }
    });
  } else if (mobileDialogQuery && mobileDialogQuery.addListener) {
    mobileDialogQuery.addListener(function () {
      if (!mobileDialogQuery.matches && document.body.classList.contains("dialog-exiting")) {
        clearDialogTimers();
        document.body.classList.remove("dialog-exiting", "dialog-entering", "dialog-leaving", "dialog-returning");
        setDialogState(true);
      }
    });
  }

  if (dialogToggle) {
    dialogToggle.addEventListener("click", function () {
      setDialog();
    });
  }

  if (dialogClose) {
    dialogClose.addEventListener("click", function () {
      setDialog(false);
    });
  }

  if (aiModeChoice) {
    aiModeChoice.setAttribute("aria-pressed", "false");
    aiModeChoice.addEventListener("click", function () {
      var willActivate = !aiModeChoice.classList.contains("is-active");
      aiModeChoice.classList.toggle("is-active", willActivate);
      aiModeChoice.setAttribute("aria-pressed", willActivate ? "true" : "false");
      if (willActivate) {
        setDialog(false);
        setDesktopMode("ai");
      }
    });
  }

  if (desktopAiMode) {
    desktopAiMode.addEventListener("click", function () {
      setDialog(false);
      setDesktopMode("ai");
    });
  }

  if (desktopDialogMode) {
    desktopDialogMode.addEventListener("click", function () {
      setDialog(true);
      setDesktopMode("dialog");
    });
  }

  if (desktopHistoryPanel) {
    desktopHistoryPanel.querySelectorAll("[data-typewrite]").forEach(function (button) {
      button.addEventListener("click", function () {
        searchInput.value = button.getAttribute("data-typewrite") || "";
        refreshGhost();
        searchInput.focus();
      });
    });
  }

  if (dialogSend) dialogSend.addEventListener("click", function () {
    var text = dialogInput.value.trim();
    if (!text) return;

    var userMessage = document.createElement("p");
    var userRow = document.createElement("div");
    userRow.className = "message-row message-row--user";
    var userAvatar = document.createElement("div");
    userAvatar.className = "message-avatar";
    userAvatar.textContent = "Я";
    var userStack = document.createElement("div");
    userStack.className = "message-stack";
    userMessage.className = "message message--user";
    userMessage.textContent = text;
    userStack.appendChild(userMessage);
    userRow.appendChild(userAvatar);
    userRow.appendChild(userStack);
    dialogThread.appendChild(userRow);

    var assistantRow = document.createElement("div");
    assistantRow.className = "message-row message-row--assistant";
    var assistantAvatar = document.createElement("div");
    assistantAvatar.className = "message-avatar";
    assistantAvatar.textContent = "AI";
    var assistantStack = document.createElement("div");
    assistantStack.className = "message-stack";
    var assistantMessage = document.createElement("p");
    assistantMessage.className = "message message--assistant";
    assistantMessage.textContent = "Для такого запроса я бы показал 3 направления: спокойный сюжет, камерную прозу и книгу с мягким юмором.";
    assistantStack.appendChild(assistantMessage);
    assistantRow.appendChild(assistantAvatar);
    assistantRow.appendChild(assistantStack);
    dialogThread.appendChild(assistantRow);

    dialogInput.value = "";
    dialogThread.scrollTop = dialogThread.scrollHeight;
  });

  document.querySelectorAll("[data-open-modal]").forEach(function (button) {
    button.addEventListener("click", function () {
      var modalId = button.getAttribute("data-open-modal");
      if (isDesktopInline() && modalId === "settings-modal") {
        if (searchShell.classList.contains("is-dialog")) {
          setDialog(false);
          window.setTimeout(function () {
            if (!typedPanels.settings || typedPanels.settings.isOpen) return;
            animateTypedPanel("settings", true);
          }, 360);
          return;
        }
        toggleTypedPanel("settings");
        return;
      }
      if (isDesktopInline() && modalId === "history-modal") {
        if (searchShell.classList.contains("is-dialog")) {
          setDialog(false);
          window.setTimeout(function () {
            if (!typedPanels.history || typedPanels.history.isOpen) return;
            animateTypedPanel("history", true);
          }, 360);
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
    if (event.key === "Escape") closeModals();
  });

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

    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: .12, rootMargin: "0px 0px -60px 0px" });

    document.querySelectorAll(".reveal-block").forEach(function (block) {
      revealObserver.observe(block);
    });
  } else {
    document.querySelectorAll(".reveal-block").forEach(function (block) {
      block.classList.add("is-visible");
    });
  }

  if (typewriterNavLogo && topScreen && heroMark) {
    updateNavLogoFromScroll();
    window.addEventListener("scroll", requestNavLogoScrollUpdate, { passive: true });
    window.addEventListener("resize", requestNavLogoScrollUpdate);
  }

  if (scrollCue) scrollCue.addEventListener("click", function () {
    if (scrollCue.classList.contains("is-top-mode")) {
      topScreen.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    } else {
      homeStream.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    }
  });

  if (typewriterNavLogo && topScreen) {
    typewriterNavLogo.addEventListener("click", function (event) {
      var homeNav = typewriterNavLogo.closest(".typewriter-nav--home");
      if (!homeNav) return;
      event.preventDefault();
      topScreen.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    });
  }

  if (searchInput && typedPlaceholder) typeLoop();

  window.addEventListener("beforeunload", function () {
    if (typingTimer) window.clearTimeout(typingTimer);
  });
})();
