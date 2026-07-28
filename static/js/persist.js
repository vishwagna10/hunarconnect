// persist.js
// Any form with [data-persist-key="some_form_name"] gets its fields
// (input, textarea, select, checkboxes) auto-saved to localStorage as the
// person types, and restored the next time that form is opened -- even if
// they closed the app before submitting. Cleared on successful submit.
(function () {
  function storageKey(formKey, fieldName) {
    return "hunarconnect:" + formKey + ":" + fieldName;
  }

  function restoreForm(form, formKey) {
    var fields = form.querySelectorAll("[name]");
    fields.forEach(function (field) {
      var key = storageKey(formKey, field.name);
      var saved = localStorage.getItem(key);
      if (saved === null) return;

      if (field.type === "checkbox" || field.type === "radio") {
        var savedList = JSON.parse(saved);
        if (Array.isArray(savedList)) {
          field.checked = savedList.indexOf(field.value) !== -1;
        } else {
          field.checked = saved === "true";
        }
      } else if (field.type !== "password") {
        field.value = saved;
      }
    });
  }

  function attachAutosave(form, formKey) {
    var fields = form.querySelectorAll("[name]");
    fields.forEach(function (field) {
      var evt = (field.tagName === "SELECT" || field.type === "checkbox" || field.type === "radio")
        ? "change" : "input";
      field.addEventListener(evt, function () {
        if (field.type === "password") return; // never persist passwords
        var key = storageKey(formKey, field.name);
        if (field.type === "checkbox") {
          var group = form.querySelectorAll('[name="' + field.name + '"]');
          if (group.length > 1) {
            var checked = Array.prototype.filter.call(group, function (f) { return f.checked; })
              .map(function (f) { return f.value; });
            localStorage.setItem(key, JSON.stringify(checked));
          } else {
            localStorage.setItem(key, field.checked);
          }
        } else {
          localStorage.setItem(key, field.value);
        }
      });
    });

    form.addEventListener("submit", function () {
      fields.forEach(function (field) {
        localStorage.removeItem(storageKey(formKey, field.name));
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-persist-key]").forEach(function (form) {
      var formKey = form.getAttribute("data-persist-key");
      restoreForm(form, formKey);
      attachAutosave(form, formKey);
    });
  });
})();
