-- E2E seed data: deterministic UUIDs, idempotent via ON CONFLICT DO NOTHING.
-- Run against the local `decision_hub` database before E2E tests.

BEGIN;

-- =====================================================================
-- Users
-- =====================================================================
INSERT INTO users (id, github_id, username)
VALUES (
    'aaaaaaaa-0000-0000-0000-000000000001',
    '99901',
    'e2e-bot'
) ON CONFLICT DO NOTHING;

-- =====================================================================
-- Organizations
-- =====================================================================
INSERT INTO organizations (id, slug, owner_id, description)
VALUES (
    'bbbbbbbb-0000-0000-0000-000000000001',
    'test-org',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'Test Organization for E2E'
) ON CONFLICT DO NOTHING;

INSERT INTO organizations (id, slug, owner_id, description)
VALUES (
    'bbbbbbbb-0000-0000-0000-000000000002',
    'acme-corp',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'Acme Corporation'
) ON CONFLICT DO NOTHING;

-- =====================================================================
-- Org members (owner role for both orgs)
-- =====================================================================
INSERT INTO org_members (org_id, user_id, role)
VALUES (
    'bbbbbbbb-0000-0000-0000-000000000001',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'owner'
) ON CONFLICT DO NOTHING;

INSERT INTO org_members (org_id, user_id, role)
VALUES (
    'bbbbbbbb-0000-0000-0000-000000000002',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'owner'
) ON CONFLICT DO NOTHING;

-- =====================================================================
-- Skills
-- =====================================================================

-- 1. test-org/data-analyzer
INSERT INTO skills (
    id, org_id, name, description, category,
    download_count, latest_semver, latest_eval_status,
    latest_published_at, latest_published_by
) VALUES (
    'cccccccc-0000-0000-0000-000000000001',
    'bbbbbbbb-0000-0000-0000-000000000001',
    'data-analyzer',
    'Analyze datasets with statistical methods and generate visual reports',
    'Data Science & Statistics',
    142, '1.2.0', 'A',
    now() - interval '3 days', 'e2e-bot'
) ON CONFLICT DO NOTHING;

-- 2. test-org/code-reviewer
INSERT INTO skills (
    id, org_id, name, description, category,
    download_count, latest_semver, latest_eval_status,
    latest_published_at, latest_published_by
) VALUES (
    'cccccccc-0000-0000-0000-000000000002',
    'bbbbbbbb-0000-0000-0000-000000000001',
    'code-reviewer',
    'Automated code review with best practices and security checks',
    'Coding & Development',
    87, '0.5.0', 'B',
    now() - interval '7 days', 'e2e-bot'
) ON CONFLICT DO NOTHING;

-- 3. acme-corp/deploy-helper
INSERT INTO skills (
    id, org_id, name, description, category,
    download_count, latest_semver, latest_eval_status,
    latest_published_at, latest_published_by
) VALUES (
    'cccccccc-0000-0000-0000-000000000003',
    'bbbbbbbb-0000-0000-0000-000000000002',
    'deploy-helper',
    'Streamline deployments to cloud providers with safety checks',
    'DevOps & Infrastructure',
    310, '2.0.1', 'A',
    now() - interval '1 day', 'e2e-bot'
) ON CONFLICT DO NOTHING;

-- 4. acme-corp/ml-pipeline
INSERT INTO skills (
    id, org_id, name, description, category,
    download_count, latest_semver, latest_eval_status,
    latest_published_at, latest_published_by
) VALUES (
    'cccccccc-0000-0000-0000-000000000004',
    'bbbbbbbb-0000-0000-0000-000000000002',
    'ml-pipeline',
    'Build and orchestrate machine learning training pipelines',
    'Data Science & Statistics',
    56, '1.0.0', 'A',
    now() - interval '14 days', 'e2e-bot'
) ON CONFLICT DO NOTHING;

-- =====================================================================
-- Versions
-- =====================================================================

-- data-analyzer v1.0.0 (older version, eval B)
INSERT INTO versions (
    id, skill_id, semver, semver_major, semver_minor, semver_patch,
    s3_key, checksum, eval_status, published_by, created_at
) VALUES (
    'dddddddd-0000-0000-0000-000000000001',
    'cccccccc-0000-0000-0000-000000000001',
    '1.0.0', 1, 0, 0,
    'skills/test-org/data-analyzer/1.0.0.tar.gz',
    'sha256:e2e0000000000000000000000000000000000000000000000000000000000001',
    'B', 'e2e-bot',
    now() - interval '30 days'
) ON CONFLICT DO NOTHING;

-- data-analyzer v1.2.0 (latest, eval A)
INSERT INTO versions (
    id, skill_id, semver, semver_major, semver_minor, semver_patch,
    s3_key, checksum, eval_status, published_by, created_at
) VALUES (
    'dddddddd-0000-0000-0000-000000000002',
    'cccccccc-0000-0000-0000-000000000001',
    '1.2.0', 1, 2, 0,
    'skills/test-org/data-analyzer/1.2.0.tar.gz',
    'sha256:e2e0000000000000000000000000000000000000000000000000000000000002',
    'A', 'e2e-bot',
    now() - interval '3 days'
) ON CONFLICT DO NOTHING;

-- code-reviewer v0.5.0
INSERT INTO versions (
    id, skill_id, semver, semver_major, semver_minor, semver_patch,
    s3_key, checksum, eval_status, published_by, created_at
) VALUES (
    'dddddddd-0000-0000-0000-000000000003',
    'cccccccc-0000-0000-0000-000000000002',
    '0.5.0', 0, 5, 0,
    'skills/test-org/code-reviewer/0.5.0.tar.gz',
    'sha256:e2e0000000000000000000000000000000000000000000000000000000000003',
    'B', 'e2e-bot',
    now() - interval '7 days'
) ON CONFLICT DO NOTHING;

-- deploy-helper v2.0.1
INSERT INTO versions (
    id, skill_id, semver, semver_major, semver_minor, semver_patch,
    s3_key, checksum, eval_status, published_by, created_at
) VALUES (
    'dddddddd-0000-0000-0000-000000000004',
    'cccccccc-0000-0000-0000-000000000003',
    '2.0.1', 2, 0, 1,
    'skills/acme-corp/deploy-helper/2.0.1.tar.gz',
    'sha256:e2e0000000000000000000000000000000000000000000000000000000000004',
    'A', 'e2e-bot',
    now() - interval '1 day'
) ON CONFLICT DO NOTHING;

-- ml-pipeline v1.0.0
INSERT INTO versions (
    id, skill_id, semver, semver_major, semver_minor, semver_patch,
    s3_key, checksum, eval_status, published_by, created_at
) VALUES (
    'dddddddd-0000-0000-0000-000000000005',
    'cccccccc-0000-0000-0000-000000000004',
    '1.0.0', 1, 0, 0,
    'skills/acme-corp/ml-pipeline/1.0.0.tar.gz',
    'sha256:e2e0000000000000000000000000000000000000000000000000000000000005',
    'A', 'e2e-bot',
    now() - interval '14 days'
) ON CONFLICT DO NOTHING;

COMMIT;
