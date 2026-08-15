(function () {
  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.getElementById("primary-nav");

  function setOpen(open) {
    if (!toggle) return;
    document.body.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú");
  }

  if (toggle && nav) {
    toggle.addEventListener("click", function (event) {
      event.stopPropagation();
      setOpen(!document.body.classList.contains("nav-open"));
    });

    document.addEventListener("click", function (event) {
      if (!document.body.classList.contains("nav-open")) return;
      if (event.target.closest(".topbar")) return;
      setOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 900) setOpen(false);
    });
  }

  document.querySelectorAll(".file-drop input[type=file]").forEach(function (input) {
    input.addEventListener("change", function () {
      var title = input.closest(".file-drop").querySelector(".file-drop-title");
      if (title && input.files && input.files[0]) {
        title.textContent = input.files[0].name;
      }
    });
  });

  function focusFirstField(dialog) {
    var field = dialog.querySelector("input:not([type=hidden]), textarea, select");
    if (field) field.focus();
  }

  function openDialog(dialog) {
    if (!dialog || typeof dialog.showModal !== "function") return;
    dialog.showModal();
    focusFirstField(dialog);
  }

  function dismissDialog(dialog) {
    var url = dialog.getAttribute("data-dismiss-url");
    if (url && dialog.hasAttribute("data-open")) {
      window.location.href = url;
      return;
    }
    if (typeof dialog.close === "function") dialog.close();
  }

  document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dialog = document.getElementById(btn.getAttribute("data-open-dialog"));
      if (dialog) openDialog(dialog);
    });
  });

  document.querySelectorAll("[data-close-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dialog = btn.closest("dialog");
      if (dialog) dismissDialog(dialog);
    });
  });

  document.querySelectorAll("dialog.modal").forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dismissDialog(dialog);
    });
    dialog.addEventListener("cancel", function (event) {
      if (!dialog.hasAttribute("data-open")) return;
      event.preventDefault();
      dismissDialog(dialog);
    });
  });

  var auto = document.querySelector("dialog.modal[data-open]");
  if (auto) openDialog(auto);
})();
