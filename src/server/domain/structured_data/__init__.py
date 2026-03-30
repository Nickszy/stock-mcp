# src/server/domain/structured_data/__init__.py
"""Structured data platform — multi-source ingestion, validation, and canonical publishing.

Pipeline: fetch -> raw_snapshot -> normalize -> compare -> validate -> publish/review -> canonical
"""
