kills (Agent Skills) → Très important en 2026
Créer et charger des SKILL.md (fichiers dans .claude/skills/).
Chaque skill est un « playbook » que l’agent peut invoquer automatiquement.
Utile pour tes templates Cirqix (ex: skill « Extraction Factures », skill « Deep Research », skill « Support Client en arabe »).
MCP (Model Context Protocol)
Créer ou connecter des MCP servers pour outils custom (ex: intégration WhatsApp, Google Sheets, Odoo, PDF avancé, base de données tunisienne…).
C’est la façon propre et moderne de définir des outils externes dans le SDK.
Subagents
Définir et lancer des sous-agents spécialisés avec contexte isolé.
Exemple : un sub-agent « Researcher », un sub-agent « Critic » (pour vérifier les hallucinations), un sub-agent « Writer ».
Parfait pour des deep agents multi-étapes.
Hooks (lifecycle hooks)
Intercepter les événements (avant/après tool call, après pensée, etc.) pour ajouter du logging, de la validation, ou du human-in-the-loop.
File Checkpointing & Persistance
Sauvegarder/reprendre l’état des fichiers et sessions.
Essentiel pour que les utilisateurs de Cirqix puissent lancer un agent, partir, et revenir plus tard.
Permissions & Sécurité
Configurer les droits des outils (quels outils sont autorisés, budget max, sandbox).
Très important en SaaS pour éviter les abus et contrôler les coûts.
Subagents + Parallel execution
Lancer plusieurs sub-agents en parallèle (ex: recherche sur plusieurs sources en même temps).