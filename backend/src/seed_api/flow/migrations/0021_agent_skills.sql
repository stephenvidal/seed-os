-- The shared skills each agent may use (M8, D-033), like its tools. An agent's
-- private skills (skills.agent_id) are always its own and are not listed here.
ALTER TABLE agents ADD COLUMN skills uuid[] NOT NULL DEFAULT '{}';
