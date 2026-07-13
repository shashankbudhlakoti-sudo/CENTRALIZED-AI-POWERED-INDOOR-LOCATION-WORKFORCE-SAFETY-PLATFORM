-- ============================================================
-- contracts/seed.sql
-- 5 employees per department (25 total), matching the 5 Keycloak
-- test users' departments (hr, it, finance, security, general).
--
-- The 2 real physical beacons (decoded from the phone beacon app,
-- same UUID, Major/Minor 1,1 and 2,2) are assigned to one IT
-- employee and one Finance employee, per current hardware setup.
-- ============================================================

-- ------------------------------------------------------------
-- HR department (5)
-- ------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, department, consent_given) VALUES
    ('EMP-HR-01', 'Aditi Sharma',   'hr', true),
    ('EMP-HR-02', 'Rohan Gupta',    'hr', true),
    ('EMP-HR-03', 'Priya Nair',     'hr', true),
    ('EMP-HR-04', 'Vikram Singh',   'hr', true),
    ('EMP-HR-05', 'Neha Joshi',     'hr', true)
ON CONFLICT (employee_code) DO NOTHING;

-- ------------------------------------------------------------
-- IT department (5) — EMP-IT-01 gets the real beacon
-- ------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, department, consent_given) VALUES
    ('EMP-IT-01', 'Shashank Budhlakoti', 'it', true),
    ('EMP-IT-02', 'Arjun Mehta',         'it', true),
    ('EMP-IT-03', 'Kavya Reddy',         'it', true),
    ('EMP-IT-04', 'Siddharth Rao',       'it', true),
    ('EMP-IT-05', 'Ananya Iyer',         'it', true)
ON CONFLICT (employee_code) DO NOTHING;

-- ------------------------------------------------------------
-- Finance department (5) — EMP-FIN-01 gets the real beacon
-- ------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, department, consent_given) VALUES
    ('EMP-FIN-01', 'Kartikeya',       'finance', true),
    ('EMP-FIN-02', 'Meera Kapoor',    'finance', true),
    ('EMP-FIN-03', 'Rahul Verma',     'finance', true),
    ('EMP-FIN-04', 'Sanya Malhotra',  'finance', true),
    ('EMP-FIN-05', 'Aryan Kumar',     'finance', true)
ON CONFLICT (employee_code) DO NOTHING;

-- ------------------------------------------------------------
-- Security department (5)
-- ------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, department, consent_given) VALUES
    ('EMP-SEC-01', 'Manoj Tiwari',   'security', true),
    ('EMP-SEC-02', 'Deepak Yadav',   'security', true),
    ('EMP-SEC-03', 'Ritu Chauhan',   'security', true),
    ('EMP-SEC-04', 'Sameer Khan',    'security', true),
    ('EMP-SEC-05', 'Pooja Bhatt',    'security', true)
ON CONFLICT (employee_code) DO NOTHING;

-- ------------------------------------------------------------
-- General / management (5)
-- ------------------------------------------------------------
INSERT INTO employees (employee_code, full_name, department, consent_given) VALUES
    ('EMP-GEN-01', 'Rajesh Agarwal', 'general', true),
    ('EMP-GEN-02', 'Sunita Desai',   'general', true),
    ('EMP-GEN-03', 'Amit Bose',      'general', true),
    ('EMP-GEN-04', 'Kiran Rao',      'general', true),
    ('EMP-GEN-05', 'Vivek Menon',    'general', true)
ON CONFLICT (employee_code) DO NOTHING;

-- ------------------------------------------------------------
-- Tags — the 2 real physical beacons, assigned to real people
-- (matches KNOWN_BEACONS in ingestion/laptop_scanner.py)
-- ------------------------------------------------------------
INSERT INTO tags (tag_uid, employee_id) VALUES
    ('shashank-tag',  (SELECT id FROM employees WHERE employee_code = 'EMP-IT-01')),
    ('kartikeya-tag', (SELECT id FROM employees WHERE employee_code = 'EMP-FIN-01'))
ON CONFLICT (tag_uid) DO NOTHING;

-- Verify after running:
-- SELECT department, COUNT(*) FROM employees GROUP BY department ORDER BY department;
-- SELECT e.full_name, e.department, t.tag_uid FROM employees e JOIN tags t ON t.employee_id = e.id;
