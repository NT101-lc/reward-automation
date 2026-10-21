"use strict";
// Giao diện Rewards Bot (Tabler + ApexCharts). Mọi dữ liệu đến từ Python (window.pywebview.api) và sự kiện window.onEvents.

const S = { settings: {}, profiles: [], pstate: {}, history: {}, running: new Set(),
            logs: [], unreadErr: 0, selected: null, page: "dashboard" };
const api = () => window.pywebview.api;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// chỉ hiển thị ảnh https từ bing.com (dữ liệu lấy từ trang web bên ngoài nên không tin tuyệt đối)
const safeImg = (u) => (/^https:\/\/([a-z0-9-]+\.)*bing\.com\//i.test(u || "") ? u : "");
const fmt = (n) => (n === null || n === undefined || n === "" ? "—" : Number(n).toLocaleString("en-US"));
const SERIES = [["pc", "Search PC", "#2a78d6"], ["mobile", "Search Mobile", "#eb6834"], ["offers", "Offers", "#1baf7a"]];
// bảng màu biểu đồ của giao diện Cyberpunk (cyan / hồng / vàng neon)
const CYBER_COLORS = { pc: "#05d9e8", mobile: "#ff2a6d", offers: "#fcee0a", balance: "#fcee0a" };
const isCyber = () => document.documentElement.getAttribute("data-skin") === "cyberpunk";
const seriesColor = (k) => (isCyber() ? CYBER_COLORS[k] : (SERIES.find((x) => x[0] === k) || [, , "#2a78d6"])[2]);
const RUN_STATES = ["Đang chạy", "Đang chờ", "Đang làm mới", "Đang đăng nhập", "Đang kiểm tra"];
const GROUP_ORDER = ["Tìm kiếm", "Daily Set", "Keep earning", "Hoạt động", "Task thêm"];
const img = (u, cls = "") => (safeImg(u) ? `<img class="${cls}" src="${esc(safeImg(u))}" alt="" loading="lazy">` : "");

// ảnh từ Rewards lỗi -> ẩn đi (CSP không cho onerror nội tuyến nên bắt chung ở document)
document.addEventListener("error", (e) => { if (e.target.tagName === "IMG") e.target.classList.add("broken"); }, true);

// ===================================================================== khởi động
window.addEventListener("pywebviewready", async () => {
  const b = await api().bootstrap();
  Object.assign(S, b, { running: new Set(b.running) });
  S.selected = S.profiles[0]?.name ?? null;
  bindStatic();
  applyTheme();
  renderAll();
});

window.onEvents = (batch) => {
  let dirty = false;
  for (const e of batch) {
    if (e.type === "log") {
      S.logs.push(e);
      if (/^\s*(lỗi|cảnh báo)/i.test(e.msg)) S.unreadErr++;
      if (S.page === "log") appendLog(e);
    } else if (e.type === "status") {
      const st = (S.pstate[e.name] ||= {});
      Object.assign(st, e.data);
      if (e.history) S.history[e.name] = e.history;
      if (RUN_STATES.includes(e.data.state)) S.running.add(e.name);
      dirty = true;
    } else if (e.type === "done") {
      S.running.delete(e.name); dirty = true;
    }
  }
  if (S.logs.length > 4000) S.logs = S.logs.slice(-3000);
  if (dirty) { renderSide(); if (S.page === "dashboard") renderDashboard(); if (S.page === "profiles") renderProfiles(); }
  renderLogBadge();
};

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
}

// ===================================================================== sáng / tối
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const isDark = () => document.documentElement.getAttribute("data-bs-theme") === "dark";
function applyTheme() {
  const mode = S.settings.theme || "system";
  const cyber = mode === "cyberpunk";  // Cyberpunk luôn là nền tối + lớp giao diện riêng (cyberpunk.css)
  const dark = cyber || mode === "dark" || (mode === "system" && darkQuery.matches);
  const changed = isDark() !== dark || isCyber() !== cyber;
  document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
  if (cyber) document.documentElement.setAttribute("data-skin", "cyberpunk");
  else document.documentElement.removeAttribute("data-skin");
  $$(".theme-switch button").forEach((b) => b.classList.toggle("active", b.dataset.theme === mode));
  $$("#theme-choice input").forEach((i) => (i.checked = i.value === mode));
  if (changed && S.page === "dashboard") { Charts.reset(); renderDashboard(); }
}
async function setTheme(mode) {
  S.settings.theme = mode; applyTheme();  // đổi ngay, lưu sau
  await saveSettings({ theme: mode });
}
darkQuery.addEventListener("change", () => (S.settings.theme || "system") === "system" && applyTheme());

// ===================================================================== điều hướng + nút cố định
function bindStatic() {
  $$("#nav [data-page]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); go(b.dataset.page); }));
  $$(".theme-switch button").forEach((b) => (b.onclick = () => setTheme(b.dataset.theme)));
  $$("#theme-choice input").forEach((i) => (i.onchange = () => setTheme(i.value)));
  $("#btn-refresh").onclick = () => S.selected && start([S.selected], "refresh");
  $("#btn-check").onclick = () => S.selected && start([S.selected], "check");
  $("#btn-run-one").onclick = () => S.selected && start([S.selected], "run");
  $("#btn-run-all").onclick = () => start(null, "run");
  $("#btn-stop-all").onclick = async () => { await api().stop(null); toast("Đã gửi lệnh dừng"); };
  $("#btn-add").onclick = () => openProfileDialog(null);
  $("#btn-clear-log").onclick = () => { S.logs = []; S.unreadErr = 0; renderLog(); renderLogBadge(); };
  $("#btn-copy-log").onclick = copyLog;
  $("#log-filter").onchange = renderLog;
  $("#btn-save-settings").onclick = saveSettingsForm;
  $("#max-parallel").onchange = (e) => saveSettings({ max_parallel: Math.max(1, +e.target.value || 1) });
  bindProfileDialog();
}

function go(page) {
  S.page = page;
  $$("#nav [data-page]").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".view").forEach((p) => (p.hidden = p.id !== "page-" + page));
  if (page === "log") S.unreadErr = 0;
  if (page === "dashboard") Charts.reset();  // vẽ lại theo kích thước thật sau khi trang hiện ra
  renderAll();
  window.scrollTo(0, 0);
}

async function start(names, action) {
  const r = await api().start(names, action);
  if (r.ok === false) { toast(r.error); return; }
  r.running.forEach((n) => S.running.add(n));
  renderSide(); renderDashboard(); renderProfiles();
  toast({ run: "Bắt đầu chạy", refresh: "Đang làm mới điểm", login: "Đã mở cửa sổ đăng nhập",
          check: "Đang kiểm tra (không search)" }[action]);
}

function renderAll() {
  renderSide();
  if (S.page === "dashboard") renderDashboard();
  if (S.page === "profiles") renderProfiles();
  if (S.page === "log") renderLog();
  if (S.page === "settings") renderSettings();
  renderLogBadge();
}

function renderSide() {
  $("#brand-sub").textContent = `${S.profiles.length} tài khoản`;
  const on = S.running.size > 0;
  $("#run-state").classList.toggle("on", on);
  $("#run-state span:last-child").textContent = on ? `Đang chạy ${S.running.size} tài khoản` : "Đang nghỉ";
}

function renderLogBadge() {
  const b = $("#log-badge");
  b.hidden = !S.unreadErr || S.page === "log";
  b.textContent = S.unreadErr;
}

const initials = (n) => n.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const st = (name) => S.pstate[name] || {};

function statePill(name) {
  const s = st(name).state || "Sẵn sàng";
  const cls = RUN_STATES.includes(s) ? "bg-blue-lt" : s === "Hoàn thành" ? "bg-green-lt"
    : ["Lỗi", "Chưa đăng nhập"].includes(s) ? "bg-red-lt" : "bg-secondary-lt";
  return `<span class="badge ${cls}">${esc(s)}</span>`;
}
const doneBadge = (done) => `<span class="badge ${done ? "bg-green-lt" : "bg-yellow-lt"}">${done ? "Xong" : "Chưa xong"}</span>`;
const bar = (pct, color) => `<div class="progress"><div class="progress-bar" style="width:${Math.min(100, Math.max(0, pct))}%${color ? `;background:${color}` : ""}"></div></div>`;

// ===================================================================== tổng quan
function renderDashboard() {
  const chips = $("#profile-chips");
  if (!S.profiles.length) {
    chips.innerHTML = `<button class="btn btn-primary" id="btn-first-profile"><i class="ti ti-user-plus"></i>Thêm tài khoản đầu tiên</button>`;
    $("#btn-first-profile").addEventListener("click", () => { go("profiles"); openProfileDialog(null); });
  } else {
    chips.innerHTML = S.profiles.map((p) => `
      <button class="chip ${p.name === S.selected ? "active" : ""}" data-name="${esc(p.name)}">
        <span class="avatar avatar-sm rounded-circle ${S.running.has(p.name) ? "run" : ""}">${esc(initials(p.name))}</span>
        <span>${esc(p.name)}</span><span class="pts">${fmt(st(p.name).points)}</span>
      </button>`).join("");
    $$(".chip", chips).forEach((c) => (c.onclick = () => { S.selected = c.dataset.name; Charts.reset(); renderDashboard(); }));
  }
  const name = S.selected;
  const s = st(name);
  const stats = s.stats || {};
  $("#hero-avatar").textContent = name ? initials(name) : "";
  $("#hero-name").textContent = name || "Chưa có tài khoản";
  $("#hero-state").textContent = name ? `${s.state || "Sẵn sàng"}${s.progress ? " · " + s.progress : ""}` : "";
  $("#hero-points").textContent = fmt(s.points);
  $("#hero-today").textContent = s.today != null ? "+" + fmt(s.today) : "—";
  $("#hero-month").textContent = fmt(stats.month);
  $("#hero-life").textContent = fmt(stats.lifetime);
  for (const id of ["#btn-run-one", "#btn-refresh", "#btn-check"]) $(id).disabled = !name || S.running.has(name);
  renderCheck(s);
  $("#tasks-updated").textContent = s.updated ? "Cập nhật " + s.updated : "";
  renderStamps(s);
  renderStreak(s);
  renderMeters(s);
  renderTasks(s);
  renderCharts(name);
}

function renderCheck(s) {
  const panel = $("#check-panel");
  if (!s.check || !s.check.length) { panel.hidden = true; return; }
  panel.hidden = false;
  $("#check-time").textContent = s.check_time ? "Lúc " + s.check_time : "";
  const sign = { ok: "ti-check", warn: "ti-exclamation-mark", fail: "ti-x" };
  $("#check-list").innerHTML = s.check.map((c) => `
    <li class="list-group-item ${esc(c.level)}"><span class="mark"><i class="ti ${sign[c.level] || "ti-question-mark"}"></i></span>
      <span class="ct">${esc(c.title)}</span><span class="cd">${esc(c.detail)}</span></li>`).join("");
}

function renderStamps(s) {
  // mỗi task có điểm của hôm nay là 1 con dấu: search PC/Mobile, Daily Set, Keep earning
  const tasks = (s.tasks || []).filter((t) => ["Tìm kiếm", "Daily Set", "Keep earning"].includes(t.group));
  const box = $("#stamps");
  if (!tasks.length) {
    box.innerHTML = `<p class="empty-note w-100">Chưa có dữ liệu. Bấm <b>Làm mới</b> để đọc task hôm nay từ Rewards.</p>`;
    $("#stamp-count").textContent = "";
    return;
  }
  const done = tasks.filter((t) => t.done).length;
  $("#stamp-count").textContent = `${done}/${tasks.length} dấu`;
  box.innerHTML = tasks.map((t) => `
    <div class="stamp ${t.done ? "done" : ""}" title="${esc(t.title)} · ${t.done ? "Đã xong" : "Chưa làm"} · +${t.max} điểm">
      <div class="stamp-wrap"><div class="disc">${img(t.img) || `<span class="fallback">${esc(initials(t.title))}</span>`}</div>
      <span class="check"><i class="ti ti-check"></i></span></div>
      <span class="pts">+${t.max}</span>
    </div>`).join("");
}

function renderStreak(s) {
  // Stamp bonus của Rewards: đủ 12 dấu (từ các chuỗi streak) thì được thưởng (thường +1.000 điểm)
  const info = s.streak || {};
  const stamps = info.stamps, streaks = info.streaks || [];
  const panel = $("#streak-panel");
  if (!stamps && !streaks.length) { panel.hidden = true; return; }
  panel.hidden = false;
  const have = stamps?.progress ?? 0, max = stamps?.max || 12, bonus = stamps?.bonus || 1000;
  const left = Math.max(0, max - have);
  $("#streak-sub").textContent = stamps ? `${have}/${max} dấu` : "";
  $("#daily-streak").innerHTML = info.daily_streak != null
    ? `<span class="flame"><i class="ti ti-flame"></i></span><div><b>${fmt(info.daily_streak)} ngày</b><span>Daily streak liên tiếp</span></div>` : "";
  $("#stamp-grid").setAttribute("aria-label", `${have} trên ${max} dấu`);
  $("#stamp-grid").innerHTML = Array.from({ length: max }, (_, i) =>
    `<span class="sdot ${i < have ? "on" : i === have ? "next" : ""}"><i class="ti ${i < have ? "ti-star-filled" : "ti-star"}"></i></span>`).join("");
  $("#streak-hint").innerHTML = !stamps ? "Chưa đọc được số dấu."
    : left ? `Còn <b>${left}</b> dấu nữa để nhận <b>+${fmt(bonus)}</b> điểm. Giữ các chuỗi streak bên cạnh mỗi ngày để nhận dấu.`
    : `Đã đủ ${max} dấu: vào Rewards để nhận <b>+${fmt(bonus)}</b> điểm.`;
  $("#streak-list").innerHTML = streaks.map((r) => {
    // giống trang Rewards: 7 ô cho 7 ngày; ô đã xong tô vàng, ô hôm nay viền nổi
    const n = r.of || 7, day = Math.min(r.day, n);
    const todayIdx = r.today_done ? day - 1 : day;
    const days = Array.from({ length: n }, (_, i) =>
      `<span class="sday ${i < day ? "on" : ""} ${i === todayIdx ? "today" : ""}" title="Ngày ${i + 1}">${i < day ? '<i class="ti ti-check"></i>' : i + 1}</span>`).join("");
    const status = r.today_done ? `<span class="badge bg-green-lt">Hôm nay xong</span>`
      : `<span class="badge bg-yellow-lt">Hôm nay chưa${r.today ? " · " + esc(r.today) : ""}</span>`;
    return `<div class="streak-row">${img(r.img) || `<span class="ico"></span>`}
      <div class="min-w-0"><div class="t text-truncate">${esc(r.title)}</div>
        <div class="sub">Ngày ${r.day}/${n}${r.next ? ` · ngày tới +${r.next} điểm` : ""}</div></div>
      ${status}
      <div class="days">${days}</div></div>`;
  }).join("");
}

function renderMeters(s) {
  const stats = s.stats || {};
  const icons = s.icons || {};
  const rows = [["pc", "Search PC", icons["Tìm kiếm"]], ["mobile", "Search Mobile", icons["Mobile"]]];
  const findImg = (title) => (s.tasks || []).find((t) => t.title === title)?.img;
  $("#meters").innerHTML = rows.map(([k, label, ic]) => {
    const p = stats[k], m = stats[k + "_max"], color = seriesColor(k);
    return `<div class="meter">${img(findImg(label) || ic) || `<span class="ico"></span>`}
      <span class="label">${label}</span><span class="val">${m ? `${p}/${m} điểm` : "chưa có dữ liệu"}</span>
      ${bar(m ? (p / m) * 100 : 0, color)}</div>`;
  }).join("");
}

function renderTasks(s) {
  const tasks = s.tasks || [];
  const box = $("#task-groups");
  if (!tasks.length) { box.innerHTML = `<p class="empty-note">Chưa có dữ liệu task cho tài khoản này.</p>`; return; }
  const groups = {};
  tasks.forEach((t) => (groups[t.group] ||= []).push(t));
  const icons = s.icons || {};
  box.innerHTML = Object.keys(groups)
    .sort((a, b) => (GROUP_ORDER.indexOf(a) + 99) % 99 - (GROUP_ORDER.indexOf(b) + 99) % 99)
    .map((g) => {
      const items = groups[g], d = items.filter((t) => t.done).length;
      return `<div class="tgroup"><h3>${img(icons[g] || items[0]?.img)}${esc(g)}<span class="count">${d}/${items.length} xong</span></h3>
        ${items.map((t) => `<div class="task">
            ${img(t.img, "thumb") || `<span class="thumb"></span>`}
            <div class="min-w-0"><div class="t" title="${esc(t.title)}">${esc(t.title)}</div>
              <div class="sub">${t.progress}/${t.max} ${esc(t.unit || "điểm")}${t.bot ? ` <span class="botnote">· ${esc(t.bot)}</span>` : ""}</div>
              ${bar(t.max ? (t.progress / t.max) * 100 : 0, t.done ? "var(--tblr-success)" : "")}</div>
            ${doneBadge(t.done)}</div>`).join("")}</div>`;
    }).join("");
}

// ===================================================================== biểu đồ (ApexCharts)
const Charts = {
  inst: {}, keys: {},
  reset() { for (const k in this.inst) { this.inst[k].destroy(); } this.inst = {}; this.keys = {}; },
  // chỉ vẽ lại khi dữ liệu / theme đổi (sự kiện trạng thái đến liên tục khi bot chạy)
  draw(id, key, make) {
    const el = $("#" + id);
    if (this.keys[id] === key && this.inst[id]) return;
    if (this.inst[id]) { this.inst[id].destroy(); delete this.inst[id]; }
    this.keys[id] = key;
    const opts = make();
    if (!opts) return;
    el.innerHTML = "";
    this.inst[id] = new ApexCharts(el, opts);
    this.inst[id].render();
  },
};
function chartBase() {
  const dark = isDark();
  return {
    chart: { height: 250, toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false },
             fontFamily: "inherit", background: "transparent", foreColor: isCyber() ? "#8b96c4" : dark ? "#9aa6b8" : "#6b7385" },
    theme: { mode: dark ? "dark" : "light" },
    grid: { borderColor: isCyber() ? "rgba(5,217,232,.12)" : dark ? "rgba(255,255,255,.07)" : "#eef0f5", strokeDashArray: 3, padding: { left: 6, right: 6 } },
    dataLabels: { enabled: false },
    tooltip: { theme: dark ? "dark" : "light" },
    legend: { position: "top", horizontalAlign: "right", fontSize: "12px", markers: { size: 5 } },
  };
}
function emptyChart(id, msg) {
  if (Charts.inst[id]) { Charts.inst[id].destroy(); delete Charts.inst[id]; }
  Charts.keys[id] = "empty";
  $("#" + id).innerHTML = `<div class="empty">${msg}</div>`;
}
function renderCharts(name) {
  const hist = S.history[name] || {};
  const days = Object.keys(hist).sort();
  const lab = (d) => `${d.slice(8, 10)}/${d.slice(5, 7)}`;
  const theme = isCyber() ? "c" : isDark() ? "d" : "l";
  const d14 = days.slice(-14);
  if (!d14.length) emptyChart("chart-daily", "Chưa có lịch sử. Mỗi lần chạy hoặc làm mới sẽ ghi lại điểm của ngày đó.");
  else Charts.draw("chart-daily", theme + JSON.stringify(d14.map((d) => [d, hist[d].pc, hist[d].mobile, hist[d].offers])), () => ({
    ...chartBase(),
    chart: { ...chartBase().chart, type: "bar", stacked: true },
    colors: SERIES.map(([k]) => seriesColor(k)),
    series: SERIES.map(([k, l]) => ({ name: l, data: d14.map((d) => hist[d][k] || 0) })),
    xaxis: { categories: d14.map(lab), axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { labels: { formatter: (v) => fmt(Math.round(v)) } },
    plotOptions: { bar: { columnWidth: "45%", borderRadius: 4, borderRadiusApplication: "end", borderRadiusWhenStacked: "last" } },
  }));
  const d30 = days.slice(-30).filter((d) => hist[d].available != null);
  if (!d30.length) emptyChart("chart-balance", "Chưa có lịch sử điểm.");
  else Charts.draw("chart-balance", theme + JSON.stringify(d30.map((d) => [d, hist[d].available])), () => ({
    ...chartBase(),
    chart: { ...chartBase().chart, type: "area" },
    colors: [seriesColor("balance")],
    series: [{ name: "Điểm", data: d30.map((d) => hist[d].available) }],
    stroke: { width: 2.5, curve: "smooth" },
    fill: { type: "gradient", gradient: { opacityFrom: 0.35, opacityTo: 0.02 } },
    markers: { size: d30.length < 3 ? 5 : 0, hover: { size: 5 } },
    xaxis: { categories: d30.map(lab), axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { labels: { formatter: (v) => fmt(Math.round(v)) } },
    legend: { show: false },
  }));
}
window.addEventListener("resize", () => { clearTimeout(window._rz); window._rz = setTimeout(() => S.page === "dashboard" && (Charts.reset(), renderDashboard()), 200); });

// ===================================================================== tài khoản
function renderProfiles() {
  const tb = $("#profile-table tbody");
  if (!S.profiles.length) {
    tb.innerHTML = `<tr><td colspan="8" class="empty-note">Chưa có tài khoản. Bấm <b>Thêm tài khoản</b>, rồi <b>Đăng nhập</b> một lần.</td></tr>`;
  } else {
    const ib = (act, icon, label, cls = "") => `<button class="btn btn-sm ${cls}" data-act="${act}" title="${label}"><i class="ti ${icon}"></i>${label}</button>`;
    tb.innerHTML = S.profiles.map((p) => {
      const s = st(p.name), run = S.running.has(p.name);
      return `<tr data-name="${esc(p.name)}">
        <td><span class="avatar avatar-sm rounded-circle ${run ? "run" : ""}">${esc(initials(p.name))}</span></td>
        <td><b>${esc(p.name)}</b></td>
        <td class="text-secondary">${p.mode === "cdp" ? `Edge đang mở · cổng ${p.cdp_port}` : "Cửa sổ riêng"}</td>
        <td>${statePill(p.name)}</td>
        <td class="text-end">${fmt(s.points)}</td>
        <td class="text-end">${s.today != null ? "+" + fmt(s.today) : "—"}</td>
        <td class="text-secondary small">${esc(s.progress || "")}</td>
        <td><div class="row-actions">
          ${run ? ib("stop", "ti-player-stop", "Dừng", "btn-outline-danger")
                : ib("run", "ti-player-play", "Chạy", "btn-primary") + ib("check", "ti-stethoscope", "Kiểm tra")
                  + ib("login", "ti-login", "Đăng nhập") + ib("edit", "ti-pencil", "Sửa") + ib("del", "ti-trash", "Xóa", "btn-ghost-danger")}
        </div></td></tr>`;
    }).join("");
    $$("button[data-act]", tb).forEach((b) => (b.onclick = async () => {
      const name = b.closest("tr").dataset.name;
      const act = b.dataset.act;
      if (act === "run") start([name], "run");
      else if (act === "login") start([name], "login");
      else if (act === "check") { S.selected = name; start([name], "check"); }
      else if (act === "stop") { await api().stop([name]); toast("Đang dừng " + name); }
      else if (act === "edit") openProfileDialog(S.profiles.find((p) => p.name === name));
      else if (act === "del" && confirm(`Xóa tài khoản "${name}" khỏi app?\nPhiên đăng nhập trong data/profiles vẫn được giữ.`)) {
        const r = await api().delete_profiles([name]); S.profiles = r.profiles;
        if (S.selected === name) S.selected = S.profiles[0]?.name ?? null;
        renderAll();
      }
    }));
  }
  renderToggles();
  $("#max-parallel").value = S.settings.max_parallel;
}

function renderToggles() {
  const ic = st(S.selected).icons || {};
  const any = (k) => Object.values(S.pstate).map((s) => (s.icons || {})[k]).find(Boolean);
  const items = [
    ["do_quests", "Daily Set, Keep earning", "Bấm từng thẻ task, làm quiz và poll", ic["Daily Set"] || any("Daily Set"), "ti-cards"],
    ["do_pc", "Search PC", "Tìm đến khi đủ điểm search máy tính", ic["Tìm kiếm"] || any("Tìm kiếm"), "ti-device-desktop"],
    ["do_mobile", "Search Mobile", "Giả lập điện thoại, tìm đến khi đủ điểm", ic["Mobile"] || any("Mobile"), "ti-device-mobile"],
    ["do_visual", "Visual Search", "Tìm bằng 1 ảnh qua nút camera của Bing (mỗi ngày 1 lượt)", ic["Visual Search"] || any("Visual Search"), "ti-camera"],
    ["do_browse", "Browse", `Lướt web ${S.settings.browse_minutes} phút. Không làm lên Edge – Minutes (mục đó phải tự dùng Edge)`, "", "ti-world"],
    ["headless", "Chạy ẩn", "Không hiện cửa sổ trình duyệt", "", "ti-eye-off"],
  ];
  $("#task-toggles").innerHTML = items.map(([k, t, d, im, ti]) => `
    <label class="list-group-item toggle-item">${img(im) || `<span class="ico"><i class="ti ${ti}"></i></span>`}
      <div><div class="tt">${t}</div><div class="td">${d}</div></div>
      <span class="form-check form-switch"><input class="form-check-input" type="checkbox" data-key="${k}" ${S.settings[k] ? "checked" : ""}></span></label>`).join("");
  $$("#task-toggles input").forEach((i) => (i.onchange = () => saveSettings({ [i.dataset.key]: i.checked })));
}

async function saveSettings(partial) {
  const r = await api().save_settings(partial);
  S.settings = r.settings;
  if (!r.ok) toast(r.error);
  return r.ok;
}

function bindProfileDialog() {
  const dlg = $("#profile-dialog"), f = $("#profile-form");
  const syncPort = () => ($("#pd-port").hidden = f.mode.value !== "cdp");
  $$("input[name=mode]", f).forEach((r) => (r.onchange = syncPort));
  f.onsubmit = async (e) => {
    if (e.submitter?.value !== "ok") return;
    e.preventDefault();
    const r = await api().save_profile(dlg.dataset.old || null,
      { name: f.name.value, mode: f.mode.value, cdp_port: +f.cdp_port.value });
    if (!r.ok) { $("#pd-error").textContent = r.error; return; }
    if (S.selected === dlg.dataset.old || !S.selected) S.selected = f.name.value.trim();
    S.profiles = r.profiles; dlg.close(); renderAll();
    toast(dlg.dataset.old ? "Đã lưu tài khoản" : "Đã thêm tài khoản. Bấm Đăng nhập để đăng nhập lần đầu.");
  };
  dlg._sync = syncPort;
}

function openProfileDialog(p) {
  const dlg = $("#profile-dialog"), f = $("#profile-form");
  dlg.dataset.old = p ? p.name : "";
  $("#pd-title").textContent = p ? "Sửa tài khoản" : "Thêm tài khoản";
  f.name.value = p ? p.name : `Tài khoản ${S.profiles.length + 1}`;
  f.mode.value = p ? p.mode : "managed";
  f.cdp_port.value = p ? p.cdp_port : 9222 + S.profiles.length;
  $("#pd-error").textContent = "";
  dlg._sync(); dlg.showModal(); f.name.select();
}
window.openProfileDialog = openProfileDialog; window.go = go;

// ===================================================================== nhật ký
const logFilter = () => $("#log-filter").value;
function renderLog() {
  const sel = $("#log-filter"), cur = sel.value || "";
  sel.innerHTML = `<option value="">Tất cả tài khoản</option>` + S.profiles.map((p) => `<option ${p.name === cur ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  const box = $("#logbox"); box.innerHTML = "";
  S.logs.filter((l) => !cur || l.name === cur).slice(-1500).forEach(appendLog);
  if (!S.logs.length) box.innerHTML = `<div class="l tm">Chưa có nhật ký. Khi bot chạy, từng bước sẽ hiện ở đây.</div>`;
}
function appendLog(e) {
  const cur = logFilter();
  if (cur && e.name !== cur) return;
  const box = $("#logbox"), atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const d = document.createElement("div");
  d.className = "l";
  d.innerHTML = `<span class="tm">${esc(e.time)}</span> <span class="nm">${esc(e.name)}</span> <span class="${/^\s*(lỗi|cảnh báo)/i.test(e.msg) ? "er" : ""}">${esc(e.msg)}</span>`;
  box.appendChild(d);
  if (atBottom) box.scrollTop = box.scrollHeight;
}
async function copyLog() {
  const cur = logFilter();
  const text = S.logs.filter((l) => !cur || l.name === cur).map((l) => `${l.time} [${l.name}] ${l.msg}`).join("\n");
  if (!text) { toast("Nhật ký đang trống"); return; }
  try { await navigator.clipboard.writeText(text); toast("Đã sao chép nhật ký"); }
  catch { // dự phòng khi clipboard API bị chặn: chọn sẵn chữ để Ctrl+C
    const r = document.createRange(); r.selectNodeContents($("#logbox"));
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    toast("Đã chọn toàn bộ nhật ký, bấm Ctrl+C để sao chép");
  }
}

// ===================================================================== cài đặt
const SETTING_FIELDS = [
  ["search_delay_min", "Nghỉ ít nhất giữa 2 lượt search (giây)"],
  ["search_delay_max", "Nghỉ nhiều nhất giữa 2 lượt search (giây)"],
  ["extra_searches", "Số lượt search thêm cho chắc đủ điểm"],
  ["browse_minutes", "Thời gian browse (phút)"],
  ["history_days", "Không lặp lại câu search đã dùng trong (ngày)"],
];
function renderSettings() {
  $("#settings-form").innerHTML = `<div class="settings-grid">` + SETTING_FIELDS.map(([k, l]) =>
    `<label for="set-${k}" class="form-label m-0">${l}</label><input type="number" class="form-control" min="0" id="set-${k}" data-key="${k}" value="${esc(S.settings[k])}">`).join("")
    + `<label for="set-browser" class="form-label m-0">Trình duyệt cho cửa sổ riêng</label>
       <select id="set-browser" class="form-select">${[["msedge", "Microsoft Edge"], ["chrome", "Google Chrome"], ["", "Chromium"]]
        .map(([v, t]) => `<option value="${v}" ${S.settings.browser_channel === v ? "selected" : ""}>${t}</option>`).join("")}</select>
       </div>
       <label class="form-check form-switch mt-4 mb-0">
         <input class="form-check-input" type="checkbox" id="set-bypass-proxy" ${S.settings.bypass_proxy !== false ? "checked" : ""}>
         <span class="form-check-label">Không đi qua proxy hệ thống (chặn proxy chen giữa)</span></label>`;
  $$("#theme-choice input").forEach((i) => (i.checked = i.value === (S.settings.theme || "system")));
}
async function saveSettingsForm() {
  const partial = { browser_channel: $("#set-browser").value };
  for (const i of $$("#settings-form input[data-key]")) {
    const v = parseInt(i.value, 10);
    if (Number.isNaN(v) || v < 0) { toast("Ô “" + i.previousElementSibling.textContent + "” cần là số không âm"); i.focus(); return; }
    partial[i.dataset.key] = v;
  }
  partial.bypass_proxy = $("#set-bypass-proxy").checked;
  const ok = await saveSettings(partial);
  renderSettings();
  if (ok) toast("Đã lưu cài đặt");
}
