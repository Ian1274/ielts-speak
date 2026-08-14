// 独立登录页:登录成功后跳回 ?next= 校验后的站内地址,无 next 跳首页。
import { fetchMe, login } from "./auth.js";

const $ = (id) => document.getElementById(id);
const els = {
  form: $("loginForm"),
  name: $("loginName"),
  pass: $("loginPass"),
  error: $("loginError"),
  submit: $("loginSubmit"),
};

// 只允许站内相对路径,防 open-redirect
function nextTarget() {
  const next = new URLSearchParams(location.search).get("next");
  if (
    next &&
    next.startsWith("/") &&
    !next.startsWith("//") &&
    !next.includes("\\") &&
    !next.includes(":")
  ) {
    return next;
  }
  return "/";
}

function setError(msg) {
  els.error.textContent = msg;
  els.error.hidden = !msg;
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  setError("");
  els.submit.disabled = true;
  try {
    await login(els.name.value.trim(), els.pass.value);
    location.href = nextTarget();
  } catch (err) {
    setError(err.message);
    els.submit.disabled = false;
  }
});

// 已登录则直接跳过登录页
if (await fetchMe()) location.href = nextTarget();
