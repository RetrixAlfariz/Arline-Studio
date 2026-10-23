"use strict";

(() => {
  const target = new EventTarget();

  const api = Object.freeze({
    on(type, handler, options) {
      target.addEventListener(type, handler, options);
      return () => target.removeEventListener(type, handler, options);
    },
    once(type, handler) {
      target.addEventListener(type, handler, { once: true });
      return () => target.removeEventListener(type, handler);
    },
    off(type, handler, options) {
      target.removeEventListener(type, handler, options);
    },
    emit(type, detail = null) {
      target.dispatchEvent(new CustomEvent(type, { detail }));
    },
  });

  window.ArlineEvents = api;
})();
