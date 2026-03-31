# src/server/domain/entity_registry/__init__.py
"""Entity Registry — shared entity layer for cross-system integration.

Extends the existing security_master identity tables with:
- Classification taxonomy (GICS, CICS, 申万 industries)
- Corporate relations (parent/child, cross-listed, same-entity)
- Entity events (name changes, ticker changes, IPO, delisting, M&A)
- Market snapshots (shares outstanding, market cap, index membership)
"""
