// Login / create-account page.
(function () {
  const form = document.getElementById("auth-form");
  const tabLogin = document.getElementById("tab-login");
  const tabReg = document.getElementById("tab-register");
  const nameField = document.getElementById("name-field");
  const pwHint = document.getElementById("pw-hint");
  const title = document.getElementById("form-title");
  const btn = document.getElementById("submit-btn");
  const errBox = document.getElementById("auth-error");
  const themeBtn = document.getElementById("theme-btn");
  const paintTheme = () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    themeBtn.textContent = dark ? "Light mode" : "Dark mode";
  };
  themeBtn.onclick = () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("cp-theme", next); } catch (e) { /* private mode */ }
    paintTheme();
  };
  paintTheme();
  let mode = location.hash === "#register" ? "register" : "login";

  function setMode(m) {
    mode = m;
    const reg = m === "register";
    tabLogin.setAttribute("aria-selected", String(!reg));
    tabReg.setAttribute("aria-selected", String(reg));
    nameField.classList.toggle("hidden", !reg);
    pwHint.classList.toggle("hidden", !reg);
    title.textContent = reg ? "Create your account" : "Welcome back";
    btn.textContent = reg ? "Create account" : "Log in";
    form.password.autocomplete = reg ? "new-password" : "current-password";
    errBox.classList.add("hidden");
    (reg ? form.name : form.email).focus();
  }
  tabLogin.onclick = () => setMode("login");
  tabReg.onclick = () => setMode("register");
  setMode(mode);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errBox.classList.add("hidden");
    const data = { email: form.email.value.trim(), password: form.password.value };
    if (mode === "register") data.name = form.name.value.trim();
    if (!data.email || !data.password || (mode === "register" && !data.name)) {
      errBox.textContent = "Fill in every field to continue.";
      errBox.classList.remove("hidden");
      return;
    }
    btn.disabled = true;
    const label = btn.textContent;
    btn.innerHTML = `<span class="spinner"></span> ${mode === "register" ? "Creating account" : "Logging in"}`;
    try {
      await API.post(mode === "register" ? "/api/auth/register" : "/api/auth/login", data);
      location.href = "/app";
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = label;
    }
  });
})();
