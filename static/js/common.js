/* ===== Common JS — shared across all Chata pages ===== */

/* --- Page-load overlay --- */
function hidePageLoadOverlay() {
    var overlay = document.getElementById('pageLoadOverlay');
    if (overlay) overlay.classList.add('hidden');
}

/* --- Interactive grid --- */
var grid = null;
var ticking = false;

function isMobileGrid() {
    return window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
}

function createInteractiveGrid() {
    var g = document.getElementById('interactiveGrid');
    if (!g) return;
    g.innerHTML = '';
    if (isMobileGrid()) return; /* mobile: no cells, static grid from CSS only to avoid lag */
    var gridSize = 50;
    var cols = Math.ceil(window.innerWidth / gridSize);
    var rows = Math.ceil(window.innerHeight * 6 / gridSize);
    for (var i = 0; i < rows; i++) {
        for (var j = 0; j < cols; j++) {
            var cell = document.createElement('div');
            cell.className = 'grid-cell';
            cell.style.left = j * gridSize + 'px';
            cell.style.top = i * gridSize + 'px';
            g.appendChild(cell);
        }
    }
}

function updateGridOnScroll() {
    if (!ticking) {
        requestAnimationFrame(function() {
            if (!grid) {
                grid = document.getElementById('interactiveGrid');
            }
            if (grid) {
                var scrollY = window.pageYOffset;
                grid.style.transform = 'translateY(-' + (scrollY * 0.60) + 'px)';
            }
            ticking = false;
        });
        ticking = true;
    }
}

/* --- Grid lighting (mouse hover + ambient) --- */
var cellTimeouts = new Map();
var mouseX = 0;
var mouseY = 0;
var gridAnimationFrameId = null;

document.addEventListener('mousemove', function(e) {
    mouseX = e.clientX;
    mouseY = e.clientY;
});

function updateGridLighting() {
    var g = document.getElementById('interactiveGrid');
    if (!g) return;
    var cells = g.querySelectorAll('.grid-cell');

    cells.forEach(function(cell) {
        var rect = cell.getBoundingClientRect();
        var isMouseOver = mouseX >= rect.left && mouseX < rect.right && mouseY >= rect.top && mouseY < rect.bottom;

        if (isMouseOver) {
            if (cellTimeouts.has(cell)) {
                clearTimeout(cellTimeouts.get(cell));
                cellTimeouts.delete(cell);
            }
            cell.style.background = 'rgba(51, 102, 255, 0.15)';
            cell.style.borderColor = 'rgba(51, 102, 255, 0.6)';
            cell.style.boxShadow = '0 0 20px rgba(51, 102, 255, 0.4)';
            cell.style.transform = 'scale(1.02)';
            cell.classList.add('active');

            var timeoutId = setTimeout(function() {
                cell.style.background = '';
                cell.style.borderColor = 'rgba(51, 102, 255, 0.1)';
                cell.style.boxShadow = '';
                cell.style.transform = 'scale(1)';
                cell.classList.remove('active');
                cellTimeouts.delete(cell);
            }, 1500);
            cellTimeouts.set(cell, timeoutId);
        }
    });

    gridAnimationFrameId = requestAnimationFrame(updateGridLighting);
}

function createAmbientLighting() {
    var g = document.getElementById('interactiveGrid');
    if (!g) return;
    var cells = g.querySelectorAll('.grid-cell');

    function lightRandomSquare() {
        if (cells.length === 0) return;
        var randomCell = cells[Math.floor(Math.random() * cells.length)];
        var intensity = Math.random() * 0.5 + 0.3;
        var duration = Math.random() * 2000 + 1000;

        randomCell.style.background = 'rgba(255, 255, 255, ' + (intensity * 0.3) + ')';
        randomCell.style.borderColor = 'rgba(255, 255, 255, ' + (intensity * 0.4) + ')';
        randomCell.style.boxShadow = '0 0 ' + (25 * intensity) + 'px rgba(255, 255, 255, ' + (intensity * 0.6) + ')';
        randomCell.style.transform = 'scale(' + (1 + 0.1 * intensity) + ')';
        randomCell.classList.add('active');

        setTimeout(function() {
            randomCell.style.background = '';
            randomCell.style.borderColor = 'rgba(51, 102, 255, 0.1)';
            randomCell.style.boxShadow = '';
            randomCell.style.transform = 'scale(1)';
            randomCell.classList.remove('active');
        }, duration);
    }

    function scheduleNextLight() {
        var delay = Math.random() * 3000 + 2000;
        setTimeout(function() {
            lightRandomSquare();
            scheduleNextLight();
        }, delay);
    }
    scheduleNextLight();
}

/* --- Bootstrap everything on page load --- */
window.addEventListener('load', function() {
    hidePageLoadOverlay();
    window.scrollTo(0, 0);
    createInteractiveGrid();
    grid = document.getElementById('interactiveGrid');
    if (!isMobileGrid()) {
        updateGridLighting();
        setTimeout(createAmbientLighting, 2000);
    }
});
window.addEventListener('pageshow', hidePageLoadOverlay);
window.addEventListener('DOMContentLoaded', hidePageLoadOverlay);
window.addEventListener('resize', createInteractiveGrid);
window.addEventListener('scroll', updateGridOnScroll, { passive: true });

/* --- Show overlay on same-origin page navigation --- */
(function() {
    var overlay = document.getElementById('pageLoadOverlay');
    if (!overlay) return;
    document.querySelectorAll('a[href]').forEach(function(a) {
        var href = a.getAttribute('href');
        if (!href || href === '#' || href.indexOf('javascript:') === 0) return;
        try {
            var url = new URL(a.href, window.location.href);
            if (url.origin === window.location.origin && url.pathname && url.pathname !== window.location.pathname) {
                a.addEventListener('click', function() { overlay.classList.remove('hidden'); });
            }
        } catch (e) {}
    });
})();
