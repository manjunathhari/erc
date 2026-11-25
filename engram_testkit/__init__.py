"""Engram Comparative Conversation Test Kit (engram_testkit).

Runs the same questions, with the same answer model, against each configuration (arms A to D and a
"no memory" floor), saves every call, and scores the answers. In this shell every arm is bound to the
stub memory, so every output says: simulated arms (stub), not a Stage 4 comparison.

The kit names no model and opens no network connection. The caller passes the answer and judge
callables, and the run freeze names their models.
"""
