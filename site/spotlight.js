// Spotlight banner: an opportunity we pass along from another organization.
// Each banner carries data-until (an ISO time). Once that time passes, the
// banner removes itself, so the site never advertises a closed deadline.
(function () {
  var now = Date.now();
  document.querySelectorAll('[data-until]').forEach(function (el) {
    var until = Date.parse(el.getAttribute('data-until'));
    if (!isNaN(until) && now >= until) el.remove();
  });
})();
