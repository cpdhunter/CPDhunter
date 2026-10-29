// ===== 網站基本資料：上線前請修改呢 3 行 =====
window.SITE = {
  operator: "cpdhunter］",   // 你的全名或公司名稱
  email: "［hkcpdhunter@gmail.com］",        // 例如 hello@cpdhunter.hk
  effective: "2026-10-29"       // 條款生效／最後更新日期
};
document.addEventListener("DOMContentLoaded", () => {
  for (const [k, v] of Object.entries(window.SITE))
    document.querySelectorAll("[data-site=" + k + "]").forEach(el => {
      el.textContent = v;
      if (k === "email" && el.tagName === "A") el.href = "mailto:" + v;
    });
  const set = l => {
    document.documentElement.lang = l === "en" ? "en" : "zh-HK";
    document.querySelectorAll("[data-lang]").forEach(el => el.hidden = el.dataset.lang !== l);
    document.querySelectorAll(".lang button").forEach(b => b.classList.toggle("on", b.dataset.l === l));
    try { localStorage.setItem("lang", l); } catch (e) {}
  };
  document.querySelectorAll(".lang button").forEach(b => b.onclick = () => set(b.dataset.l));
  let l = "zh"; try { l = localStorage.getItem("lang") || "zh"; } catch (e) {}
  set(l);
});
