/* 登录 */
(function () {
  const form = document.getElementById('login-form');
  const err = document.getElementById('err');
  const btn = document.getElementById('submit');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.hidden = true;
    btn.disabled = true;
    btn.textContent = '登录中…';
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: form.username.value.trim(),
          password: form.password.value,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '登录失败');
      location.href = data.redirect || '/admin';
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      btn.disabled = false;
      btn.textContent = '登录';
    }
  });
})();
