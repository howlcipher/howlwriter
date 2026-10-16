"""Source Intelligence: evidence-grounded projects.

A project is a user-selected folder of materials -- instructions, rubrics,
references, packet captures, screenshots, videos, drafts -- plus a private
workspace that records what each file is, what was extracted from it, where
exactly each piece of evidence came from, what the task requires, and what
browser research or lab actions were performed.

Four kinds of information are kept apart, each with its own provenance:

* **Task instructions** decide what must be produced (the requirements
  ledger). They are never evidence that work was done.
* **Source evidence** decides factual content (the evidence library). Each
  item carries an exact location and an evidence status; nothing is cited
  that was not extracted.
* **Voice** decides expression. It comes only from a personal voice profile
  (`howlwriter.voice`); no project material ever enters a voice corpus
  without the separate authorship-confirmation workflow.
* **Lab and browser actions** are an audit trail of what was observed or
  done, with whether state changed.

The workspace lives under ``~/.howlwriter/projects/<project-id>/``
(``HOWLWRITER_PROJECTS_DIR`` overrides), owner-only, refused inside an
unignored Git worktree. Source files are read, never modified.
"""
