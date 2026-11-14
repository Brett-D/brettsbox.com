// Brett's Box "Lab": small progressive enhancements. Everything works without this file.
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
    var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 8); };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
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

  // Pause the SVG map animation for people who prefer less motion.
  if (reduce.matches) {
    document.querySelectorAll('svg.map').forEach(function (svg) {
      if (svg.pauseAnimations) svg.pauseAnimations();
    });
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

  // Count the big numbers up once, for a little life.
  if (!reduce.matches) {
    document.querySelectorAll('[data-count]').forEach(function (el) {
      var target = parseInt(el.getAttribute('data-count'), 10);
      var start = null;
      function step(ts) {
        if (start === null) start = ts;
        var t = Math.min(1, (ts - start) / 1200);
        el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
        if (t < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    });
  }
})();
