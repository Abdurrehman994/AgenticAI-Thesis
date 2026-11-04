/*
 * Plain-code checks of the PLM Data Agent widget: release readiness and duplicate detection.
 *
 * A port of agent/readiness.py and agent/duplicates.py, so the widget gives the same answers inside
 * 3DEXPERIENCE as the scripts. tests/test_widget.py runs both on the same data and compares them: change the
 * Python and this file together.
 *
 * A snapshot is {items: {id: item}, children: {id: [child ids]}}, items as dseng search returns them.
 * Works in the browser (window.PLMCore) and in node (module.exports).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PLMCore = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var FIELDS = ['description', 'partNumber'];
  var PROPOSED_PREFIX = '[PROPOSED]';
  var MIN_SCORE = 0.5;
  var MAX_REASON_WORDS = 6;
  var KIND = {
    MISSING: 'missing', UNAPPROVED: 'unapproved AI value', PENDING: 'pending review',
    DUPLICATE: 'duplicate part number', CYCLE: 'cycle'
  };

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  // Python's repr of a string, so messages read the same as the scripts' ('Guard assembly')
  function quote(s) {
    s = String(s);
    var q = s.indexOf("'") >= 0 && s.indexOf('"') < 0 ? '"' : "'";
    return q + s.replace(/\\/g, '\\\\').split(q).join('\\' + q) + q;
  }

  function partNumber(item) {
    return ((item['dseng:EnterpriseReference'] || {}).partNumber) || '';
  }

  function fieldValue(item, field) {
    return field === 'partNumber' ? partNumber(item) : (item[field] || '');
  }

  function title(snapshot, id) {
    var item = snapshot.items[id];
    return (item && item.title) || id;
  }

  function children(snapshot, id) { return snapshot.children[id] || []; }

  // ---- release readiness (agent/readiness.py) ----

  function walkBom(snapshot, rootId) {
    var lines = [], cycles = [], done = {};
    function visit(id, depth, path) {
      if (path.indexOf(id) >= 0) {
        cycles.push({ item_id: id, title: title(snapshot, id), kind: KIND.CYCLE, field: '',
          detail: path.concat([id]).map(function (i) { return title(snapshot, i); }).join(' > ') });
        return;
      }
      if (done[id]) { return; }  // a part used in several assemblies is checked once
      done[id] = true;
      lines.push({ item_id: id, title: title(snapshot, id), depth: depth });
      children(snapshot, id).forEach(function (child) { visit(child, depth + 1, path.concat([id])); });
    }
    visit(rootId, 0, []);
    return { bom: lines, cycles: cycles };
  }

  function readiness(snapshot, rootId, pending) {
    var walked = walkBom(snapshot, rootId);
    var bom = walked.bom, issues = walked.cycles.slice();
    var items = bom.map(function (line) { return snapshot.items[line.item_id] || { id: line.item_id }; });

    items.forEach(function (item) {
      FIELDS.forEach(function (field) {
        if (!fieldValue(item, field).trim()) {
          issues.push({ item_id: item.id, title: item.title || '', kind: KIND.MISSING, field: field, detail: '' });
        }
      });
    });
    items.forEach(function (item) {
      var description = fieldValue(item, 'description');
      if (description.indexOf(PROPOSED_PREFIX) === 0) {
        issues.push({ item_id: item.id, title: item.title || '', kind: KIND.UNAPPROVED, field: 'description', detail: description });
      }
    });

    var inBom = {};
    bom.forEach(function (line) { inBom[line.item_id] = true; });
    (pending || []).forEach(function (record) {
      if (inBom[record.item_id]) {
        issues.push({ item_id: record.item_id, title: record.title, kind: KIND.PENDING, field: record.field,
          detail: 'proposal ' + record.proposal_id + ': ' + quote(record.value) });
      }
    });

    var users = {};  // part number -> titles of every item in the collab space and the BOM using it
    var all = {};
    Object.keys(snapshot.items).forEach(function (id) { all[id] = snapshot.items[id]; });
    items.forEach(function (item) { all[item.id] = item; });
    Object.keys(all).forEach(function (id) {
      var number = partNumber(all[id]);
      if (number) { (users[number] = users[number] || []).push(all[id].title || id); }
    });
    items.forEach(function (item) {
      var number = partNumber(item);
      var others = (users[number] || []).filter(function (t) { return t !== item.title; });
      if (number && others.length) {
        issues.push({ item_id: item.id, title: item.title || '', kind: KIND.DUPLICATE, field: 'partNumber',
          detail: number + ' also on ' + others.slice().sort(cmp).join(', ') });
      }
    });

    var order = {};
    bom.forEach(function (line, n) { order[line.item_id] = n; });
    issues.sort(function (a, b) {
      var oa = a.item_id in order ? order[a.item_id] : bom.length;
      var ob = b.item_id in order ? order[b.item_id] : bom.length;
      return (oa - ob) || cmp(a.kind, b.kind) || cmp(a.field, b.field);
    });
    return { root_id: rootId, root_title: title(snapshot, rootId), fields: FIELDS.slice(), bom: bom, issues: issues,
      ready: issues.length === 0 };
  }

  function summary(report) {
    if (report.ready) { return 'READY: ' + report.bom.length + ' items checked'; }
    var kinds = {}, ids = {};
    report.issues.forEach(function (i) { kinds[i.kind] = (kinds[i.kind] || 0) + 1; ids[i.item_id] = true; });
    var counts = Object.keys(kinds).sort(cmp).map(function (k) { return k + ' ' + kinds[k]; }).join(', ');
    return 'NOT READY: ' + report.issues.length + ' issues on ' + Object.keys(ids).length + ' of ' +
      report.bom.length + ' items (' + counts + ')';
  }

  // ---- duplicate detection (agent/duplicates.py) ----

  function words(text) {
    text = String(text || '')
      .replace(/(\d+)\s+(\d+\/\d+)/g, '$1+$2')  // 1 1/4" -> 1+1/4, so it stays apart from 1"
      .replace(/(\d)\s+(mm|cm|m|kw|w|v|kg|g)\b/gi, '$1$2')  // 22 mm -> 22mm
      .toLowerCase();
    var found = text.match(/\d+(?:[./+]\d+)+|[0-9a-z]+/g) || [];
    var set = {};
    found.forEach(function (w) { set[w] = true; });
    return set;
  }

  function keys(set) { return Object.keys(set); }
  function union(a, b) { var u = {}; keys(a).forEach(function (w) { u[w] = true; }); keys(b).forEach(function (w) { u[w] = true; }); return u; }
  function intersection(a, b) { var i = {}; keys(a).forEach(function (w) { if (b[w]) { i[w] = true; } }); return i; }
  function minus(a, b) { return keys(a).filter(function (w) { return !b[w]; }); }

  function specs(set) {
    var s = {};
    keys(set).forEach(function (w) { if (/\d/.test(w)) { s[w] = true; } });
    return s;
  }

  function descriptionOf(item) {
    var description = fieldValue(item, 'description');
    return description.indexOf(PROPOSED_PREFIX) === 0 ? '' : description;  // an unapproved AI value is not evidence
  }

  function profile(itemTitle, description, material, kids) {
    var descriptionWords = words(description);
    var all = union(words(itemTitle), descriptionWords);
    var childSet = {};
    (kids || []).forEach(function (c) { childSet[c] = true; });
    return { words: all, descriptionWords: descriptionWords,
      specs: specs(keys(descriptionWords).length ? descriptionWords : all),
      material: String(material || '').trim().toLowerCase(), children: childSet };
  }

  function Index(snapshot) {
    var self = this;
    this.snapshot = snapshot;
    this.profiles = {};
    Object.keys(snapshot.items).forEach(function (id) {
      var item = snapshot.items[id];
      self.profiles[id] = profile(item.title || '', descriptionOf(item), fieldValue(item, 'material'), children(snapshot, id));
    });
    this.n = Object.keys(this.profiles).length;
    var df = {};
    Object.keys(this.profiles).forEach(function (id) {
      keys(self.profiles[id].words).forEach(function (w) { df[w] = (df[w] || 0) + 1; });
    });
    this.idf = {};
    Object.keys(df).forEach(function (w) { self.idf[w] = Math.log(self.n / df[w]); });  // a word in every item weighs 0
    this.postings = {};
    Object.keys(this.profiles).forEach(function (id) {
      keys(self.profiles[id].words).forEach(function (w) {
        if (self.idf[w] > 0) { (self.postings[w] = self.postings[w] || []).push(id); }
      });
    });
  }

  Index.prototype.weight = function (w) {
    return w in this.idf ? this.idf[w] : Math.log(this.n + 1);  // a word no item has is as rare as it gets
  };

  Index.prototype.similarity = function (a, b) {
    var self = this, total = 0, shared = 0;
    keys(union(a, b)).forEach(function (w) { total += self.weight(w); });
    keys(intersection(a, b)).forEach(function (w) { shared += self.weight(w); });
    return total ? shared / total : 0;
  };

  Index.prototype.compare = function (a, b, sameKind) {
    var aKids = keys(a.children).length, bKids = keys(b.children).length;
    if (sameKind !== false && (aKids > 0) !== (bKids > 0)) { return null; }
    if (minus(a.specs, b.specs).length && minus(b.specs, a.specs).length) { return null; }  // variants
    if (a.material && b.material && a.material !== b.material) { return null; }

    var self = this;
    var text = this.similarity(a.words, b.words);
    if (keys(a.descriptionWords).length && keys(b.descriptionWords).length) {
      text = Math.max(text, this.similarity(a.descriptionWords, b.descriptionWords));
    }
    var sharedKids = keys(intersection(a.children, b.children)).length;
    var allKids = keys(union(a.children, b.children)).length;
    var structure = aKids && bKids ? sharedKids / allKids : 0;

    var reasons = [];
    var shared = keys(intersection(a.words, b.words))
      .sort(function (x, y) { return (self.weight(y) - self.weight(x)) || cmp(x, y); })
      .filter(function (w) { return self.weight(w) > 0; })
      .slice(0, MAX_REASON_WORDS);
    if (shared.length) { reasons.push('shared words: ' + shared.join(', ')); }
    if (structure) { reasons.push('same children: ' + sharedKids + ' of ' + allKids); }
    if (a.material && a.material === b.material) { reasons.push('same material: ' + a.material); }
    var sameSpecs = keys(intersection(a.specs, b.specs)).sort(cmp);
    if (sameSpecs.length) { reasons.push('same specs: ' + sameSpecs.join(', ')); }
    return { score: Math.max(text, structure), reasons: reasons };
  };

  function round3(x) { return Math.round(x * 1000) / 1000; }

  function findDuplicates(snapshot, minScore) {
    minScore = minScore === undefined ? MIN_SCORE : minScore;
    var index = new Index(snapshot), pairs = {};
    function add(a, b) { if (a < b) { pairs[a + '\u0000' + b] = [a, b]; } }
    Object.keys(index.profiles).forEach(function (id) {
      keys(index.profiles[id].words).forEach(function (w) {
        (index.postings[w] || []).forEach(function (other) { add(id, other); });
      });
    });
    var byChild = {};
    Object.keys(index.profiles).forEach(function (id) {
      keys(index.profiles[id].children).forEach(function (c) { (byChild[c] = byChild[c] || []).push(id); });
    });
    Object.keys(byChild).forEach(function (c) {
      byChild[c].forEach(function (a) { byChild[c].forEach(function (b) { add(a, b); }); });
    });

    var found = [];
    Object.keys(pairs).forEach(function (key) {
      var a = pairs[key][0], b = pairs[key][1];
      var result = index.compare(index.profiles[a], index.profiles[b], true);
      if (result && result.score >= minScore) {
        found.push({ item_id: a, title: title(snapshot, a), other_id: b, other_title: title(snapshot, b),
          score: round3(result.score), reasons: result.reasons });
      }
    });
    found.sort(function (x, y) { return (y.score - x.score) || cmp(x.title, y.title) || cmp(x.other_title, y.other_title); });
    return found;
  }

  function findExisting(snapshot, newTitle, description, material, minScore, limit) {
    minScore = minScore === undefined ? MIN_SCORE : minScore;
    var index = new Index(snapshot), fresh = profile(newTitle || '', description || '', material || '', []);
    var found = [];
    Object.keys(index.profiles).forEach(function (id) {
      var result = index.compare(fresh, index.profiles[id], false);  // the new item's children are not known yet
      if (result && result.score >= minScore) {
        found.push({ item_id: '', title: newTitle || description, other_id: id, other_title: title(snapshot, id),
          score: round3(result.score), reasons: result.reasons });
      }
    });
    found.sort(function (x, y) { return (y.score - x.score) || cmp(x.other_title, y.other_title); });
    return found.slice(0, limit || 10);
  }

  return {
    FIELDS: FIELDS, PROPOSED_PREFIX: PROPOSED_PREFIX, MIN_SCORE: MIN_SCORE, KIND: KIND,
    partNumber: partNumber, fieldValue: fieldValue,
    walkBom: walkBom, readiness: readiness, summary: summary,
    words: words, findDuplicates: findDuplicates, findExisting: findExisting
  };
});
