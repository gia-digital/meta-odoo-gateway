(function () {
  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.getElementById("primary-nav");

  function syncTopbarHeight() {
    if (!document.body.classList.contains("table-view")) return;
    var bar = document.querySelector(".topbar");
    if (!bar) return;
    document.body.style.setProperty("--topbar-h", bar.offsetHeight + "px");
  }

  syncTopbarHeight();
  window.addEventListener("resize", syncTopbarHeight);

  function setOpen(open) {
    if (!toggle) return;
    document.body.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú");
    requestAnimationFrame(syncTopbarHeight);
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

  var playForm = document.getElementById("playground-form");
  var playLog = document.getElementById("playground-log");
  var playInput = document.getElementById("playground-input");
  var playSend = document.getElementById("playground-send");
  var playReset = document.getElementById("playground-reset");
  var playEmpty = document.getElementById("playground-empty");
  if (playForm && playLog && playInput) {
    var history = [];
    var state = {};
    var busy = false;

    function node(tag, className, text) {
      var el = document.createElement(tag);
      if (className) el.className = className;
      if (text != null) el.textContent = text;
      return el;
    }

    function scrollLog() {
      playLog.scrollTop = playLog.scrollHeight;
    }

    function hideEmpty() {
      if (playEmpty) playEmpty.hidden = true;
    }

    function appendTurn(role, bubbles, events) {
      hideEmpty();
      var turn = node(
        "div",
        "playground-turn playground-turn-" + (role === "user" ? "user" : "agent")
      );
      var parts = bubbles && bubbles.length ? bubbles : [""];
      parts.forEach(function (text) {
        var msg = node("div", "msg " + (role === "user" ? "msg-inbound" : "msg-outbound"));
        var meta = node("div", "msg-meta");
        meta.appendChild(node("span", null, role === "user" ? "Cliente" : "GIA"));
        msg.appendChild(meta);
        msg.appendChild(node("div", "msg-body", text));
        turn.appendChild(msg);
      });
      if (events && events.length) {
        var row = node("div", "playground-events");
        events.forEach(function (event) {
          var label = event.label || "Acción simulada";
          if (event.detail) label += " — " + event.detail;
          row.appendChild(node("span", "playground-event", label));
        });
        turn.appendChild(row);
      }
      playLog.appendChild(turn);
      scrollLog();
      return turn;
    }

    function setBusy(on) {
      busy = on;
      playSend.disabled = on;
      playInput.disabled = on;
      playSend.textContent = on ? "Escribiendo…" : "Enviar";
    }

    playInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        playForm.requestSubmit();
      }
    });

    playForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (busy) return;
      var text = playInput.value.trim();
      if (!text) return;
      var mine = appendTurn("user", [text]);
      playInput.value = "";
      setBusy(true);
      var pending = node("div", "playground-turn playground-turn-agent playground-typing");
      var pendingMsg = node("div", "msg msg-outbound");
      pendingMsg.appendChild(node("div", "msg-body", "GIA está escribiendo…"));
      pending.appendChild(pendingMsg);
      playLog.appendChild(pending);
      scrollLog();

      fetch("/dashboard/playground/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ message: text, history: history, state: state }),
      })
        .then(function (response) {
          return response.text().then(function (raw) {
            var data = {};
            try { data = raw ? JSON.parse(raw) : {}; } catch (err) { data = {}; }
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          pending.remove();
          if (!result.ok || typeof result.data.reply !== "string") {
            if (mine) mine.remove();
            var fail = node("div", "playground-turn playground-turn-agent playground-error");
            var failMsg = node("div", "msg msg-outbound");
            failMsg.appendChild(node("div", "msg-body", (result.data && result.data.detail) || "No se pudo generar la respuesta. Si la sesión expiró, recarga la página."));
            fail.appendChild(failMsg);
            playLog.appendChild(fail);
            scrollLog();
            playInput.value = text;
            return;
          }
          var bubbles = result.data.bubbles && result.data.bubbles.length
            ? result.data.bubbles
            : [result.data.reply || ""];
          appendTurn("agent", bubbles, result.data.events || []);
          history.push({ role: "user", content: text });
          history.push({ role: "assistant", content: result.data.reply || bubbles.join("\n---\n") });
          state = result.data.state || state;
        })
        .catch(function () {
          pending.remove();
          if (mine) mine.remove();
          var fail = node("div", "playground-turn playground-turn-agent playground-error");
          var failMsg = node("div", "msg msg-outbound");
          failMsg.appendChild(node("div", "msg-body", "No hubo conexión con el servidor. El mensaje no se envió."));
          fail.appendChild(failMsg);
          playLog.appendChild(fail);
          scrollLog();
          playInput.value = text;
        })
        .finally(function () {
          setBusy(false);
          playInput.focus();
        });
    });

    if (playReset) {
      playReset.addEventListener("click", function () {
        history = [];
        state = {};
        playInput.value = "";
        playLog.querySelectorAll(".playground-turn").forEach(function (turn) {
          turn.remove();
        });
        if (playEmpty) playEmpty.hidden = false;
        playInput.focus();
      });
    }
  }
})();
