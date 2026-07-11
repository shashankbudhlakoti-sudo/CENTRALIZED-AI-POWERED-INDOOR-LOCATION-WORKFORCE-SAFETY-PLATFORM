-- ============================================================
-- contracts/seed.sql
-- Seeds 2 real employees + tags, matching the beacon UUIDs
-- decoded from the phone beacon app (shashank-tag, kartikeya-tag
-- in ingestion/laptop_scanner.py).
--
-- One employee in a general department, one in Finance —
-- lets you actually test RLS department isolation with real
-- hardware data, not just fake INSERTs.
-- ============================================================

INSERT INTO employees (employee_code, full_name, department, consent_given)
VALUES
    ('EMP-001', 'Shashank Budhlakoti', 'security', true),
    ('EMP-002', 'Kartikeya', 'finance', true)
ON CONFLICT (employee_code) DO NOTHING;

INSERT INTO tags (tag_uid, employee_id)
VALUES
    ('shashank-tag', (SELECT id FROM employees WHERE employee_code = 'EMP-001')),
    ('kartikeya-tag', (SELECT id FROM employees WHERE employee_code = 'EMP-002'))
ON CONFLICT (tag_uid) DO NOTHING;

-- Quick verify after running:
-- SELECT e.full_name, e.department, t.tag_uid FROM employees e JOIN tags t ON t.employee_id = e.id;
