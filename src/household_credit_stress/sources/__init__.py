"""Fetch and parse the public data the stress test runs on.

Each module handles one publisher. Parsing is kept apart from downloading, so the tests
can feed saved responses to the parsers without touching the network.
"""
