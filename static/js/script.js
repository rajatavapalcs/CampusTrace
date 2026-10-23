/* CampusTrace - vanilla JavaScript only.
   Frontend validation and the mobile menu. The server always validates again,
   and no secret answer is ever sent to the browser. */

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
