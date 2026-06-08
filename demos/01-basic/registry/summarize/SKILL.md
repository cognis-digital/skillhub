---
name: summarize
version: 2.1.0
description: Summarize a block of text into a short abstract.
author: skillhub-demo
tags: [nlp, text, summary]
requires: [web-fetch]
---

# summarize

Summarize text into a concise abstract. When given a URL instead of raw text,
delegate to the `web-fetch` skill first, then summarize the fetched body.

## Usage

Provide `text` (or `url`) and an optional `max_sentences` (default 3).
