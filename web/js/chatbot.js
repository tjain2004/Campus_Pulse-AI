// Pulse chat widget — talks to /api/chat (backend/chatbot.py, rule-based, no API key).
(function () {
  const fab = document.getElementById("bot-fab");
  const box = document.getElementById("bot");
  const body = document.getElementById("bot-body");
  const chips = document.getElementById("bot-chips");
  const form = document.getElementById("bot-form");
  const input = document.getElementById("bot-input");
  const badge = document.getElementById("bot-badge");
  let started = false;

  function add(role, html, link) {
    const div = document.createElement("div");
    div.className = "bm " + (role === "user" ? "user" : "bot-msg");
    div.innerHTML = html + (link ? `<a class="go" href="#${link}">Open ${link.replace(/^\w/, (c) => c.toUpperCase())}</a>` : "");
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }
  function setChips(list) {
    chips.innerHTML = (list || []).map((c) => `<button type="button" class="chip">${esc(c)}</button>`).join("");
  }
  chips.addEventListener("click", (e) => { const b = e.target.closest(".chip"); if (b) send(b.textContent); });

  async function send(text, silent) {
    text = (text || "").trim();
    if (!text) return;
    if (!silent) add("user", esc(text));
    const typing = add("bot", '<span class="typing"><span></span><span></span><span></span></span>');
    try {
      const r = await API.post("/api/chat", { message: text });
      typing.remove();
      add("bot", md(r.reply), r.link);
      setChips(r.chips);
      if (r.refresh && typeof refreshMe === "function") { refreshMe(); if (location.hash === "#tasks") route(); }
    } catch (err) {
      typing.remove();
      add("bot", esc(err.message));
    }
  }

  function open() {
    box.classList.remove("hidden");
    fab.setAttribute("aria-expanded", "true");
    badge.classList.add("hidden");
    if (!started) { started = true; send("hi", true); }
    setTimeout(() => input.focus(), 50);
  }
  function close() { box.classList.add("hidden"); fab.setAttribute("aria-expanded", "false"); fab.focus(); }

  fab.onclick = () => (box.classList.contains("hidden") ? open() : close());
  document.getElementById("bot-close").onclick = close;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !box.classList.contains("hidden")) close(); });
  form.onsubmit = (e) => { e.preventDefault(); const v = input.value; input.value = ""; send(v); };
  document.addEventListener("click", (e) => { if (e.target.closest(".bm .go")) close(); });
})();
