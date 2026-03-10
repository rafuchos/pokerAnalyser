/* Poker Analyzer Web UI – client-side helpers */

document.addEventListener('DOMContentLoaded', function () {
    // Highlight active sub-nav on scroll (future use)
    // Currently tabs are server-rendered via Jinja2

    // Accordion toggles (for session cards, if present)
    document.querySelectorAll('[data-toggle="accordion"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var target = document.getElementById(btn.dataset.target);
            if (target) {
                target.classList.toggle('collapsed');
                btn.classList.toggle('expanded');
            }
        });
    });
});
