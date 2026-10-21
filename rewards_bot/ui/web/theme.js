"use strict";
// Chạy trước khi vẽ trang: đặt sáng/tối theo Windows để không bị nháy trắng. app.js áp lại theo cài đặt sau khi khởi động.
(function () {
  const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
})();
