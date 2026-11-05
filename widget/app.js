/*
 * PLM Data Agent widget for 3DDashboard ("Run your App").
 *
 * In 3DDashboard it calls 3DSpace with the logged-in user's session through the platform's WAFData module: no
 * credentials in this code, and each user sees and changes only what their own role allows. The agent backend
 * (scripts/serve_widget.py) adds what is not in PLM: proposals awaiting review (part numbers live only in the
 * log) and recording decisions. Opened outside 3DDashboard, the widget runs on a dataset: the offline demo.
 *
 * The checks themselves are in core.js (same results as agent/readiness.py and agent/duplicates.py).
 */
/* global PLMCore, widget, require */
(function () {
  'use strict';

  var core = PLMCore;
  var ITEM = '/resources/v1/modeler/dseng/dseng:EngItem';
  var MASK = 'dsmveng:EngItemMask.Details';
  var INSTANCE_MASK = 'dsmveng:EngInstanceMask.Details';
  var PAGE = 100;

  var state = {
    mode: null,            // 'live' or 'offline'
    tab: 'review',
    steps: [],             // connection checks shown in the Connection tab
    cfg: {},               // from the backend: spaceUrl, securityContext, collabspace, tenant
    backend: false,
    WAFData: null, spaceUrl: '', tenant: '', csrf: '',
    snapshot: { items: {}, children: {} },
    pending: [],
    notes: {},             // proposal key -> {kind, text} after a decision
    dataset: 'dataset.json',
    root: '',
    newPart: { description: '', title: '', material: '' }
  };

  // ---------------------------------------------------------------- helpers

  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === undefined || v === null || v === false) { return; }
      if (k === 'class') { el.className = v; }
      else if (k.indexOf('on') === 0) { el.addEventListener(k.slice(2), v); }
      else if (k === 'value') { el.value = v; }
      else { el.setAttribute(k, v === true ? '' : v); }
    });
    for (var i = 2; i < arguments.length; i++) { append(el, arguments[i]); }
    return el;
  }

  function append(el, child) {
    if (child === undefined || child === null || child === false) { return; }
    if (Array.isArray(child)) { child.forEach(function (c) { append(el, c); }); return; }
    el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  function root() {
    // In 3DDashboard the widget draws into widget.body; standalone into the page's #app
    var body = inDashboard() && typeof widget !== 'undefined' && widget.body;
    if (body) {
      if (!body.id) { body.id = 'app'; }  // the stylesheet styles #app
      return body;
    }
    return document.getElementById('app') || (typeof widget !== 'undefined' && widget.body) || null;
  }

  function step(name, ok, detail) {
    var existing = state.steps.filter(function (s) { return s.name === name; })[0];
    var entry = existing || { name: name };
    entry.ok = ok; entry.detail = detail || '';
    if (!existing) { state.steps.push(entry); }
    render();
  }

  function mapLimit(list, limit, fn) {
    var results = new Array(list.length), next = 0;
    function worker() {
      if (next >= list.length) { return Promise.resolve(); }
      var n = next++;
      return Promise.resolve(fn(list[n], n)).then(function (r) { results[n] = r; return worker(); });
    }
    var workers = [];
    for (var i = 0; i < Math.min(limit, list.length); i++) { workers.push(worker()); }
    return Promise.all(workers).then(function () { return results; });
  }

  function backend(path, options) {
    return fetch(new URL(path, document.baseURI).toString(), options).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) { throw new Error(body.error || ('HTTP ' + r.status)); }
        return body;
      });
    });
  }

  function key(record) { return record.proposal_id || ('plm:' + record.item_id + ':' + record.field); }

  // ---------------------------------------------------------------- platform (live mode)

  function inDashboard() {
    try { return window.top !== window && typeof require === 'function'; } catch (e) { return true; }
  }

  function loadModules() {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('DS/WAFData did not load within 10 s')); }, 10000);
      try {
        require(['DS/WAFData/WAFData', 'DS/i3DXCompassServices/i3DXCompassServices'], function (WAFData, Compass) {
          clearTimeout(timer);
          resolve({ WAFData: WAFData, Compass: Compass });
        }, function (err) { clearTimeout(timer); reject(err); });
      } catch (e) { clearTimeout(timer); reject(e); }
    });
  }

  function serviceUrl(Compass, platformId) {
    return new Promise(function (resolve, reject) {
      // On the tenant this call has been seen to never answer: give up after 8 s and use a fallback
      setTimeout(function () { reject(new Error('the platform did not answer getServiceUrl within 8 s')); }, 8000);
      Compass.getServiceUrl({
        serviceName: '3DSpace',
        platformId: platformId || undefined,
        onComplete: function (r) {
          if (typeof r === 'string' && r) { return resolve(r); }
          if (Array.isArray(r) && r.length) {
            var match = r.filter(function (x) { return !platformId || x.platformId === platformId; })[0] || r[0];
            return resolve(match.url);
          }
          reject(new Error('no 3DSpace URL in ' + JSON.stringify(r)));
        },
        onFailure: function (e) { reject(new Error('getServiceUrl failed: ' + (e && e.message || e))); }
      });
    });
  }

  // The frame URL names the tenant's ifwe domain (widgetDomain=https://r123-eu1-academia-ifwe.3dexperience.3ds.com);
  // 3DSpace is the same host with -space and /enovia (as PLM_SPACE_URL in .env)
  function spaceUrlFromFrame() {
    try {
      var domain = new URLSearchParams(window.location.search).get('widgetDomain') || '';
      return /-ifwe\./.test(domain) ? domain.replace(/\/$/, '').replace('-ifwe.', '-space.') + '/enovia' : '';
    } catch (e) { return ''; }
  }

  function tenantFromUrl(url) {
    var host = (url.match(/^https?:\/\/([^/]+)/) || [])[1] || '';
    return host.split('-')[0].toUpperCase();
  }

  function plm(method, path, options) {
    options = options || {};
    var params = {};
    Object.keys(options.params || {}).forEach(function (k) { params[k] = options.params[k]; });
    if (state.tenant) { params.tenant = state.tenant; }  // the cloud tenant answers "tenant does not exist" without it
    var query = Object.keys(params).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
    }).join('&');
    var headers = { Accept: 'application/json', SecurityContext: state.cfg.securityContext };
    if (method !== 'GET') {
      headers.ENO_CSRF_TOKEN = state.csrf;
      headers['Content-Type'] = 'application/json';
    }
    return new Promise(function (resolve, reject) {
      state.WAFData.authenticatedRequest(state.spaceUrl + path + (query ? '?' + query : ''), {
        method: method,
        headers: headers,
        type: 'json',
        data: options.body ? JSON.stringify(options.body) : undefined,
        timeout: 30000,
        onTimeout: function () { reject(new Error(method + ' ' + path.replace(ITEM, 'EngItem') + ': no answer within 30 s')); },
        onComplete: function (data) {
          if (typeof data === 'string') { try { data = data ? JSON.parse(data) : {}; } catch (e) { /* keep text */ } }
          resolve(data || {});
        },
        onFailure: function (err, data) {
          var detail = (data && (data.message || data.error)) || (err && err.message) || String(err);
          reject(new Error(method + ' ' + path.replace(ITEM, 'EngItem') + ': ' + detail));
        }
      });
    });
  }

  function getItem(id) {
    return plm('GET', ITEM + '/' + id, { params: { $mask: MASK } }).then(function (data) {
      var member = (data.member || [])[0];
      if (!member) { throw new Error('item ' + id + ' not found'); }
      return member;
    });
  }

  function searchAll() {
    var found = [];
    function page(skip) {
      return plm('GET', ITEM + '/search', { params: { $searchStr: '*', $mask: MASK, $top: PAGE, $skip: skip } })
        .then(function (data) {
          var members = data.member || [];
          found = found.concat(members);
          return members.length < PAGE ? found : page(skip + PAGE);
        });
    }
    return page(0);
  }

  function childrenOf(id) {
    var ids = [];
    function page(skip) {
      return plm('GET', ITEM + '/' + id + '/dseng:EngInstance', { params: { $mask: INSTANCE_MASK, $top: PAGE, $skip: skip } })
        .then(function (data) {
          var members = data.member || [];
          members.forEach(function (inst) {
            var child = (inst.referencedObject || {}).identifier;
            if (child && ids.indexOf(child) < 0) { ids.push(child); }
          });
          return members.length < PAGE ? ids : page(skip + PAGE);
        });
    }
    return page(0);
  }

  function connectLive() {
    state.mode = 'live';
    state.steps = [];
    return backend('api/config').then(function (cfg) {
      state.cfg = cfg; state.backend = true;
      step('Agent backend', true, 'proposal log reachable');
    }, function () {
      state.backend = false;
      step('Agent backend', true, 'not used here: inside 3DDashboard the widget works on PLM alone (part-number ' +
        'proposals and the proposal log stay with review.py)');
    }).then(function () {
      applySettings();
      step('Platform modules', null, 'loading...');
      return loadModules();
    }).then(function (m) {
      state.WAFData = m.WAFData;
      step('Platform modules', true, 'WAFData and i3DXCompassServices loaded');
      var platformId = typeof widget !== 'undefined' && widget.getValue ? widget.getValue('x3dPlatformId') : '';
      step('3DSpace URL', null, 'asking the platform...');
      function use(url, source) {
        state.spaceUrl = url.replace(/\/$/, '');
        state.tenant = platformId || state.cfg.tenant || tenantFromUrl(state.spaceUrl);
        step('3DSpace URL', true, state.spaceUrl + ' (tenant ' + state.tenant + ', ' + source + ')');
      }
      if (state.cfg.spaceUrlOverride) { return use(state.cfg.spaceUrlOverride, 'entered under Connection'); }
      return serviceUrl(m.Compass, platformId).then(function (url) { use(url, 'from the platform'); }, function (e) {
        var fallback = state.cfg.spaceUrl || spaceUrlFromFrame();
        if (!fallback) { throw new Error(e.message + '; enter the 3DSpace URL under Connection'); }
        use(fallback, (state.cfg.spaceUrl ? 'from .env' : 'from the dashboard frame') + ': ' + e.message);
      });
    }).then(function () {
      step('CSRF token', null, 'requesting...');
      return plm('GET', '/resources/v1/application/CSRF');
    }).then(function (data) {
      state.csrf = ((data || {}).csrf || {}).value;
      if (!state.csrf) { throw new Error('no CSRF token in ' + JSON.stringify(data).slice(0, 200)); }
      step('CSRF token', true, 'received');
      step('Search', null, 'searching ' + (state.cfg.collabspace || 'all collab spaces') + '...');
      return loadSnapshot();
    }).catch(function (e) {
      step('Connection', false, e.message || String(e));
      state.tab = 'connection';
      render();
    });
  }

  function loadSnapshot() {
    var space = state.cfg.collabspace;
    return searchAll().then(function (members) {
      var items = {};
      members.filter(function (i) { return !space || i.collabspace === space; })
        .sort(function (a, b) { return (a.title || '') < (b.title || '') ? -1 : 1; })
        .forEach(function (i) { items[i.id] = i; });
      step('Search', true, Object.keys(items).length + ' items in ' + (space || 'all collab spaces') +
        ' (of ' + members.length + ' found)');
      var snapshot = { items: items, children: {} };
      step('BOM links', null, 'reading the structure of ' + Object.keys(items).length + ' items...');
      return mapLimit(Object.keys(items), 4, function (id) {
        return childrenOf(id).then(function (kids) { snapshot.children[id] = kids; });
      }).then(function () {
        var outside = [];
        Object.keys(snapshot.children).forEach(function (id) {
          snapshot.children[id].forEach(function (c) { if (!items[c] && outside.indexOf(c) < 0) { outside.push(c); } });
        });
        return mapLimit(outside, 4, function (id) {  // a child outside the collab space (e.g. a library part)
          return getItem(id).then(function (item) { items[id] = item; snapshot.children[id] = []; });
        });
      }).then(function () {
        var links = Object.keys(snapshot.children).reduce(function (n, id) { return n + snapshot.children[id].length; }, 0);
        step('BOM links', true, links + ' parent-child links read');
        state.snapshot = snapshot;
        return state.backend ? backend('api/pending') : [];
      });
    }).then(function (pending) {
      state.pending = pending;
      pickRoot();
      render();
    });
  }

  function applySettings() {
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem('plm-agent-settings') || '{}'); } catch (e) { /* none */ }
    ['securityContext', 'collabspace', 'spaceUrlOverride'].forEach(function (k) { if (saved[k]) { state.cfg[k] = saved[k]; } });
    if (!state.cfg.securityContext) {
      throw new Error('no SecurityContext: enter it under Connection (Role.Organization.CollabSpace)');
    }
  }

  // ---------------------------------------------------------------- offline demo

  function connectOffline() {
    state.mode = 'offline';
    state.steps = [];
    step('Offline demo', true, 'not inside 3DDashboard: an in-memory tenant built from data/' + state.dataset +
      ', with the rule-based proposals at confidence >= 0.5 written as [PROPOSED] (as run_agent.py --apply). Nothing is written anywhere.');
    return backend('api/offline?dataset=' + encodeURIComponent(state.dataset)).then(function (payload) {
      state.backend = true;
      state.cfg = { collabspace: payload.collabspace };
      state.snapshot = { items: payload.items, children: payload.children };
      state.pending = payload.pending;
      state.notes = {};
      pickRoot();
      render();
    }, function (e) {
      var local = window.location.hostname === 'localhost';
      step('Agent backend', false, local ? e.message + ': start it with scripts/serve_widget.py'
        : 'the offline demo needs the local server: run scripts/serve_widget.py and open https://localhost:8443/index.html ' +
          '(in 3DDashboard, "Run your App", the widget uses the live tenant instead)');
    });
  }

  // ---------------------------------------------------------------- review

  function reviewList() {
    var list = state.pending.slice();
    var logged = {};
    list.forEach(function (r) { logged[r.item_id + ':' + r.field] = true; });
    Object.keys(state.snapshot.items).forEach(function (id) {  // [PROPOSED] in PLM with no record in the log
      var item = state.snapshot.items[id];
      var description = core.fieldValue(item, 'description');
      if (description.indexOf(core.PROPOSED_PREFIX) === 0 && !logged[id + ':description']) {
        list.push({ proposal_id: null, item_id: id, title: item.title, field: 'description',
          value: description.slice(core.PROPOSED_PREFIX.length).trim(), written_to_plm: true, old_value: null,
          method: 'not in this proposal log', evidence: [], confidence: null });
      }
    });
    return list;
  }

  function expectedValue(record, item) {
    if (record.written_to_plm) { return core.PROPOSED_PREFIX + ' ' + record.value; }
    return record.old_value === null ? core.fieldValue(item, record.field) : (record.old_value || '');
  }

  function attributes(field, value) {
    return field === 'partNumber' ? { 'dseng:EnterpriseReference': { partNumber: value } } : (function () {
      var a = {}; a[field] = value; return a;
    })();
  }

  function decide(record, event, value) {
    if (typeof value === 'string') { value = value.trim(); }  // stray spaces from the edit box must not reach PLM
    var k = key(record);
    var label = event === 'approved' ? 'Write ' + JSON.stringify(value) + ' to ' + record.field + ' of ' + record.title
      : (record.written_to_plm ? 'Restore the old ' + record.field + ' of ' + record.title + ' (' +
        JSON.stringify(record.old_value || '') + ')' : 'Reject the ' + record.field + ' proposal for ' + record.title);
    if (state.mode === 'live' && !window.confirm(label + ' in PLM?')) { return; }
    if (event === 'approved' && !value.trim()) {
      state.notes[k] = { kind: 'bad', text: 'An approved value cannot be empty: reject instead.' };
      return render();
    }
    state.notes[k] = { kind: 'busy', text: 'Working...' };
    render();

    var done = state.mode === 'offline' ? Promise.resolve(applyLocally(record, event, value)) : applyInPlm(record, event, value);
    done.then(function (message) {
      state.notes[k] = { kind: 'ok', text: message };
      state.pending = state.pending.filter(function (p) { return key(p) !== k; });
      render();
    }).catch(function (e) {
      state.notes[k] = { kind: 'bad', text: e.message || String(e) };
      render();
    });
  }

  function applyLocally(record, event, value) {
    var item = state.snapshot.items[record.item_id];
    var final = event === 'approved' ? value : (record.old_value || '');
    if (event === 'approved' || record.written_to_plm) {
      if (record.field === 'partNumber') { item['dseng:EnterpriseReference'] = { partNumber: final }; }
      else { item[record.field] = final; }
    }
    return (event === 'approved' ? 'Approved' : 'Rejected') + ' (offline demo: nothing written).';
  }

  function applyInPlm(record, event, value) {
    var item;
    return getItem(record.item_id).then(function (current) {
      item = current;
      // Conflict check on the field's content, as agent/writeback.py: someone may have edited it since
      var expected = expectedValue(record, state.snapshot.items[record.item_id] || item);
      var now = core.fieldValue(item, record.field);
      if (now !== expected) {
        throw new Error('Conflict: ' + record.field + ' is now ' + JSON.stringify(now) + ', expected ' +
          JSON.stringify(expected) + '. It was changed in PLM; review it there.');
      }
      if (event === 'rejected' && !record.written_to_plm) { return null; }  // a part number never reached PLM
      var final = event === 'approved' ? value : (record.old_value || '');
      var body = attributes(record.field, final);
      body.cestamp = item.cestamp;
      return plm('PATCH', ITEM + '/' + record.item_id, { params: { $mask: MASK }, body: body });
    }).then(function (data) {
      var updated = data && (data.member || [])[0];
      if (updated) { state.snapshot.items[record.item_id] = updated; }
      if (!record.proposal_id || !state.backend) { return 'Done in PLM (no proposal log entry to update).'; }
      var decision = { proposal_id: record.proposal_id, event: event };
      if (event === 'approved') { decision.final_value = value; }
      return backend('api/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(decision) }).then(function () {
        return (event === 'approved' ? 'Approved' : 'Rejected') + ': PLM updated and decision logged.';
      }, function (e) {
        return 'PLM updated, but the decision was not logged (' + e.message + ').';
      });
    });
  }

  // ---------------------------------------------------------------- views

  function pickRoot() {
    var s = state.snapshot, used = {};
    Object.keys(s.children).forEach(function (id) { (s.children[id] || []).forEach(function (c) { used[c] = true; }); });
    var assemblies = assemblyIds();
    if (assemblies.indexOf(state.root) < 0) {
      state.root = assemblies.filter(function (id) { return !used[id]; })[0] || assemblies[0] || '';
    }
  }

  function assemblyIds() {
    var s = state.snapshot;
    return Object.keys(s.items).filter(function (id) { return (s.children[id] || []).length; })
      .sort(function (a, b) { return (s.items[a].title || '') < (s.items[b].title || '') ? -1 : 1; });
  }

  function gapCount() {
    var n = 0;
    Object.keys(state.snapshot.items).forEach(function (id) {
      core.FIELDS.forEach(function (f) { if (!core.fieldValue(state.snapshot.items[id], f).trim()) { n++; } });
    });
    return n;
  }

  function viewHeader() {
    var items = Object.keys(state.snapshot.items).length;
    var report = state.root ? core.readiness(state.snapshot, state.root, state.pending) : null;
    return h('header', null,
      h('div', { class: 'brand' },
        h('div', { class: 'title' }, 'PLM Data Agent'),
        h('span', { class: 'mode ' + state.mode }, state.mode === 'live'
          ? 'Live: ' + (state.cfg.collabspace || 'tenant') : 'Offline demo: ' + state.dataset),
        h('button', { class: 'ghost', onclick: start, title: 'Reload everything from PLM' }, 'Refresh')),
      h('div', { class: 'stats' },
        stat(items, 'items'),
        stat(gapCount(), 'empty fields'),
        stat(reviewList().length, 'awaiting review'),
        report ? h('div', { class: 'stat ' + (report.ready ? 'ok' : 'bad') },
          h('b', null, report.ready ? 'READY' : 'NOT READY'), h('span', null, report.root_title)) : null));
  }

  function stat(value, label) { return h('div', { class: 'stat' }, h('b', null, value), h('span', null, label)); }

  function viewTabs() {
    var tabs = [['review', 'Review'], ['readiness', 'Release readiness'], ['duplicates', 'Duplicates'], ['connection', 'Connection']];
    return h('nav', null, tabs.map(function (t) {
      return h('button', { class: state.tab === t[0] ? 'active' : '', onclick: function () { state.tab = t[0]; render(); } }, t[1]);
    }));
  }

  function viewReview() {
    var list = reviewList();
    var done = Object.keys(state.notes).filter(function (k) { return state.notes[k].kind === 'ok'; }).length;
    return h('section', null,
      h('p', { class: 'hint' }, 'AI proposals waiting for a decision. Descriptions are in PLM as ', h('code', null, '[PROPOSED] value'),
        '; part numbers only in the proposal log until approved. Edit the value before approving if needed.'),
      list.length ? null : h('p', { class: 'empty' }, done ? 'All reviewed.' : 'Nothing awaiting review.'),
      list.map(viewProposal),
      Object.keys(state.notes).filter(function (k) {
        return state.notes[k].kind === 'ok' && !list.some(function (r) { return key(r) === k; });
      }).map(function (k) { return h('div', { class: 'note ok' }, state.notes[k].text); }));
  }

  function viewProposal(record) {
    var k = key(record), note = state.notes[k];
    var item = state.snapshot.items[record.item_id] || {};
    var input = h('input', { type: 'text', value: record.value, 'aria-label': 'proposed value' });
    var confidence = typeof record.confidence === 'number' ? record.confidence : null;
    return h('article', { class: 'card' },
      h('div', { class: 'row' },
        h('div', null, h('b', null, record.title), h('span', { class: 'field' }, record.field)),
        confidence === null ? null : h('div', { class: 'conf', title: 'confidence' },
          h('div', { class: 'bar' }, h('i', { style: 'width:' + Math.round(confidence * 100) + '%' })),
          h('span', null, confidence.toFixed(2)))),
      h('div', { class: 'meta' }, 'In PLM now: ', h('code', null, core.fieldValue(item, record.field) || '(empty)'),
        ' · ', record.method || '', record.suggester ? ' · ' + record.suggester : ''),
      record.evidence && record.evidence.length ? h('ul', { class: 'evidence' },
        record.evidence.slice(0, 5).map(function (e) { return h('li', null, e); })) : null,
      h('div', { class: 'row actions' }, input,
        h('button', { class: 'primary', disabled: note && note.kind === 'busy',
          onclick: function () { decide(record, 'approved', input.value); } }, 'Approve'),
        h('button', { class: 'danger', disabled: note && note.kind === 'busy',
          onclick: function () { decide(record, 'rejected'); } }, 'Reject')),
      note ? h('div', { class: 'note ' + note.kind }, note.text) : null);
  }

  function viewReadiness() {
    var ids = assemblyIds();
    if (!ids.length) { return h('section', null, h('p', { class: 'empty' }, 'No assemblies found.')); }
    var report = core.readiness(state.snapshot, state.root, state.pending);
    var byItem = {};
    report.issues.forEach(function (i) { (byItem[i.item_id] = byItem[i.item_id] || []).push(i); });
    var select = h('select', { onchange: function (e) { state.root = e.target.value; render(); } },
      ids.map(function (id) {
        return h('option', { value: id, selected: id === state.root }, state.snapshot.items[id].title);
      }));
    return h('section', null,
      h('div', { class: 'row' }, h('label', null, 'Assembly ', select)),
      h('div', { class: 'verdict ' + (report.ready ? 'ok' : 'bad') }, core.summary(report)),
      h('div', { class: 'tree' }, report.bom.map(function (line) {
        var issues = byItem[line.item_id] || [];
        return h('div', { class: 'node' + (issues.length ? ' flagged' : ''), style: 'padding-left:' + (line.depth * 18 + 6) + 'px' },
          h('span', { class: 'dot' }, issues.length ? '!' : '✓'), ' ', line.title,
          issues.map(function (i) {
            return h('div', { class: 'issue' }, i.kind + (i.field ? ' ' + i.field : '') + (i.detail ? ': ' + i.detail : ''));
          }));
      }), report.issues.filter(function (i) { return i.kind === core.KIND.CYCLE; }).map(function (i) {
        return h('div', { class: 'issue' }, 'cycle: ' + i.detail);
      })));
  }

  function viewCandidates(list, emptyText) {
    if (!list.length) { return h('p', { class: 'empty' }, emptyText); }
    return list.map(function (c) {
      return h('article', { class: 'card' },
        h('div', { class: 'row' }, h('div', null, c.item_id ? [h('b', null, c.title), ' ↔ '] : null, h('b', null, c.other_title)),
          h('span', { class: 'score' }, c.score.toFixed(2))),
        h('ul', { class: 'evidence' }, c.reasons.map(function (r) { return h('li', null, r); })));
    });
  }

  function viewDuplicates() {
    var pairs = core.findDuplicates(state.snapshot);
    var p = state.newPart;
    var description = h('input', { type: 'text', value: p.description, placeholder: 'Description, e.g. Hex bolt M8x25, zinc plated' });
    var title = h('input', { type: 'text', value: p.title, placeholder: 'Title (optional)' });
    var material = h('input', { type: 'text', value: p.material, placeholder: 'Material (optional)' });
    function check() {
      state.newPart = { description: description.value, title: title.value, material: material.value, checked: true };
      render();
    }
    var existing = p.checked ? core.findExisting(state.snapshot, p.title, p.description, p.material) : null;
    return h('section', null,
      h('h3', null, 'Before creating a part: does it already exist?'),
      h('div', { class: 'row actions' }, description, title, material, h('button', { class: 'primary', onclick: check }, 'Check')),
      existing ? viewCandidates(existing, 'No existing item looks like this part: create it.') : null,
      h('h3', null, 'Possible duplicates in ' + (state.cfg.collabspace || 'the collab space') + ' (' + pairs.length + ')'),
      h('p', { class: 'hint' }, 'Same words weighted by rarity; sizes must agree (M6 and M8 are variants), a different material rules a pair out.'),
      viewCandidates(pairs, 'No possible duplicates.'));
  }

  function viewConnection() {
    var context = h('input', { type: 'text', value: state.cfg.securityContext || '', placeholder: 'Role.Organization.CollabSpace' });
    var space = h('input', { type: 'text', value: state.cfg.collabspace || '', placeholder: 'Collab space' });
    var spaceUrl = h('input', { type: 'text', value: state.cfg.spaceUrlOverride || '',
      placeholder: 'optional, e.g. https://r123-eu1-academia-space.3dexperience.3ds.com/enovia' });
    function save() {
      try {
        localStorage.setItem('plm-agent-settings', JSON.stringify({ securityContext: context.value.trim(),
          collabspace: space.value.trim(), spaceUrlOverride: spaceUrl.value.trim() }));
      } catch (e) { /* storage blocked: use the backend's values */ }
      start();
    }
    var offlineButtons = state.mode === 'offline' ? h('div', { class: 'row' }, 'Dataset: ',
      ['dataset.json', 'dataset_cad.json'].map(function (d) {
        return h('button', { class: d === state.dataset ? 'primary' : 'ghost', onclick: function () { state.dataset = d; start(); } }, d);
      })) : null;
    return h('section', null,
      h('table', { class: 'steps' }, state.steps.map(function (s) {
        var mark = s.ok === null ? '…' : s.ok ? '✓' : '✗';
        return h('tr', null, h('td', { class: s.ok === null ? 'busy' : s.ok ? 'ok' : 'bad' }, mark),
          h('td', null, h('b', null, s.name)), h('td', null, s.detail));
      })),
      offlineButtons,
      state.mode === 'live' ? h('div', { class: 'settings' },
        h('label', null, 'SecurityContext ', context), h('label', null, 'Collab space ', space),
        h('label', null, '3DSpace URL ', spaceUrl),
        h('button', { class: 'primary', onclick: save }, 'Save and reconnect')) : null,
      h('p', { class: 'hint' }, state.mode === 'live'
        ? 'Live mode calls 3DSpace with your own 3DEXPERIENCE session (WAFData): no password or token is stored in the widget, ' +
          'and you see and change only what your role allows.'
        : 'Offline demo: an in-memory tenant built from a dataset; nothing is written anywhere.'));
  }

  function render() {
    var el = root();
    if (!el) { return; }
    var views = { review: viewReview, readiness: viewReadiness, duplicates: viewDuplicates, connection: viewConnection };
    var body = state.mode ? views[state.tab]() : h('p', { class: 'empty' }, 'Starting...');
    el.innerHTML = '';
    append(el, [viewHeader(), viewTabs(), body]);
  }

  function start() {
    state.notes = {};
    state.pending = [];
    state.snapshot = { items: {}, children: {} };
    render();
    if (typeof widget !== 'undefined' && widget.setTitle) { try { widget.setTitle('PLM Data Agent'); } catch (e) { /* ok */ } }
    return inDashboard() ? connectLive() : connectOffline();
  }

  try {  // ?tab=readiness opens that tab, ?dataset=dataset_cad.json picks the offline dataset
    var query = new URLSearchParams(window.location.search);
    if (['review', 'readiness', 'duplicates', 'connection'].indexOf(query.get('tab')) >= 0) { state.tab = query.get('tab'); }
    if (query.get('dataset')) { state.dataset = query.get('dataset'); }
  } catch (e) { /* old browser: defaults */ }

  // Show errors inside the widget: in 3DDashboard there is no console at hand during a demo
  window.addEventListener('error', function (e) {
    var el = root();
    if (el) { append(el, h('div', { class: 'note bad' }, 'Widget error: ' + e.message + ' (' + (e.filename || '').split('/').pop() + ':' + e.lineno + ')')); }
  });

  var started = false;
  function once() { if (!started && root()) { started = true; start(); } }
  if (typeof widget !== 'undefined' && widget.addEvent) {
    widget.addEvent('onLoad', once);  // the widget's start in 3DDashboard
    widget.addEvent('onRefresh', start);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', once); } else { once(); }
  setTimeout(once, 3000);  // in case onLoad fired before this script registered
})();
