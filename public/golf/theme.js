/* Runs before the page paints: applies a saved Light or Dark choice so the page never flashes the
   wrong colours. With no saved choice ("Match device") the stylesheet follows the device setting. */
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("golf-theme");
  } catch (error) {
    theme = null;
  }
  if (theme === "light" || theme === "dark") {
    document.documentElement.setAttribute("data-theme", theme);
  }
})();
