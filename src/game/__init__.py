"""Budget Game — a daily variable-spend streak game for David & Steph.

Card-agnostic: pulls every connected credit card via SimpleFIN and classifies
each transaction's money-type; only Variable discretionary spend enters the
game. Per-user caps and streaks. Lives in Stavid so it shares the bot's Discord
connection, Postgres, and the #bills NLP ledger.

Pure logic is in `core`; I/O (SimpleFIN, Anthropic) is isolated in siblings so
the money paths stay unit-testable offline.
"""
