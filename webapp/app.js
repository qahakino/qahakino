const tg = window.Telegram?.WebApp;
tg?.ready(); tg?.expand();
tg?.setHeaderColor?.("#120f1d"); tg?.setBackgroundColor?.("#120f1d");
const view = document.getElementById("view");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const hue = s => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
const b64e = s => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const b64d = s => decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/"))));
let ME = null;

// ---------- tillar ----------
const I18N = {
  uz: {nav_home:"Bosh", nav_catalog:"Katalog", nav_search:"Qidiruv", nav_fav:"Sevimli", nav_profile:"Profil",
    loading:"Yuklanmoqda…", open_tg:"Mini App'ni Telegram ichida oching", not_found:"Topilmadi", error:"Xatolik",
    pill:"Bugungi tavsiya", details:"Batafsil", rnd_t:"Nima ko'rishni bilmayapsizmi?", rnd_s:"Tasodifiy kino tanlash",
    sec_new:"Yangi qo'shilganlar", sec_pop:"Mashhur", sec_series:"Seriallar", sec_genres:"Janrlar", all:"Barchasi",
    catalog:"Katalog", t_all:"Barchasi", t_movies:"Kinolar", t_series:"Seriallar", s_new:"Eng yangi", s_pop:"Mashhur", s_name:"Nomi (A-Z)",
    g_all:"Barcha janrlar", year_ph:"Yil (masalan 2024)", more:"Yana ko'rsatish", nothing:"Hech narsa topilmadi", nothing_s:"Filtrlarni o'zgartirib ko'ring.",
    search:"Qidiruv", search_ph:"Kino, serial nomi yoki kodi", nf:"Topilmadi", nf_s:"Nomini boshqacha yozing yoki kodni kiriting.",
    fav:"Sevimlilar", fav_empty:"Sevimlilar bo'sh", fav_empty_s:"Kino sahifasidagi «Sevimlilarga» tugmasini bosing.",
    user:"Foydalanuvchi", st_movies:"Kino", st_series:"Serial", st_favs:"Sevimli", recent:"Oxirgi ko'rilganlar", to_bot:"🤖 Botga qaytish", language:"Til",
    tag_series:"Serial", min:"daq", n_eps:"{n} qism", code_lbl:"Kino kodi", play:"▶ Tomosha qilish", play_ep:"▶ Tomosha qilish · {n}-qism",
    episodes:"Qismlar", fav_on:"♥ Sevimlilarda", fav_off:"♡ Sevimlilarga", share:"Ulashish", no_eps:"Qismlar hali qo'shilmagan",
    sent:"✅ Video botga yuborildi", to_chat:"Chatga o'tish", sub_alert:"Avval kanalga obuna bo'ling, so'ng qayta urinib ko'ring.",
    start_alert:"Avval botga o'tib /start bosing, so'ng qayta urinib ko'ring.", wait:"⏳ Biroz kuting…", fail:"⚠️ Yuborib bo'lmadi, keyinroq urinib ko'ring"},
  ru: {nav_home:"Главная", nav_catalog:"Каталог", nav_search:"Поиск", nav_fav:"Избранное", nav_profile:"Профиль",
    loading:"Загрузка…", open_tg:"Откройте Mini App внутри Telegram", not_found:"Не найдено", error:"Ошибка",
    pill:"Рекомендация дня", details:"Подробнее", rnd_t:"Не знаете, что посмотреть?", rnd_s:"Выбрать случайный фильм",
    sec_new:"Новинки", sec_pop:"Популярное", sec_series:"Сериалы", sec_genres:"Жанры", all:"Все",
    catalog:"Каталог", t_all:"Всё", t_movies:"Фильмы", t_series:"Сериалы", s_new:"Сначала новые", s_pop:"Популярные", s_name:"По названию (А-Я)",
    g_all:"Все жанры", year_ph:"Год (например 2024)", more:"Показать ещё", nothing:"Ничего не найдено", nothing_s:"Попробуйте изменить фильтры.",
    search:"Поиск", search_ph:"Название фильма, сериала или код", nf:"Не найдено", nf_s:"Попробуйте другое написание или введите код.",
    fav:"Избранное", fav_empty:"В избранном пусто", fav_empty_s:"Нажмите «В избранное» на странице фильма.",
    user:"Пользователь", st_movies:"Фильмы", st_series:"Сериалы", st_favs:"Избранное", recent:"Недавно просмотренные", to_bot:"🤖 Вернуться в бот", language:"Язык",
    tag_series:"Сериал", min:"мин", n_eps:"{n} сер.", code_lbl:"Код фильма", play:"▶ Смотреть", play_ep:"▶ Смотреть · серия {n}",
    episodes:"Серии", fav_on:"♥ В избранном", fav_off:"♡ В избранное", share:"Поделиться", no_eps:"Серии ещё не добавлены",
    sent:"✅ Видео отправлено в бот", to_chat:"Перейти в чат", sub_alert:"Сначала подпишитесь на канал, затем попробуйте снова.",
    start_alert:"Сначала откройте бота и нажмите /start, затем попробуйте снова.", wait:"⏳ Подождите немного…", fail:"⚠️ Не удалось отправить, попробуйте позже"},
  en: {nav_home:"Home", nav_catalog:"Catalog", nav_search:"Search", nav_fav:"Saved", nav_profile:"Profile",
    loading:"Loading…", open_tg:"Open the Mini App inside Telegram", not_found:"Not found", error:"Error",
    pill:"Today's pick", details:"Details", rnd_t:"Don't know what to watch?", rnd_s:"Pick a random movie",
    sec_new:"New arrivals", sec_pop:"Popular", sec_series:"Series", sec_genres:"Genres", all:"See all",
    catalog:"Catalog", t_all:"All", t_movies:"Movies", t_series:"Series", s_new:"Newest", s_pop:"Most popular", s_name:"Title (A-Z)",
    g_all:"All genres", year_ph:"Year (e.g. 2024)", more:"Show more", nothing:"Nothing found", nothing_s:"Try changing the filters.",
    search:"Search", search_ph:"Movie or series title, or code", nf:"Not found", nf_s:"Try a different spelling or enter the code.",
    fav:"Saved", fav_empty:"Nothing saved yet", fav_empty_s:"Tap “Save” on a movie page.",
    user:"User", st_movies:"Movies", st_series:"Series", st_favs:"Saved", recent:"Recently watched", to_bot:"🤖 Back to the bot", language:"Language",
    tag_series:"Series", min:"min", n_eps:"{n} eps", code_lbl:"Movie code", play:"▶ Watch", play_ep:"▶ Watch · episode {n}",
    episodes:"Episodes", fav_on:"♥ Saved", fav_off:"♡ Save", share:"Share", no_eps:"No episodes yet",
    sent:"✅ Video sent to the bot", to_chat:"Open chat", sub_alert:"Please subscribe to the channel first, then try again.",
    start_alert:"Please open the bot and press /start first, then try again.", wait:"⏳ Please wait a moment…", fail:"⚠️ Couldn't send, please try later"},
};
const GN = {
  ru: {Jangari:"Боевик", Komediya:"Комедия", Drama:"Драма", Fantastika:"Фантастика", Triller:"Триллер", Sarguzasht:"Приключения", "Qo'rqinchli":"Ужасы", Romantika:"Мелодрама", Multfilm:"Мультфильм", Boshqa:"Другое"},
  en: {Jangari:"Action", Komediya:"Comedy", Drama:"Drama", Fantastika:"Sci-Fi", Triller:"Thriller", Sarguzasht:"Adventure", "Qo'rqinchli":"Horror", Romantika:"Romance", Multfilm:"Animation", Boshqa:"Other"},
};
const LANGS = {uz: "🇺🇿 O'zbekcha", ru: "🇷🇺 Русский", en: "🇬🇧 English"};
let LANG = "uz";
const T = (k, v) => ((I18N[LANG] || I18N.uz)[k] ?? I18N.uz[k] ?? k).replace(/\{(\w+)\}/g, (_, n) => v?.[n] ?? "");
const gname = g => (GN[LANG] || {})[g] || g;
const tgLang = () => { const c = (tg?.initDataUnsafe?.user?.language_code || "").slice(0, 2); return c === "ru" ? "ru" : c === "en" ? "en" : "uz"; };
function applyLang() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("nav a").forEach(a => { a.lastChild.nodeValue = T("nav_" + a.dataset.r); });
  document.querySelector("header .ico")?.setAttribute("aria-label", T("search"));
}
async function setLang(l) {
  try { await api("/lang", {method: "POST", body: JSON.stringify({lang: l})}); } catch (_) {}
  LANG = l; applyLang(); route();
}

async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {...opts, headers: {"Authorization": "tma " + (tg?.initData || ""), "Content-Type": "application/json", ...opts.headers}});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || "xatolik"), {status: r.status, data});
  return data;
}
function toast(text, withChat) {
  const t = document.getElementById("toast");
  t.hidden = false; t.style.display = "";
  t.innerHTML = `<span>${esc(text)}</span>` + (withChat ? `<button id="tchat">${esc(T("to_chat"))}</button>` : "");
  if (withChat) document.getElementById("tchat").onclick = () => tg?.close();
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; t.style.display = "none"; }, 5000);
}

const pimg = m => m.poster ? `<img class="pimg" loading="lazy" src="/poster/${encodeURIComponent(m.code)}?v=${m.poster}" onerror="this.remove()" alt="">` : "";
const EYE = '<svg class="eye" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
const card = m => `<a class="card" href="#/item/${encodeURIComponent(m.code)}"><div class="poster" style="--h:${hue(m.name)}"><span class="ph">${esc(m.name)}</span>${pimg(m)}${m.kind === "series" ? `<i class="tag">${esc(T("tag_series"))}</i>` : ""}${m.views ? `<span class="vw">${EYE}${m.views}</span>` : ""}</div><div class="t">${esc(m.name)}</div>${m.year ? `<div class="s">${m.year}</div>` : ""}</a>`;
const GI = {Jangari:"💥",Komediya:"😂",Drama:"🎭",Fantastika:"🚀",Triller:"🔪",Sarguzasht:"🧭","Qo'rqinchli":"👻",Romantika:"💘",Multfilm:"🧸"};
const row = (title, items, link) => items.length ? `<div class="sec"><h2>${title}</h2>${link ? `<a href="${link}">${esc(T("all"))}</a>` : ""}</div><div class="row">${items.map(card).join("")}</div>` : "";

// ---------- sahifalar ----------
async function home() {
  const d = await api("/home");
  const top = d.popular[0];
  view.innerHTML =
    (top ? `<a class="hero" style="--h:${hue(top.name)}" href="#/item/${encodeURIComponent(top.code)}">${pimg(top)}<div class="hin"><span class="pill">${esc(T("pill"))}</span><h3>${esc(top.name)}</h3><div class="meta">${esc([top.year, top.genres.map(gname).join(", ")].filter(Boolean).join(", "))}</div><span class="btn sm">${esc(T("details"))}</span></div></a>` : "") +
    `<button class="rnd" id="rnd"><b>${esc(T("rnd_t"))}</b><span>${esc(T("rnd_s"))}</span></button>` +
    row(T("sec_new"), d.latest, "#/catalog?sort=new&type=movie") + row(T("sec_pop"), d.popular, "#/catalog?sort=popular") + row(T("sec_series"), d.series, "#/catalog?type=series") +
    `<div class="sec"><h2>${esc(T("sec_genres"))}</h2></div><div class="chips" style="margin-top:0">${ME.genres.map(g => `<a class="chip" href="#/catalog?genre=${encodeURIComponent(g)}"><i>${GI[g] || "🎞"}</i>${esc(gname(g))}</a>`).join("")}</div>`;
  document.getElementById("rnd").onclick = async () => { const r = await api("/random"); if (r.code) location.hash = "#/item/" + encodeURIComponent(r.code); };
}

async function catalog(_, p) {
  const f = {type: p.get("type") || "all", genre: p.get("genre") || "", year: p.get("year") || "", sort: p.get("sort") || "new"};
  const sel = (id, opts, val) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === val ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  view.innerHTML = `<h1>${esc(T("catalog"))}</h1><div class="filters">
    ${sel("f-type", [["all", T("t_all")], ["movie", T("t_movies")], ["series", T("t_series")]], f.type)}
    ${sel("f-sort", [["new", T("s_new")], ["popular", T("s_pop")], ["name", T("s_name")]], f.sort)}
    ${sel("f-genre", [["", T("g_all")], ...ME.genres.map(g => [g, gname(g)])], f.genre)}
    <input id="f-year" type="number" inputmode="numeric" placeholder="${esc(T("year_ph"))}" value="${esc(f.year)}"></div>
    <div class="grid" id="grid"></div><button class="btn alt" id="more" hidden>${esc(T("more"))}</button>`;
  const apply = () => { const q = new URLSearchParams({type: $v("f-type"), sort: $v("f-sort"), genre: $v("f-genre"), year: $v("f-year")}); location.hash = "#/catalog?" + q; };
  ["f-type", "f-sort", "f-genre"].forEach(id => document.getElementById(id).onchange = apply);
  document.getElementById("f-year").onchange = apply;
  let offset = 0; const grid = document.getElementById("grid"), more = document.getElementById("more");
  async function load() {
    const d = await api("/catalog?" + new URLSearchParams({...f, offset, limit: 20}));
    grid.insertAdjacentHTML("beforeend", d.items.map(card).join(""));
    offset += d.items.length; more.hidden = !d.has_more;
    if (!offset) grid.innerHTML = '<div class="empty" style="grid-column:1/-1"><b>' + esc(T("nothing")) + '</b>' + esc(T("nothing_s")) + '</div>';
  }
  more.onclick = load; await load();
}
const $v = id => document.getElementById(id).value;

function search() {
  view.innerHTML = `<h1>${esc(T("search"))}</h1><input id="q" placeholder="${esc(T("search_ph"))}" autofocus><div class="grid" id="res" style="margin-top:14px"></div>`;
  const q = document.getElementById("q"), res = document.getElementById("res"); let timer;
  q.oninput = () => { clearTimeout(timer); timer = setTimeout(async () => {
    const t = q.value.trim(); if (t.length < 1) { res.innerHTML = ""; return; }
    const d = await api("/catalog?" + new URLSearchParams({q: t, limit: 30}));
    res.innerHTML = d.items.length ? d.items.map(card).join("") : '<div class="empty" style="grid-column:1/-1"><b>' + esc(T("nf")) + '</b>' + esc(T("nf_s")) + '</div>';
  }, 300); };
}

async function fav() {
  const d = await api("/favorites");
  view.innerHTML = `<h1>${esc(T("fav"))}</h1>` + (d.items.length ? `<div class="grid">${d.items.map(card).join("")}</div>` : `<div class="empty"><b>${esc(T("fav_empty"))}</b>${esc(T("fav_empty_s"))}</div>`);
}

async function profile() {
  ME = await api("/me");
  const u = tg?.initDataUnsafe?.user || {};
  const s = ME.stats;
  view.innerHTML = `<div class="prof">${u.photo_url ? `<img src="${esc(u.photo_url)}" alt="">` : '<div class="av"></div>'}
    <h1>${esc([u.first_name, u.last_name].filter(Boolean).join(" ") || T("user"))}</h1>
    <div class="muted">${u.username ? "@" + esc(u.username) + " · " : ""}ID: ${esc(u.id || "")}</div></div>
    <div class="stats"><div><b>${s.movies}</b>${esc(T("st_movies"))}</div><div><b>${s.series}</b>${esc(T("st_series"))}</div><div><b>${s.favs}</b>${esc(T("st_favs"))}</div></div>
    ${row(T("recent"), ME.recent)}
    <div class="sec"><h2>${esc(T("language"))}</h2></div>
    <div class="chips" style="margin-top:0">${Object.entries(LANGS).map(([c, n]) => `<button class="chip${c === LANG ? " act" : ""}" data-lang="${c}">${n}</button>`).join("")}</div>
    <button class="btn alt" id="tobot">${esc(T("to_bot"))}</button>`;
  view.onclick = e => { const b = e.target.closest("[data-lang]"); if (b) setLang(b.dataset.lang); };
  document.getElementById("tobot").onclick = () => tg?.close();
}

async function item(code) {
  const m = await api("/item/" + encodeURIComponent(code));
  const next = m.kind === "series" && m.episodes.length ? (m.episodes.find(n => n > (m.last_episode || 0)) || m.episodes[0]) : null;
  const playTxt = n => n ? T("play_ep", {n}) : T("play");
  const eps = m.episodes.length ? `<div class="sec"><h2>${esc(T("episodes"))}</h2></div><div class="eps">${m.episodes.map(n => `<button data-ep="${n}" class="${n === next ? "on" : n <= (m.last_episode || 0) ? "seen" : ""}">${n}</button>`).join("")}</div>` : "";
  view.innerHTML = `<div class="ibg" style="--h:${hue(m.name)}">${pimg(m)}</div>
    <div class="big" style="--h:${hue(m.name)}"><span>${esc(m.name[0] || "🎬")}</span>${pimg(m)}</div>
    <h1 class="ttl">${esc(m.name)}</h1>
    <div class="facts">${[m.year, m.duration && m.duration + " " + T("min"), m.kind === "series" && T("n_eps", {n: m.episodes.length})].filter(Boolean).map(x => `<span>${esc(x)}</span>`).join("")}<span class="vw">${EYE}${m.views}</span></div>
    ${m.genres.length ? `<div class="chips" style="justify-content:center">${m.genres.map(g => `<span class="chip">${esc(gname(g))}</span>`).join("")}</div>` : ""}
    <div class="ticket"><span>${esc(T("code_lbl"))}</span><b>${esc(m.code)}</b></div>
    ${m.description ? `<p class="desc">${esc(m.description)}</p>` : ""}
    ${m.kind === "movie" || next ? `<button class="btn" id="play">${playTxt(next)}</button>` : `<p class="muted">${esc(T("no_eps"))}</p>`}
    <div class="two"><button class="btn alt" id="fav">${m.fav ? T("fav_on") : T("fav_off")}</button><button class="btn alt" id="share">${esc(T("share"))}</button></div>
    ${eps}${ME.is_admin ? posterBtn() + adminForm(m) : ""}`;
  let sel = next;
  const play = document.getElementById("play");
  const setSel = n => { sel = n; view.querySelectorAll(".eps button").forEach(b => b.classList.toggle("on", +b.dataset.ep === n)); if (play) play.textContent = playTxt(n); };
  view.onclick = e => { const b = e.target.closest(".eps [data-ep]"); if (b) setSel(+b.dataset.ep); };
  if (play) play.onclick = async () => {
    if (!(await watch(m.code, sel))) return;
    if (sel) {  // yuborilgan qism "ko'rilgan" bo'ladi, keyingisi avtomatik tanlanadi
      view.querySelector(`.eps [data-ep="${sel}"]`)?.classList.add("seen");
      const n = m.episodes[m.episodes.indexOf(sel) + 1]; if (n) setSel(n);
    }
  };
  document.getElementById("fav").onclick = async e => { const r = await api("/fav", {method: "POST", body: JSON.stringify({code: m.code})}); e.target.textContent = r.fav ? T("fav_on") : T("fav_off"); };
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
    toast(T("sent"), true);
    return true;
  } catch (e) {
    const d = e.data || {};
    if (d.error === "subscribe") { const l = d.channels?.[0]; tg ? tg.showAlert(T("sub_alert"), () => l && tg.openLink(l)) : alert(T("sub_alert")); }
    else if (d.error === "start_bot") { tg ? tg.showAlert(T("start_alert"), () => tg.close()) : alert(T("start_alert")); }
    else if (d.error === "too_fast") toast(T("wait"));
    else toast(T("fail"));
  }
  return false;
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
  catch (e) { view.innerHTML = `<p class="err">${e.status === 404 ? T("not_found") : T("error") + ": " + esc(e.message)}</p>`; }
  window.scrollTo(0, 0);
}
tg?.BackButton.onClick(() => history.back());
addEventListener("hashchange", route);
(async () => {
  try {
    LANG = tgLang(); applyLang();
    if (!tg?.initData) throw Object.assign(new Error(T("open_tg")), {});
    ME = await api("/me");
    LANG = ME.lang || tgLang();
    applyLang();
    const sp = tg.initDataUnsafe?.start_param;
    if (sp) { try { location.hash = "#/item/" + encodeURIComponent(b64d(sp)); return; } catch (_) {} }
    route();
  } catch (e) { view.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
})();
