/**
 * Gestionnaire de consentement aux cookies — RGPD / CNIL
 * Cabinets-Comptables.name
 *
 * Conforme aux recommandations CNIL 2021 :
 *  - Refus aussi simple qu'acceptation
 *  - Pas de consentement implicite
 *  - Durée de mémorisation 6 mois maximum
 *  - Choix granulaire par catégorie
 */
(function () {
  'use strict';

  var KEY         = 'ccn_consent';   // clé localStorage
  var EXPIRY_DAYS = 180;             // 6 mois (recommandation CNIL)

  /* ------------------------------------------------------------------ */
  /* Persistance                                                          */
  /* ------------------------------------------------------------------ */

  function getConsent() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return null;
      var data = JSON.parse(raw);
      if (!data || !data.date) return null;
      var age = (Date.now() - new Date(data.date).getTime()) / 864e5;
      if (age > EXPIRY_DAYS) { localStorage.removeItem(KEY); return null; }
      return data;
    } catch (e) { return null; }
  }

  function saveConsent(analytics, advertising) {
    var data = {
      analytics:   !!analytics,
      advertising: !!advertising,
      date: new Date().toISOString()
    };
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) {}
    return data;
  }

  /* ------------------------------------------------------------------ */
  /* Activation des services après consentement                          */
  /* ------------------------------------------------------------------ */

  function activateAnalytics() {
    /* Placeholder — remplacer par le code GA4 / Matomo réel si utilisé */
    /* Exemple GA4 :
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX';
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    function gtag(){ dataLayer.push(arguments); }
    gtag('js', new Date());
    gtag('config', 'G-XXXXXXXXXX');
    */
  }

  function activateAdvertising() {
    /* Placeholder — remplacer par le code AdSense réel si utilisé */
  }

  function applyConsent(consent) {
    if (!consent) return;
    if (consent.analytics)   activateAnalytics();
    if (consent.advertising) activateAdvertising();
  }

  /* ------------------------------------------------------------------ */
  /* Construction du bandeau                                             */
  /* ------------------------------------------------------------------ */

  var STYLES = [
    '#cc-banner{position:fixed;bottom:0;left:0;right:0;z-index:9999;',
    'background:#fff;border-top:3px solid #2563eb;box-shadow:0 -4px 24px rgba(0,0,0,.12);',
    'padding:16px 20px;font-family:\'Segoe UI\',system-ui,sans-serif;font-size:14px;',
    'color:#374151;transition:transform .3s ease;transform:translateY(100%);}',

    '#cc-banner.cc-visible{transform:translateY(0);}',

    '#cc-inner{max-width:1200px;margin:0 auto;}',

    '#cc-summary{display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap;}',
    '#cc-text{flex:1;min-width:220px;}',
    '#cc-text strong{display:block;font-size:15px;color:#111827;margin-bottom:4px;}',
    '#cc-text p{margin:0;line-height:1.5;color:#6b7280;font-size:13px;}',
    '#cc-text a{color:#2563eb;text-decoration:underline;}',

    '#cc-btns{display:flex;gap:8px;align-items:center;flex-wrap:wrap;flex-shrink:0;}',
    '.cc-btn{border:none;cursor:pointer;font-size:13px;font-weight:600;padding:9px 18px;',
    'border-radius:8px;white-space:nowrap;transition:opacity .15s;}',
    '.cc-btn:hover{opacity:.85;}',
    '.cc-accept{background:#2563eb;color:#fff;}',
    '.cc-refuse{background:#f3f4f6;color:#374151;border:1px solid #d1d5db;}',
    '.cc-customize{background:transparent;color:#2563eb;text-decoration:underline;',
    'padding:9px 6px;font-weight:500;}',

    '#cc-detail{display:none;margin-top:16px;padding-top:16px;border-top:1px solid #e5e7eb;}',
    '#cc-detail.cc-open{display:block;}',
    '.cc-category{display:flex;align-items:flex-start;gap:12px;margin-bottom:12px;',
    'padding:12px;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb;}',
    '.cc-cat-info{flex:1;}',
    '.cc-cat-info strong{display:block;font-size:13px;color:#111827;margin-bottom:2px;}',
    '.cc-cat-info p{margin:0;font-size:12px;color:#6b7280;line-height:1.4;}',
    '.cc-toggle{position:relative;display:inline-block;width:40px;height:22px;flex-shrink:0;margin-top:2px;}',
    '.cc-toggle input{opacity:0;width:0;height:0;}',
    '.cc-slider{position:absolute;inset:0;background:#d1d5db;border-radius:11px;transition:.2s;}',
    '.cc-slider:before{content:\'\';position:absolute;left:3px;top:3px;width:16px;height:16px;',
    'background:#fff;border-radius:50%;transition:.2s;}',
    '.cc-toggle input:checked+.cc-slider{background:#2563eb;}',
    '.cc-toggle input:checked+.cc-slider:before{transform:translateX(18px);}',
    '.cc-toggle input:disabled+.cc-slider{background:#93c5fd;cursor:not-allowed;}',

    '#cc-detail-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:12px;}',
  ].join('');

  function buildBanner() {
    /* Injecter les styles */
    if (!document.getElementById('cc-styles')) {
      var st = document.createElement('style');
      st.id  = 'cc-styles';
      st.textContent = STYLES;
      document.head.appendChild(st);
    }

    var banner = document.createElement('div');
    banner.id   = 'cc-banner';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-live', 'polite');
    banner.setAttribute('aria-label', 'Gestion des cookies');

    banner.innerHTML = [
      '<div id="cc-inner">',

        /* -- Résumé ---------------------------------------------------- */
        '<div id="cc-summary">',
          '<div id="cc-text">',
            '<strong>Vos préférences en matière de cookies</strong>',
            '<p>',
              'Nous utilisons des cookies pour analyser le trafic et diffuser des publicités ',
              'pertinentes. Consultez notre ',
              '<a href="/politique-de-confidentialite/" target="_blank">',
              'politique de confidentialité</a>.',
            '</p>',
          '</div>',
          '<div id="cc-btns">',
            '<button class="cc-btn cc-accept"  id="cc-accept-all">Tout accepter</button>',
            '<button class="cc-btn cc-refuse"  id="cc-refuse-all">Tout refuser</button>',
            '<button class="cc-btn cc-customize" id="cc-customize">Personnaliser</button>',
          '</div>',
        '</div>',

        /* -- Détails (masqués par défaut) ------------------------------- */
        '<div id="cc-detail">',

          /* Catégorie : Strictement nécessaires (toujours actif) */
          '<div class="cc-category">',
            '<div class="cc-cat-info">',
              '<strong>Strictement nécessaires</strong>',
              '<p>Préférences d\'affichage, mémorisation de vos choix de cookies. ',
              'Ces cookies ne peuvent pas être désactivés.</p>',
            '</div>',
            '<label class="cc-toggle">',
              '<input type="checkbox" checked disabled>',
              '<span class="cc-slider"></span>',
            '</label>',
          '</div>',

          /* Catégorie : Analytiques */
          '<div class="cc-category">',
            '<div class="cc-cat-info">',
              '<strong>Mesure d\'audience (Analytics)</strong>',
              '<p>Nous aident à comprendre comment les visiteurs interagissent avec le site ',
              '(pages vues, durée de session). Données anonymisées.</p>',
            '</div>',
            '<label class="cc-toggle">',
              '<input type="checkbox" id="cc-chk-analytics">',
              '<span class="cc-slider"></span>',
            '</label>',
          '</div>',

          /* Catégorie : Publicité */
          '<div class="cc-category">',
            '<div class="cc-cat-info">',
              '<strong>Publicité (Google AdSense)</strong>',
              '<p>Permettent d\'afficher des annonces publicitaires personnalisées pour ',
              'financer le service gratuit de cet annuaire.</p>',
            '</div>',
            '<label class="cc-toggle">',
              '<input type="checkbox" id="cc-chk-advertising">',
              '<span class="cc-slider"></span>',
            '</label>',
          '</div>',

          '<div id="cc-detail-btns">',
            '<button class="cc-btn cc-refuse"  id="cc-save-custom">Enregistrer mes choix</button>',
          '</div>',

        '</div>',
      '</div>',
    ].join('');

    return banner;
  }

  /* ------------------------------------------------------------------ */
  /* Affichage / masquage                                                */
  /* ------------------------------------------------------------------ */

  function removeBanner() {
    var el = document.getElementById('cc-banner');
    if (!el) return;
    el.style.transform = 'translateY(100%)';
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 350);
  }

  function showBanner() {
    removeBanner();
    var banner = buildBanner();
    document.body.appendChild(banner);

    /* Slide-in */
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        banner.classList.add('cc-visible');
      });
    });

    /* Événements */
    document.getElementById('cc-accept-all').addEventListener('click', function () {
      var c = saveConsent(true, true);
      applyConsent(c);
      removeBanner();
    });

    document.getElementById('cc-refuse-all').addEventListener('click', function () {
      saveConsent(false, false);
      removeBanner();
    });

    document.getElementById('cc-customize').addEventListener('click', function () {
      var det = document.getElementById('cc-detail');
      det.classList.toggle('cc-open');
      this.textContent = det.classList.contains('cc-open') ? 'Fermer' : 'Personnaliser';
    });

    document.getElementById('cc-save-custom').addEventListener('click', function () {
      var analytics   = document.getElementById('cc-chk-analytics').checked;
      var advertising = document.getElementById('cc-chk-advertising').checked;
      var c = saveConsent(analytics, advertising);
      applyConsent(c);
      removeBanner();
    });
  }

  /* ------------------------------------------------------------------ */
  /* API publique                                                        */
  /* ------------------------------------------------------------------ */

  /** Ouvrir le panneau de préférences (appelé depuis le footer) */
  window.openCookiePreferences = function () { showBanner(); };

  /* ------------------------------------------------------------------ */
  /* Initialisation                                                      */
  /* ------------------------------------------------------------------ */

  var consent = getConsent();
  if (consent) {
    /* Choix déjà enregistré → appliquer silencieusement */
    applyConsent(consent);
  } else {
    /* Première visite ou consentement expiré → afficher le bandeau */
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', showBanner);
    } else {
      showBanner();
    }
  }

})();
