// Tiny API client shared by the login page and the dashboard.
const API = {
  async call(method, url, data, isForm) {
    const opts = { method, credentials: "same-origin", headers: { "X-Requested-With": "CampusPulse" } };
    if (data !== undefined) {
      if (isForm) opts.body = data;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(data); }
    }
    const res = await fetch(url, opts);
    if (res.status === 401 && !url.startsWith("/api/auth/login")) {
      if (location.pathname !== "/") location.href = "/";
    }
    const type = res.headers.get("content-type") || "";
    const body = type.includes("json") ? await res.json() : await res.text();
    if (!res.ok) throw new Error((body && body.error) || `Request failed (${res.status})`);
    return body;
  },
  get(url) { return this.call("GET", url); },
  post(url, data) { return this.call("POST", url, data === undefined ? {} : data); },
  put(url, data) { return this.call("PUT", url, data); },
  patch(url, data) { return this.call("PATCH", url, data); },
  del(url, data) { return this.call("DELETE", url, data === undefined ? {} : data); },
  form(url, formData) { return this.call("POST", url, formData, true); },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
