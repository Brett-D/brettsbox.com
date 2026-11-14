// Brett's Box "Blueprint": small progressive enhancements. Everything works without this file.
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

  // Mobile navigation toggle.
  var header = document.querySelector('.site-header');
  var toggle = document.querySelector('.nav-toggle');
  if (header && toggle) {
    toggle.addEventListener('click', function () {
      var open = header.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && header.classList.contains('is-open')) {
        header.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  // Scroll reveals.
  var revealed = document.querySelectorAll('[data-reveal]');
  if ('IntersectionObserver' in window && !reduce.matches) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in');
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
    revealed.forEach(function (el) { io.observe(el); });
  } else {
    revealed.forEach(function (el) { el.classList.add('is-in'); });
  }

  // Demo videos: autoplay muted while on screen, unless reduced motion is requested.
  document.querySelectorAll('[data-video]').forEach(function (box) {
    var video = box.querySelector('video');
    var button = box.querySelector('.video__toggle');
    var label = button.querySelector('.video__text');
    var userPaused = false;
    video.muted = true;
    video.controls = false;
    button.hidden = false;

    function sync() {
      var playing = !video.paused;
      box.classList.toggle('is-playing', playing);
      label.textContent = playing ? 'Pause video' : 'Play video';
    }
    button.addEventListener('click', function () {
      if (video.paused) {
        userPaused = false;
        video.play().catch(function () {});
      } else {
        userPaused = true;
        video.pause();
      }
    });
    video.addEventListener('play', sync);
    video.addEventListener('pause', sync);

    if (!reduce.matches && 'IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            if (!userPaused) video.play().catch(function () {});
          } else if (!video.paused) {
            video.pause();
          }
        });
      }, { threshold: 0.3 }).observe(video);
    }
    sync();
  });

  // CAD-style pointer coordinate readout (fine pointers only, purely decorative).
  var readout = document.querySelector('.readout');
  if (readout && window.matchMedia('(pointer: fine)').matches && !reduce.matches) {
    var rx = readout.querySelector('[data-x]');
    var ry = readout.querySelector('[data-y]');
    var pad = function (n) { return ('0000' + Math.max(0, Math.round(n))).slice(-4); };
    var pending = false;
    window.addEventListener('pointermove', function (e) {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () {
        rx.textContent = 'X ' + pad(e.pageX);
        ry.textContent = 'Y ' + pad(e.pageY);
        readout.classList.add('is-on');
        pending = false;
      });
    }, { passive: true });
  }
})();