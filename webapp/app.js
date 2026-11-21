const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
tg?.setHeaderColor?.("#120f1d"); tg?.setBackgroundColor?.("#120f1d");
const view = document.getElementById("view");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const hue = s => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
const b64e = s => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64d = s => decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/"))));
let ME = null;

async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {...opts, headers: {"Authorization": "tma " + (tg?.initData || ""), "Content-Type": "application/json", ...opts.headers}});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || "xatolik"), {status: r.status, data});
  return data;
}
function toast(text, withChat) {
  const t = document.getElementById("toast");
  t.hidden = false; t.style.display = "";
  t.innerHTML = `<span>${esc(text)}</span>` + (withChat ? `<button id="tchat">Chatga o'tish</button>` : "");
  if (withChat) document.getElementById("tchat").onclick = () => tg?.close();
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; t.style.display = "none"; }, 5000);
}

const pimg = m => m.poster ? `<img class="pimg" loading="lazy" src="/poster/${encodeURIComponent(m.code)}?v=${m.poster}" onerror="this.remove()" alt="">` : "";
const EYE = '<svg class="eye" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
const card = m => `<a class="card" href="#/item/${encodeURIComponent(m.code)}"><div class="poster" style="--h:${hue(m.name)}"><span class="ph">${esc(m.name)}</span>${pimg(m)}${m.kind === "series" ? '<i class="tag">Serial</i>' : ""}${m.views ? `<span class="vw">${EYE}${m.views}</span>` : ""}</div><div class="t">${esc(m.name)}</div>${m.year ? `<div class="s">${m.year}</div>` : ""}</a>`;
const GI = {Jangari:"💥",Komediya:"😂",Drama:"🎭",Fantastika:"🚀",Triller:"🔪",Sarguzasht:"🧭","Qo'rqinchli":"👻",Romantika:"💘",Multfilm:"🧸"};
const row = (title, items, link) => items.length ? `<div class="sec"><h2>${title}</h2>${link ? `<a href="${link}">Barchasi</a>` : ""}</div><div class="row">${items.map(card).join("")}</div>` : "";

// ---------- sahifalar ----------
async function home() {
  const d = await api("/home");
  const top = d.popular[0];
  view.innerHTML =
    (top ? `<a class="hero" style="--h:${hue(top.name)}" href="#/item/${encodeURIComponent(top.code)}">${pimg(top)}<div class="hin"><span class="pill">Bugungi tavsiya</span><h3>${esc(top.name)}</h3><div class="meta">${esc([top.year, top.genres.join(", ")].filter(Boolean).join(", "))}</div><span class="btn sm">Batafsil</span></div></a>` : "") +
    `<button class="rnd" id="rnd"><b>Nima ko'rishni bilmayapsizmi?</b><span>Tasodifiy kino tanlash</span></button>` +
    row("Yangi qo'shilganlar", d.latest, "#/catalog?sort=new&type=movie") + row("Mashhur", d.popular, "#/catalog?sort=popular") + row("Seriallar", d.series, "#/catalog?type=series") +
    `<div class="sec"><h2>Janrlar</h2></div><div class="chips" style="margin-top:0">${ME.genres.map(g => `<a class="chip" href="#/catalog?genre=${encodeURIComponent(g)}"><i>${GI[g] || "🎞"}</i>${esc(g)}</a>`).join("")}</div>`;
  document.getElementById("rnd").onclick = async () => { const r = await api("/random"); if (r.code) location.hash = "#/item/" + encodeURIComponent(r.code); };
}

async function catalog(_, p) {
  const f = {type: p.get("type") || "all", genre: p.get("genre") || "", year: p.get("year") || "", sort: p.get("sort") || "new"};
  const sel = (id, opts, val) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === val ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  view.innerHTML = `<h1>Katalog</h1><div class="filters">
    ${sel("f-type", [["all", "Barchasi"], ["movie", "Kinolar"], ["series", "Seriallar"]], f.type)}
    ${sel("f-sort", [["new", "Eng yangi"], ["popular", "Mashhur"], ["name", "Nomi (A-Z)"]], f.sort)}
    ${sel("f-genre", [["", "Barcha janrlar"], ...ME.genres.map(g => [g, g])], f.genre)}
    <input id="f-year" type="number" inputmode="numeric" placeholder="Yil (masalan 2024)" value="${esc(f.year)}"></div>
    <div class="grid" id="grid"></div><button class="btn alt" id="more" hidden>Yana ko'rsatish</button>`;
  const apply = () => { const q = new URLSearchParams({type: $v("f-type"), sort: $v("f-sort"), genre: $v("f-genre"), year: $v("f-year")}); location.hash = "#/catalog?" + q; };
  ["f-type", "f-sort", "f-genre"].forEach(id => document.getElementById(id).onchange = apply);
  document.getElementById("f-year").onchange = apply;
  let offset = 0; const grid = document.getElementById("grid"), more = document.getElementById("more");
  async function load() {
    const d = await api("/catalog?" + new URLSearchParams({...f, offset, limit: 20}));
    grid.insertAdjacentHTML("beforeend", d.items.map(card).join(""));
    offset += d.items.length; more.hidden = !d.has_more;
    if (!offset) grid.innerHTML = '<div class="empty" style="grid-column:1/-1"><b>Hech narsa topilmadi</b>Filtrlarni o\'zgartirib ko\'ring.</div>';
  }
  more.onclick = load; await load();
}
const $v = id => document.getElementById(id).value;

function search() {
  view.innerHTML = `<h1>Qidiruv</h1><input id="q" placeholder="Kino, serial nomi yoki kodi" autofocus><div class="grid" id="res" style="margin-top:14px"></div>`;
  const q = document.getElementById("q"), res = document.getElementById("res"); let timer;
  q.oninput = () => { clearTimeout(timer); timer = setTimeout(async () => {
    const t = q.value.trim(); if (t.length < 1) { res.innerHTML = ""; return; }
    const d = await api("/catalog?" + new URLSearchParams({q: t, limit: 30}));
    res.innerHTML = d.items.length ? d.items.map(card).join("") : '<div class="empty" style="grid-column:1/-1"><b>Topilmadi</b>Nomini boshqacha yozing yoki kodni kiriting.</div>';
  }, 300); };
}

async function fav() {
  const d = await api("/favorites");
  view.innerHTML = `<h1>Sevimlilar</h1>` + (d.items.length ? `<div class="grid">${d.items.map(card).join("")}</div>` : '<div class="empty"><b>Sevimlilar bo\'sh</b>Kino sahifasidagi «Sevimlilarga» tugmasini bosing.</div>');
}

async function profile() {
  ME = await api("/me");
  const u = tg?.initDataUnsafe?.user || {};
  const s = ME.stats;
  view.innerHTML = `<div class="prof">${u.photo_url ? `<img src="${esc(u.photo_url)}" alt="">` : '<div class="av"></div>'}
    <h1>${esc([u.first_name, u.last_name].filter(Boolean).join(" ") || "Foydalanuvchi")}</h1>
    <div class="muted">${u.username ? "@" + esc(u.username) + " · " : ""}ID: ${esc(u.id || "")}</div></div>
    <div class="stats"><div><b>${s.movies}</b>Kino</div><div><b>${s.series}</b>Serial</div><div><b>${s.favs}</b>Sevimli</div></div>
    ${row("Oxirgi ko'rilganlar", ME.recent)}
    <button class="btn alt" id="tobot">🤖 Botga qaytish</button>`;
  document.getElementById("tobot").onclick = () => tg?.close();
}

async function item(code) {
  const m = await api("/item/" + encodeURIComponent(code));
  const eps = m.episodes.length ? `<div class="sec"><h2>Qismlar</h2></div><div class="eps">${m.episodes.map(n => `<button data-ep="${n}" class="${n === m.last_episode ? "on" : ""}">${n}</button>`).join("")}</div>` : "";
  const next = m.kind === "series" && m.episodes.length ? (m.episodes.find(n => n > (m.last_episode || 0)) || m.episodes[0]) : null;
  view.innerHTML = `<div class="ibg" style="--h:${hue(m.name)}">${pimg(m)}</div>
    <div class="big" style="--h:${hue(m.name)}"><span>${esc(m.name[0] || "🎬")}</span>${pimg(m)}</div>
    <h1 class="ttl">${esc(m.name)}</h1>
    <div class="facts">${[m.year, m.duration && m.duration + " daq", m.kind === "series" && m.episodes.length + " qism"].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join("")}<span class="vw">${EYE}${m.views}</span></div>
    ${m.genres.length ? `<div class="chips" style="justify-content:center">${m.genres.map(g => `<span class="chip">${esc(g)}</span>`).join("")}</div>` : ""}
    <div class="ticket"><span>Kino kodi</span><b>${esc(m.code)}</b></div>
    ${m.description ? `<p class="desc">${esc(m.description)}</p>` : ""}
    ${m.kind === "movie" ? `<button class="btn" id="play">▶ Tomosha qilish</button>` : (next ? `<button class="btn" data-ep="${next}">▶ ${m.last_episode ? "Davom ettirish" : "Boshlash"} (${next}-qism)</button>` : '<p class="muted">Qismlar hali qo\'shilmagan</p>')}
    <div class="two"><button class="btn alt" id="fav">${m.fav ? "♥ Sevimlilarda" : "♡ Sevimlilarga"}</button><button class="btn alt" id="share">Ulashish</button></div>
    ${eps}${ME.is_admin ? posterBtn() + adminForm(m) : ""}`;
  view.onclick = e => { const ep = e.target.closest("[data-ep]"); if (ep) watch(m.code, +ep.dataset.ep); };
  const play = document.getElementById("play"); if (play) play.onclick = () => watch(m.code);
  document.getElementById("fav").onclick = async e => { const r = await api("/fav", {method: "POST", body: JSON.stringify({code: m.code})}); e.target.textContent = r.fav ? "♥ Sevimlilarda" : "♡ Sevimlilarga"; };
  document.getElementById("share").onclick = () => {
    const link = `https://t.me/${ME.bot}?startapp=${b64e(m.code)}`;
    const url = "https://t.me/share/url?url=" + encodeURIComponent(link) + "&text=" + encodeURIComponent("🎬 " + m.name);
    tg?.openTelegramLink ? tg.openTelegramLink(url) : window.open(url);
  };
  const pin = document.getElementById("a-poster");
  if (pin) pin.onchange = async () => {
    if (!pin.files[0]) return;
    try { toast("⏳ Yuklanmoqda…");
      await api("/admin/poster/" + encodeURIComponent(m.code), {method: "PUT", body: await resizeImg(pin.files[0]), headers: {"Content-Type": "image/jpeg"}});
      toast("✅ Poster saqlandi"); route();
    } catch (e) { toast("⚠️ Poster yuklanmadi"); }
  };
  const form = document.getElementById("aform");
  if (form) form.onsubmit = async e => { e.preventDefault();
    await api("/admin/item/" + encodeURIComponent(m.code), {method: "PUT", body: JSON.stringify({
      year: $v("a-year"), duration: $v("a-dur"), description: $v("a-desc"),
      genres: [...form.querySelectorAll("input[name=g]:checked")].map(i => i.value)})});
    toast("✅ Saqlandi"); route(); };
}
const posterBtn = () => `<label class="btn alt">🖼 Posterni o'zgartirish<input type="file" accept="image/*" id="a-poster" hidden></label>`;
async function resizeImg(file) {
  const img = await createImageBitmap(file), w = 600, h = 900, c = document.createElement("canvas");
  c.width = w; c.height = h;
  const k = Math.max(w / img.width, h / img.height);
  c.getContext("2d").drawImage(img, (w - img.width * k) / 2, (h - img.height * k) / 2, img.width * k, img.height * k);
  return new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
}
const adminForm = m => `<details class="admin"><summary>✏️ Tahrirlash (admin)</summary><form id="aform">
  <input id="a-year" type="number" placeholder="Yil" value="${m.year || ""}">
  ${m.kind === "movie" ? `<input id="a-dur" type="number" placeholder="Davomiyligi (daqiqa)" value="${m.duration || ""}">` : '<input id="a-dur" type="hidden">'}
  <textarea id="a-desc" rows="4" placeholder="Tavsif">${esc(m.description)}</textarea>
  <div>${ME.genres.map(g => `<label><input type="checkbox" name="g" value="${esc(g)}"${m.genres.includes(g) ? " checked" : ""}> ${esc(g)}</label>`).join("")}</div>
  <button class="btn" type="submit">Saqlash</button></form></details>`;

async function watch(code, episode) {
  try {
    await api("/watch", {method: "POST", body: JSON.stringify({code, episode})});
    tg?.HapticFeedback?.notificationOccurred("success");
    toast("✅ Video botga yuborildi", true);
  } catch (e) {
    const d = e.data || {};
    if (d.error === "subscribe") { const l = d.channels?.[0]; tg ? tg.showAlert("Avval kanalga obuna bo'ling, so'ng qayta urinib ko'ring.", () => l && tg.openLink(l)) : alert("Kanalga obuna bo'ling"); }
    else if (d.error === "start_bot") { tg ? tg.showAlert("Avval botga o'tib /start bosing, so'ng qayta urinib ko'ring.", () => tg.close()) : alert("Botga /start yuboring"); }
    else if (d.error === "too_fast") toast("⏳ Biroz kuting…");
    else toast("⚠️ Yuborib bo'lmadi, keyinroq urinib ko'ring");
  }
}

// ---------- router ----------
const routes = {home, catalog, search, fav, profile, item};
async function route() {
  const [path, qs] = (location.hash.slice(1) || "/").split("?");
  const parts = path.split("/").filter(Boolean), name = routes[parts[0]] ? parts[0] : "home";
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.r === name));
  tg?.BackButton[name === "item" ? "show" : "hide"]();
  view.onclick = null;
  view.innerHTML = `<div class="grid" style="margin-top:14px">${"<div class='sk'></div>".repeat(6)}</div>`;
  try { await routes[name](decodeURIComponent(parts[1] || ""), new URLSearchParams(qs || "")); }
  catch (e) { view.innerHTML = `<p class="err">${e.status === 404 ? "Topilmadi" : "Xatolik: " + esc(e.message)}</p>`; }
  window.scrollTo(0, 0);
}
tg?.BackButton.onClick(() => history.back());
addEventListener("hashchange", route);
(async () => {
  try {
    if (!tg?.initData) throw Object.assign(new Error("Mini App'ni Telegram ichida oching"), {});
    ME = await api("/me");
    const sp = tg.initDataUnsafe?.start_param;
    if (sp) { try { location.hash = "#/item/" + encodeURIComponent(b64d(sp)); return; } catch (_) {} }
    route();
  } catch (e) { view.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
})();