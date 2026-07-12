"""Convo-Commerce multi-agent brain, built on the Google Agent Development Kit.

A root orchestrator agent delegates each customer message to the right
specialist sub-agent (ordering, checkout, tracking/follow-up, refunds,
recommendations). All specialists act on the shared Supabase-backed tools.
"""
