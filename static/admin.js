import { fetchMe, logout, refreshAuthUI } from "./auth.js";

const $ = (id) => document.getElementById(id);
const els = {
  user: $("authUser"),
  avatar: $("authAvatar"),
  logout: $("adminLogout"),
  error: $("adminError"),
  denied: $("adminDenied"),
  main: $("adminMain"),
  form: $("createForm"),
  name: $("newName"),
  pass: $("newPass"),
  role: $("newRole"),
  rows: $("userRows"),
};

function setError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

async function loadUsers() {
  const resp = await fetch("/api/admin/users");
  if (resp.status === 401) {
    location.href = "/login.html?next=/admin.html";
    return;
  }
  if (resp.status === 403) {
    els.denied.hidden = false;
    return;
  }
  if (!resp.ok) {
    setError("加载用户列表失败。");
    return;
  }
  const { users } = await resp.json();
  els.rows.replaceChildren();
  for (const u of users) {
    const tr = document.createElement("tr");
    const cells = [
      u.username,
      u.role === "admin" ? "管理员" : "普通用户",
      String(u.draws_7d),
      String(u.draws_total),
      (u.created_at || "").replace("T", " ").slice(0, 16),
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    const td = document.createElement("td");
    const resetBtn = document.createElement("button");
    resetBtn.className = "btn btn--small";
    resetBtn.textContent = "重置密码";
    resetBtn.addEventListener("click", async () => {
      const password = prompt(`为 ${u.username} 设置新密码(至少 6 位):`);
      if (!password) return;
      const r = await fetch(`/api/admin/users/${u.id}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      setError(r.ok ? "" : "重置失败,请检查输入。");
      if (r.ok) loadUsers();
    });
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn--danger btn--small";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", async () => {
      if (!confirm(`确认删除用户 ${u.username}?其练习记录将一并删除。`)) return;
      const r = await fetch(`/api/admin/users/${u.id}`, { method: "DELETE" });
      setError(r.ok ? "" : "删除失败。");
      loadUsers();
    });
    td.appendChild(resetBtn);
    td.appendChild(delBtn);
    tr.appendChild(td);
    els.rows.appendChild(tr);
  }
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  setError("");
  const resp = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: els.name.value,
      password: els.pass.value,
      role: els.role.value,
    }),
  });
  if (!resp.ok) {
    const j = await resp.json().catch(() => ({}));
    setError(j.detail || "创建失败。");
    return;
  }
  els.name.value = "";
  els.pass.value = "";
  loadUsers();
});

els.logout.addEventListener("click", async () => {
  await logout();
  location.href = "/";
});

async function init() {
  const me = await fetchMe();
  if (!me) {
    location.href = "/login.html?next=/admin.html";
    return;
  }
  await refreshAuthUI({ authUser: els.user, authAvatar: els.avatar, authLogoutBtn: els.logout });
  if (me.role !== "admin") {
    els.denied.hidden = false;
    return;
  }
  els.main.hidden = false;
  loadUsers();
}

init();
