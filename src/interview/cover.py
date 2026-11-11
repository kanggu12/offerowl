"""How well the kit's scenes cover one line (of a posting, or any planned question).

The line's content words are its key terms. For every item, a term counts when the item uses the word, a word of its
synonym group, or (for a Korean word of three syllables or more) all of the word's syllable pairs. An item is about
the line when one of the terms is in its title, key line, first interviewer line or alternate phrasings.
  - strong: an item uses at least `strong` of the terms (default 60 percent), is about the line, and is a scene or a
    resume deep dive (a "what is X" term entry explains a word; it does not show that you did the thing);
  - weak:   an item uses at least `weak` of the terms (default 30 percent);
  - none:   no item does.
A scene's words are those it says: the titles, the key line and the dialogue in both languages. The writer's notes
under a scene often quote the posting line they answer, so they are left out (kit "coverage": {"spoken": false}
counts every word of the item, the looser rule of earlier versions). The covering items are the best three at or
above the weak share. The rule is plain on purpose: it says which posting lines still need a scene, and its numbers
can be read in the audit file.
"""
import re  # Hangul test

from interview import text as T  # words, synonyms


def first_question(it):
    """The item's first interviewer line, from its markdown (empty when it has none)."""
    m = re.search(r"\*\*면접관\*\*\s*[:：]?\s*(.+)", it.get("md") or "")  # "**면접관** text" or "- **면접관**: text"
    return m.group(1).strip() if m else ""  # the line as written


def bigrams(w):  # Korean compounds are matched by their syllable pairs
    """Syllable pairs of a Korean word."""
    return {w[i:i + 2] for i in range(len(w) - 1)}  # every two adjacent syllables


class Coverage:  # built once per kit, then reused for every line
    """Item word bags built once, then any number of lines rated against them."""

    def __init__(self, items, alts, kit):  # items and their phrasings from the corpus, settings from kit.json
        self.syn = T.synonyms(kit.get("synonyms"))  # synonym groups
        cfg = kit.get("coverage") or {}  # thresholds from kit.json
        # the shares of key terms an item needs for a strong or a weak rating
        self.strong, self.weak = float(cfg.get("strong", 0.6)), float(cfg.get("weak", 0.3))
        self.strong_roles = set(cfg.get("strong_roles") or ("scenes", "deep"))  # the roles that can make a line strong
        spoken = cfg.get("spoken", True)  # count only what a scene says, not the writer's notes under it
        self.items = [it for it in items if it.get("role") != "reference"]  # notes and stories answer nothing by themselves
        self.bags, self.heads, self.pairs = [], [], []  # per item: every word, title words, Korean syllable pairs
        for it in self.items:  # one entry per item, in the same order as self.items
            said = spoken and (it["en"] or it["ko"])  # an item with dialogue or answer fields is measured on them
            # the words the item says: both titles, the key line and the dialogue; or every word when it has no dialogue
            bag = set(T.words(" ".join((it["tko"], it["ten"], it["key"], it["en"], it["ko"]) if said else (it["tko"], it["ten"], it["key"], it["text"]))))
            self.bags.append(bag)  # used to count how many terms the item uses
            first_q = first_question(it)  # the interviewer's first line says what the scene is about, like its title
            # the words that say what the item is about: titles, key line, first question and alternate phrasings
            self.heads.append(set(T.words(" ".join([it["tko"], it["ten"], it["key"], first_q] + list(alts.get(it["id"], []))))))
            # syllable pairs of the item's Korean words, so a long Korean term can match a compound written another way
            self.pairs.append(set().union(*(bigrams(w) for w in bag if re.match(r"[가-힣]", w))) if bag else set())

    def _has(self, term, bag, pairs):  # one term against one item
        """Does a bag hold the term, a synonym of it, or (Korean) all its syllable pairs?"""
        if term in bag or (self.syn.get(term, set()) & bag):  # the word itself or any word of its synonym group
            return True
        return bool(re.match(r"[가-힣]{3,}$", term)) and bigrams(term) <= pairs  # long Korean words: every pair present

    def rate(self, line):  # called once per posting line or planned question
        """(rating, [(id, share)] of the covering items, key terms) for one line."""
        terms = list(dict.fromkeys(T.words(line)))  # unique key terms in order
        if not terms:  # nothing to look for (a heading, a date)
            return "none", [], terms  # nothing can cover a line without content words
        scored = []  # (share, about, id)
        for it, bag, head, pairs in zip(self.items, self.bags, self.heads, self.pairs):  # each item with its word sets
            hits = sum(1 for t in terms if self._has(t, bag, pairs))  # terms the item uses
            if not hits:  # an item that uses no term is no candidate
                continue
            about = any(self._has(t, head, set()) for t in terms)  # a term in its title, key line, first question or phrasings
            scored.append((hits / len(terms), about, it["id"], it.get("role") in self.strong_roles))  # the share of terms the item uses
        scored.sort(key=lambda x: (-x[0], -x[1], -x[3]))  # best share first, items about the line before others, scenes before terms
        cover = [(i, round(s, 2)) for s, a, i, _ in scored if s >= self.weak][:3]  # the covering items
        if any(s >= self.strong and a and real for s, a, _, real in scored):  # strong needs a high share, the line's topic and a scene
            return "strong", cover, terms  # the covering items are listed either way
        return ("weak" if cover else "none"), cover, terms  # weak when some item reaches the weak share
