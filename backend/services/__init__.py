"""Services métier du pipeline : prompt_optimizer, mesh_repair, quality_scorer.

Chaque service est indépendant, testable isolément, et ne dépend que de
`config.py` + des libs externes (anthropic, trimesh, etc.).
"""
