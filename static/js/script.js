/* CampusTrace - vanilla JavaScript only.
   Frontend validation and the mobile menu. The server always validates again,
   and stored secret answers are never included in public response data. */

(function () {
  "use strict";

  // Mobile navigation
  var toggle = document.getElementById("navToggle");
  var nav = document.getElementById("siteNav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      nav.classList.toggle("open");
    });
  }

  // Password and private-answer visibility controls
  var passwordInputs = document.querySelectorAll("[data-password-toggle]");
  Array.prototype.forEach.call(passwordInputs, function (input) {
    var wrapper = input.parentNode;
    var button = wrapper.querySelector(".visibility-toggle");
    if (!button) return;

    var showLabel = button.getAttribute("aria-label") || "Show password";
    var hideLabel = showLabel.replace(/^Show/, "Hide");
    var showIcon = button.querySelector("[data-icon-show]");
    var hideIcon = button.querySelector("[data-icon-hide]");
    button.addEventListener("click", function (event) {
      event.preventDefault();
      var isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      button.setAttribute("aria-label", isVisible ? showLabel : hideLabel);
      button.setAttribute("title", isVisible ? showLabel : hideLabel);
      showIcon.classList.toggle("icon-hidden", !isVisible);
      hideIcon.classList.toggle("icon-hidden", isVisible);
    });
  });

  // A custom category is required only while "Other" is selected.
  var categorySelect = document.getElementById("category");
  var customCategory = document.getElementById("custom_category");
  var customCategoryField = document.getElementById("customCategoryField");
  if (categorySelect && customCategory && customCategoryField) {
    function updateCustomCategory() {
      var isOther = categorySelect.value === "Other";
      customCategoryField.hidden = !isOther;
      customCategory.required = isOther;
      if (!isOther) {
        customCategory.value = "";
        clearError(customCategory);
      }
    }

    categorySelect.addEventListener("change", updateCustomCategory);
    updateCustomCategory();
  }

  // Browser history does not expose entry URLs. Mark same-origin link entries
  // so these controls never send users to an unknown or external destination.
  var backButton = document.getElementById("historyBack");
  var forwardButton = document.getElementById("historyForward");
  var pendingNavigationKey = "campusTracePendingNavigation";

  if (backButton && forwardButton) {
    var currentPage = window.location.pathname + window.location.search + window.location.hash;

    function sameOriginPath(url) {
      try {
        var parsed = new URL(url, window.location.href);
        if (parsed.origin !== window.location.origin) return null;
        return parsed.pathname + parsed.search + parsed.hash;
      } catch (_error) {
        return null;
      }
    }

    function getNavigationState() {
      var state = window.history.state;
      if (state && typeof state === "object") {
        return state.campusTraceNavigation || {};
      }
      return {};
    }

    function updateNavigationState(updates) {
      var state = window.history.state;
      var nextState = state && typeof state === "object"
        ? Object.assign({}, state)
        : { campusTracePreviousState: state };
      nextState.campusTraceNavigation = Object.assign(
        {},
        nextState.campusTraceNavigation || {},
        updates
      );
      window.history.replaceState(nextState, "");
    }

    function readPendingNavigation() {
      try {
        var value = window.sessionStorage.getItem(pendingNavigationKey);
        window.sessionStorage.removeItem(pendingNavigationKey);
        return value ? JSON.parse(value) : null;
      } catch (_error) {
        return null;
      }
    }

    function storePendingNavigation(destination) {
      try {
        window.sessionStorage.setItem(
          pendingNavigationKey,
          JSON.stringify({ from: currentPage, to: destination })
        );
      } catch (_error) {
        return;
      }
    }

    var pendingNavigation = readPendingNavigation();
    if (pendingNavigation && pendingNavigation.to === currentPage) {
      updateNavigationState({ backTo: pendingNavigation.from });
    }

    function returnedFromHistory(event) {
      var entries = window.performance &&
        window.performance.getEntriesByType("navigation");
      return Boolean(
        (event && event.persisted) ||
        (entries && entries.length && entries[0].type === "back_forward")
      );
    }

    function updateHistoryButtons(event) {
      var navigationState = getNavigationState();
      var backTo = sameOriginPath(navigationState.backTo || "");
      var forwardTo = sameOriginPath(navigationState.forwardTo || "");

      backButton.disabled = !(
        backTo &&
        backTo !== currentPage &&
        window.history.length > 1
      );
      forwardButton.disabled = !(
        returnedFromHistory(event) &&
        forwardTo &&
        forwardTo !== currentPage
      );
    }

    document.addEventListener("click", function (event) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }

      var link = event.target.closest("a[href]");
      if (!link || (link.target && link.target !== "_self") || link.hasAttribute("download")) {
        return;
      }
      var destination = sameOriginPath(link.href);
      if (!destination || destination === currentPage) return;

      updateNavigationState({ forwardTo: destination });
      storePendingNavigation(destination);
    });

    backButton.addEventListener("click", function () {
      if (!backButton.disabled) window.history.back();
    });

    forwardButton.addEventListener("click", function () {
      if (!forwardButton.disabled) {
        var forwardTo = sameOriginPath(getNavigationState().forwardTo || "");
        if (forwardTo) window.history.forward();
      }
    });

    window.addEventListener("pageshow", updateHistoryButtons);
    window.addEventListener("popstate", updateHistoryButtons);
    updateHistoryButtons();
  }

  // Friendly client-side validation for required fields
  var forms = document.querySelectorAll("form[data-validate]");
  Array.prototype.forEach.call(forms, function (form) {
    form.addEventListener("submit", function (event) {
      var ok = true;
      var required = form.querySelectorAll("[required]");

      Array.prototype.forEach.call(required, function (field) {
        field.value = field.value.trim ? field.value.trim() : field.value;
        clearError(field);
        if (!field.value) {
          showError(field, "This field is required.");
          ok = false;
        }
      });

      if (!ok) {
        event.preventDefault();
        var first = form.querySelector(".invalid");
        if (first) first.focus();
      }
    });
  });

  function showError(field, message) {
    field.classList.add("invalid");
    var note = document.createElement("p");
    note.className = "field-error";
    note.textContent = message;
    field.parentNode.appendChild(note);
  }

  function clearError(field) {
    field.classList.remove("invalid");
    var existing = field.parentNode.querySelector(".field-error");
    if (existing) existing.parentNode.removeChild(existing);
  }
})();
