# Glossary

What each term IS (concept first), why this project needs it, and where it lives in the code.
Maintained with `mem term add`. Sorted A-Z.

## ADR
- what: Architecture Decision Record: a short dated document stating one decision, its context, the alternatives rejected and the consequences
- why: answers 'why is it like this?' long after the chat is gone; linked to the code it affects
- analogy: the minutes of a meeting, but only for decisions
- how-here: docs/adr/, src/infinite/adr.py

## FTS5
- what: SQLite's built-in full-text search engine: an inverted index from words to the rows containing them, ranked with BM25
- why: lets mem and the code atlas search thousands of notes, symbols and doc chunks in milliseconds with zero dependencies
- analogy: the index at the back of a book: look up a word, get the pages
- how-here: src/infinite/core.py (notes_fts), src/infinite/atlas.py (sym_fts, chunk_fts)
- see: BM25, porter stemming

## Summary tree
- what: binary tree over memories: leaves are notes, each parent is a one-line summary of its two children; recent notes stay verbatim, old ones are seen through coarse summaries
- why: fits unlimited memory into a fixed reading budget at session start without losing anything (zoom descends)
- analogy: a map that shows streets near you and only cities far away
- how-here: src/infinite/tree.py (cover, pending, zoom)
- see: OptMem, nap
