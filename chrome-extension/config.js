// Chrome extensions cannot read .env files at runtime. Keep public, non-secret
// browser configuration here (or replace this file during packaging).
globalThis.CW_CONFIG = Object.freeze({
  CW_API_BASE_URL: 'http://localhost:8000/backend'
});
