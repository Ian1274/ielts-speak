// Auth helpers + UI state, shared by index page and admin page.

export async function fetchMe() {
  try {
    const resp = await fetch("/api/auth/me");
    if (!resp.ok) return null;
    return await resp.json(); // {username, role}
  } catch {
    return null;
  }
}

export async function login(username, password) {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    throw new Error(j.detail || "登录失败,请重试。");
  }
  return await resp.json();
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
}

// els: {authUser, authLoginBtn, authAdminBtn, authLogoutBtn} — 全部可选
export async function refreshAuthUI(els) {
  const me = await fetchMe();
  const loggedIn = Boolean(me);
  if (els.authUser) {
    els.authUser.hidden = !loggedIn;
    if (me) els.authUser.textContent = `${me.username}${me.role === "admin" ? " · 管理员" : ""}`;
  }
  if (els.authLoginBtn) els.authLoginBtn.hidden = loggedIn;
  if (els.authAdminBtn) els.authAdminBtn.hidden = !(loggedIn && me.role === "admin");
  if (els.authLogoutBtn) els.authLogoutBtn.hidden = !loggedIn;
}
